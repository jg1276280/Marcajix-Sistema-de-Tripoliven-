from django.contrib.auth.models import User
from django.conf import settings
from django.test import TestCase, override_settings
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils import timezone
from datetime import date, timedelta
import json
import time
from employees.forms import EmployeeForm
from employees.models import Department, Employee, Management, Position
from .forms import LoginForm
from .models import UserSecurity, AttendanceLog, SecurityEvent
from .services import AttendanceRegistrationError, register_attendance
from core.test_utils import create_test_image as attendance_image, create_user_with_role
from .permissions import HUMAN_RESOURCES, SECURITY, SYSTEMS


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AuthenticationTests(TestCase):
    def setUp(self):
        self.user = create_user_with_role("login-user", SECURITY)

    def test_valid_login_resets_failed_attempts(self):
        UserSecurity.objects.create(user=self.user, failed_login_attempts=2)
        response = self.client.post("/login/", {"username": "login-user", "password": "ValidPassword123!"})
        self.assertRedirects(response, "/dashboard/")
        self.assertEqual(UserSecurity.objects.get(user=self.user).failed_login_attempts, 0)

    def test_authenticated_session_is_not_persistent_in_the_browser(self):
        self.client.login(username="login-user", password="ValidPassword123!")

        response = self.client.get("/dashboard/")

        self.assertEqual(response.status_code, 200)
        session_cookie = response.cookies.get(settings.SESSION_COOKIE_NAME)
        self.assertIsNotNone(session_cookie)
        self.assertEqual(session_cookie["max-age"], "")

    def test_session_older_than_twelve_hours_redirects_to_login(self):
        self.client.login(username="login-user", password="ValidPassword123!")
        session = self.client.session
        session["_marcajix_session_started_at"] = int(time.time()) - settings.SESSION_MAX_AGE - 1
        session.save()

        response = self.client.get("/dashboard/")

        self.assertRedirects(response, "/login/?next=/dashboard/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_repeated_failed_logins_lock_account_temporarily_without_deactivating_it(self):
        from .security import MAX_LOGIN_ATTEMPTS

        for _ in range(MAX_LOGIN_ATTEMPTS):
            form = LoginForm(data={"username": "login-user", "password": "WrongPassword123!"})
            self.assertFalse(form.is_valid())
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertGreater(self.user.security.locked_until, timezone.now())

        locked = LoginForm(data={"username": "login-user", "password": "ValidPassword123!"})
        self.assertFalse(locked.is_valid())
        self.assertEqual(locked.non_field_errors().as_data()[0].code, "locked")

        UserSecurity.objects.filter(user=self.user).update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(LoginForm(data={"username": "login-user", "password": "ValidPassword123!"}).is_valid())

    def test_login_errors_do_not_reveal_whether_the_user_exists(self):
        unknown = LoginForm(data={"username": "nobody", "password": "WrongPassword123!"})
        wrong_password = LoginForm(data={"username": "login-user", "password": "WrongPassword123!"})
        self.assertFalse(unknown.is_valid())
        self.assertFalse(wrong_password.is_valid())
        self.assertEqual(unknown.non_field_errors(), wrong_password.non_field_errors())

    def test_user_without_role_cannot_log_in(self):
        User.objects.create_user(username="no-role", password="ValidPassword123!")
        form = LoginForm(data={"username": "no-role", "password": "ValidPassword123!"})
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors().as_data()[0].code, "no_role")

    def test_public_registration_is_not_available(self):
        self.assertEqual(self.client.get("/registro/").status_code, 404)
        self.assertNotContains(self.client.get("/login/"), "Crear cuenta")


@override_settings(MEDIA_ROOT="test-media", STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AttendanceTests(TestCase):
    def setUp(self):
        self.management = Management.objects.create(name="Tecnología")
        self.department = Department.objects.create(name="Sistemas", management=self.management)
        self.position = Position.objects.create(name="Analista", department=self.department)
        self.employee = Employee.objects.create(full_name="Ana Pérez", identification="31395897", position=self.position, photo=attendance_image())
        self.user = create_user_with_role("attendance-user", SECURITY)

    def test_database_protects_employee_with_attendance_history(self):
        register_attendance(self.employee.pk, timezone.now(), AttendanceLog.ENTRY)
        with self.assertRaises(ProtectedError):
            self.employee.delete()

    def test_register_endpoint_returns_employee_data(self):
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}])})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["employee"], "Ana Pérez")

    def test_manual_endpoint_records_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}])})
        self.assertEqual(response.status_code, 201)
        log = AttendanceLog.objects.get()
        self.assertEqual(log.capture_mode, AttendanceLog.MANUAL)
        self.assertEqual(log.registered_by, self.user)

    def test_endpoint_rejects_non_manual_capture(self):
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "hid", "rows": "[]"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Marcajix solo permite registros manuales.")

    def test_manual_endpoint_handles_malformed_rows_without_500(self):
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}, "broken-row"])})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(len(response.json()["errors"]), 1)

    def test_manual_endpoint_registers_multiple_employees(self):
        operations = Management.objects.create(name="Operaciones")
        second_employee = Employee.objects.create(full_name="Luis Torres", identification="31395898", position=Position.objects.create(name="Analista", department=Department.objects.create(name="Finanzas", management=operations)), photo=attendance_image("second.png"))
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{ "employee_id": self.employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}, {"employee_id": second_employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}])})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(AttendanceLog.objects.count(), 2)

    def test_manual_endpoint_rejects_dates_outside_72_hours(self):
        self.client.force_login(self.user)
        old_date = (timezone.now() - timedelta(hours=73)).isoformat()
        future_date = (timezone.now() + timedelta(minutes=1)).isoformat()
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": old_date}, {"employee_id": self.employee.pk, "mark_type": "exit", "marked_at": future_date}])})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(response.json()["errors"]), 2)
        self.assertEqual(AttendanceLog.objects.count(), 0)

    def test_manual_endpoint_processes_valid_rows_and_returns_invalid_rows(self):
        operations = Management.objects.create(name="Operaciones")
        second_employee = Employee.objects.create(full_name="Luis Torres", identification="31395898", position=Position.objects.create(name="Analista", department=Department.objects.create(name="Finanzas", management=operations)), photo=attendance_image("partial.png"))
        self.client.force_login(self.user)
        valid_date = timezone.now().isoformat()
        invalid_date = (timezone.now() - timedelta(hours=73)).isoformat()
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": valid_date}, {"employee_id": second_employee.pk, "mark_type": "entry", "marked_at": invalid_date}])})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.json()["successes"]), 1)
        self.assertEqual(len(response.json()["errors"]), 1)
        self.assertEqual(AttendanceLog.objects.count(), 1)

    def test_vacation_employee_registers_with_warning(self):
        self.employee.status = self.employee.VACATION
        self.employee.save(update_fields=["status", "updated_at"])
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}])})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(AttendanceLog.objects.count(), 1)
        self.assertEqual(response.json()["warnings"][0]["employee_id"], self.employee.pk)

    def test_blocked_employee_creates_attempt_and_audit_without_attendance(self):
        from django.contrib.admin.models import LogEntry

        self.employee.status = self.employee.INACTIVE
        self.employee.save(update_fields=["status", "updated_at"])
        self.client.force_login(self.user)
        response = self.client.post("/dashboard/marcajes/registrar/", {"capture_mode": "manual", "rows": json.dumps([{"employee_id": self.employee.pk, "mark_type": "entry", "marked_at": timezone.now().isoformat()}])})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["code"], "blocked")
        self.assertEqual(AttendanceLog.objects.count(), 0)
        attempt = SecurityEvent.objects.get(event_type=SecurityEvent.BLOCKED_EMPLOYEE)
        self.assertEqual(attempt.employee_status, self.employee.INACTIVE)
        self.assertEqual(attempt.attempted_by, self.user)
        self.assertTrue(LogEntry.objects.filter(object_id=attempt.pk, change_message__contains="estatus Inactivo").exists())

    def test_exit_remains_allowed_for_an_open_session_even_when_status_changes(self):
        register_attendance(self.employee.pk, timezone.now() - timedelta(minutes=30), AttendanceLog.ENTRY)
        self.employee.status = self.employee.INACTIVE
        self.employee.save(update_fields=["status", "updated_at"])

        exit_log = register_attendance(self.employee.pk, timezone.now(), AttendanceLog.EXIT)

        self.assertEqual(exit_log.mark_type, AttendanceLog.EXIT)
        self.assertEqual(AttendanceLog.objects.filter(employee=self.employee).count(), 2)

    def test_historical_marks_are_validated_against_their_chronological_session(self):
        today = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
        yesterday_entry = today - timedelta(days=1, hours=1)
        yesterday_exit = today - timedelta(days=1, minutes=1)

        register_attendance(self.employee.pk, today, AttendanceLog.ENTRY)
        entry_log = register_attendance(self.employee.pk, yesterday_entry, AttendanceLog.ENTRY)
        exit_log = register_attendance(self.employee.pk, yesterday_exit, AttendanceLog.EXIT)

        self.assertEqual(entry_log.marked_at, yesterday_entry)
        self.assertEqual(exit_log.marked_at, yesterday_exit)
        self.assertEqual(AttendanceLog.objects.filter(employee=self.employee).count(), 3)

    def test_historical_exit_without_historical_entry_is_rejected(self):
        marked_at = timezone.now() - timedelta(days=1)

        with self.assertRaises(AttendanceRegistrationError) as context:
            register_attendance(self.employee.pk, marked_at, AttendanceLog.EXIT)

        self.assertEqual(context.exception.code, "exit_without_entry")

    def test_employee_search_returns_active_matches(self):
        self.client.force_login(self.user)
        response = self.client.get("/dashboard/marcajes/empleados/?q=Ana")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["employees"][0]["name"], "Ana Pérez")

    def test_employee_search_matches_card_code(self):
        self.employee.hid_card_code = "CARD-ATT-001"
        self.employee.save(update_fields=["hid_card_code", "updated_at"])
        self.client.force_login(self.user)
        response = self.client.get("/dashboard/marcajes/empleados/?q=CARD-ATT-001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["employees"][0]["id"], self.employee.pk)

    def test_attendance_page_does_not_preload_unused_attendance_data(self):
        self.client.force_login(self.user)
        with self.assertNumQueries(6):  # Incluye la consulta del rol del usuario (se cachea por petición).
            response = self.client.get("/dashboard/marcajes/")
        self.assertEqual(response.status_code, 200)

    def test_employee_search_uses_bounded_queries_for_last_mark(self):
        operations = Management.objects.create(name="Operaciones")
        second_employee = Employee.objects.create(full_name="Luis Torres", identification="31395898", position=Position.objects.create(name="Analista", department=Department.objects.create(name="Finanzas", management=operations)), photo=attendance_image("query-count.png"))
        register_attendance(self.employee.pk, timezone.now(), AttendanceLog.ENTRY)
        register_attendance(second_employee.pk, timezone.now(), AttendanceLog.ENTRY)
        self.client.force_login(self.user)
        with self.assertNumQueries(7):  # Incluye la consulta del rol del usuario (se cachea por petición).
            response = self.client.get("/dashboard/marcajes/empleados/?q=")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["employees"][0]["last_mark"], "Entrada")

    def test_employee_history_link_returns_all_paginated_events(self):
        from datetime import datetime, timedelta

        for offset in range(26):
            AttendanceLog.objects.create(
                employee=self.employee,
                marked_at=timezone.make_aware(datetime(2026, 1, 1) + timedelta(days=offset)),
                mark_type=AttendanceLog.ENTRY if offset % 2 == 0 else AttendanceLog.EXIT,
            )
        self.client.force_login(self.user)

        response = self.client.get(f"/dashboard/marcajes/historial/?employee={self.employee.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["date_from"], "")
        self.assertEqual(response.context["date_to"], "")
        self.assertEqual(response.context["page_obj"].paginator.count, 26)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)


@override_settings(STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class DataIntegrityTests(TestCase):
    def setUp(self):
        self.management = Management.objects.create(name="Operaciones")
        self.department = Department.objects.create(name="Logística", management=self.management)
        self.position = Position.objects.create(name="Analista", department=self.department)

    def _employee_payload(self, **overrides):
        payload = {
            "full_name": "Laura Gómez",
            "identification": "12345678",
            "hid_card_code": "CARD-001",
            "position": self.position.pk,
            "hire_date": date.today().isoformat(),
            "emergency_phone": "8091234567",
        }
        payload.update(overrides)
        return payload

    def test_employee_form_requires_hire_date_and_blocks_future_date(self):
        invalid_blank = EmployeeForm(data=self._employee_payload(hire_date=""))
        self.assertFalse(invalid_blank.is_valid())
        self.assertIn("hire_date", invalid_blank.errors)

        future_date = (date.today() + timedelta(days=1)).isoformat()
        invalid_future = EmployeeForm(data=self._employee_payload(hire_date=future_date))
        self.assertFalse(invalid_future.is_valid())
        self.assertIn("hire_date", invalid_future.errors)

    def test_duplicate_card_code_is_rejected(self):
        Employee.objects.create(
            full_name="Ana Pérez",
            identification="31395897",
            hid_card_code="CARD-001",
            position=self.position,
            photo=attendance_image("card-one.png"),
            hire_date=date.today(),
        )
        form = EmployeeForm(data=self._employee_payload(identification="31395898", hid_card_code="card-001"))
        self.assertFalse(form.is_valid())
        self.assertIn("hid_card_code", form.errors)

    def test_duplicate_entry_within_two_minutes_is_rejected(self):
        employee = Employee.objects.create(
            full_name="Rosa López",
            identification="31395899",
            hid_card_code="CARD-002",
            position=self.position,
            photo=attendance_image("card-two.png"),
            hire_date=date.today(),
        )
        now = timezone.now()
        register_attendance(employee.pk, now, AttendanceLog.ENTRY)
        with self.assertRaises(AttendanceRegistrationError):
            register_attendance(employee.pk, now + timedelta(seconds=30), AttendanceLog.ENTRY)

    def test_employee_detail_ignores_open_entry_when_building_hours(self):
        employee = Employee.objects.create(
            full_name="Miguel Silva",
            identification="31395900",
            hid_card_code="CARD-003",
            position=self.position,
            photo=attendance_image("card-three.png"),
            hire_date=date.today(),
        )
        self.client.force_login(create_user_with_role("detail-checker", HUMAN_RESOURCES))
        AttendanceLog.objects.create(
            employee=employee,
            marked_at=timezone.now() - timedelta(hours=2),
            mark_type=AttendanceLog.ENTRY,
        )
        response = self.client.get(reverse("employees:detail", args=[employee.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_hours"], 0)
        self.assertTrue(response.context["open_session"])

@override_settings(MEDIA_ROOT="test-media", STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class AttendanceServiceTests(TestCase):
    def setUp(self):
        department = Department.objects.create(name="Seguridad", management=Management.objects.create(name="Operaciones"))
        self.employee = Employee.objects.create(full_name="Pedro Ruiz", identification="31395901", hid_card_code="CARD-777", position=Position.objects.create(name="Vigilante", department=department), photo=attendance_image("service.png"))

    def test_next_mark_type_alternates_between_entry_and_exit(self):
        from .services import next_mark_type

        self.assertEqual(next_mark_type(self.employee), AttendanceLog.ENTRY)
        register_attendance(self.employee.pk, timezone.now() - timedelta(minutes=10), AttendanceLog.ENTRY, capture_mode=AttendanceLog.HID)
        self.assertEqual(next_mark_type(self.employee), AttendanceLog.EXIT)
        register_attendance(self.employee.pk, timezone.now(), AttendanceLog.EXIT, capture_mode=AttendanceLog.HID)
        self.assertEqual(next_mark_type(self.employee), AttendanceLog.ENTRY)

    def test_unknown_card_is_recorded_as_security_event(self):
        from .services import record_unknown_card

        record_unknown_card("CARD-999", "HID · Garita")
        event = SecurityEvent.objects.get()
        self.assertEqual(event.event_type, SecurityEvent.UNKNOWN_CARD)
        self.assertEqual(event.hid_card_code, "CARD-999")
        self.assertIsNone(event.employee)

    def test_history_lists_unknown_card_events(self):
        from .services import record_unknown_card

        record_unknown_card("CARD-999", "HID · Garita")
        self.client.force_login(create_user_with_role("history-viewer", SECURITY))
        response = self.client.get(reverse("attendance_history"), {"q": "CARD-999"})
        self.assertContains(response, "Tarjeta no reconocida")

    def test_hid_listener_registers_cards_and_reports_status(self):
        import sys
        import types
        from unittest import mock

        from .hid_listener import listen_hid_reader
        from .models import HIDReaderConfig

        class StopListening(Exception):
            pass

        class FakeSerial:
            lines = [b"CARD-777\r\n", b"", b"CARD-777\r\n"]  # La segunda lectura es un rebote y se ignora.

            def __init__(self, **kwargs):
                pass

            def readline(self):
                if not self.lines:
                    raise StopListening
                return self.lines.pop(0)

            def close(self):
                pass

        fake_serial = types.SimpleNamespace(Serial=FakeSerial, SerialException=OSError)
        config = HIDReaderConfig.objects.create(pk=1, port="COM9")
        with mock.patch.dict(sys.modules, {"serial": fake_serial}), self.assertRaises(StopListening):
            listen_hid_reader(config)
        self.assertEqual(AttendanceLog.objects.filter(employee=self.employee, capture_mode=AttendanceLog.HID).count(), 1)
        config.refresh_from_db()
        self.assertTrue(config.is_online)
