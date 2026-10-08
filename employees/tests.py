from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from datetime import date

from core.models import AttendanceLog, SecurityEvent
from core.permissions import SYSTEMS
from core.test_utils import create_test_image as image_upload, create_user_with_role
from .forms import EmployeeForm
from .models import Department, Employee, Management, Position


@override_settings(MEDIA_ROOT="test-media", STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class EmployeeTests(TestCase):
    def setUp(self):
        self.admin = create_user_with_role("employee-admin", SYSTEMS)
        self.management = Management.objects.create(name="Tecnología")
        self.department = Department.objects.create(name="Sistemas", management=self.management)
        self.position = Position.objects.create(name="Analista", department=self.department)
        self.payload = {"full_name": "Ana Pérez", "identification": "31395897", "position": self.position, "status": Employee.ACTIVE}
        self.form_payload = {"full_name": "Ana Pérez", "identification": "31395897", "position": self.position.pk, "department": self.department.pk, "management": self.management.pk, "hire_date": date.today().isoformat(), "status": Employee.ACTIVE}

    def test_employee_form_requires_valid_photo(self):
        form = EmployeeForm(data=self.form_payload)
        self.assertFalse(form.is_valid())
        self.assertIn("photo", form.errors)

    def test_employee_form_validates_name_and_identification_format(self):
        invalid_name = EmployeeForm(data={**self.form_payload, "full_name": "Ana 123"}, files={"photo": image_upload("invalid-name.png")})
        invalid_identification = EmployeeForm(data={**self.form_payload, "identification": "V-12345678"}, files={"photo": image_upload("invalid-id.png")})
        long_identification = EmployeeForm(data={**self.form_payload, "identification": "123456789"}, files={"photo": image_upload("long-id.png")})
        self.assertIn("full_name", invalid_name.errors)
        self.assertIn("identification", invalid_identification.errors)
        self.assertIn("identification", long_identification.errors)

    def test_employee_crud_and_duplicate_constraints(self):
        employee = Employee.objects.create(photo=image_upload(), **self.payload)
        self.assertEqual(Employee.objects.count(), 1)
        duplicate = EmployeeForm(data={**self.form_payload, "identification": "V-100"}, files={"photo": image_upload("duplicate.png")})
        self.assertFalse(duplicate.is_valid())
        self.assertIn("identification", duplicate.errors)
        employee.status = Employee.INACTIVE
        employee.save(update_fields=["status", "updated_at"])
        employee.refresh_from_db()
        self.assertEqual(employee.status, Employee.INACTIVE)

    def test_employee_form_persists_card_code(self):
        form = EmployeeForm(data={**self.form_payload, "hid_card_code": "CARD-001"}, files={"photo": image_upload("card-code.png")})
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertEqual(employee.hid_card_code, "CARD-001")

    def test_employee_form_persists_birthday(self):
        form = EmployeeForm(
            data={
                **self.form_payload,
                "birthday": "1990-05-13",
            },
            files={"photo": image_upload("birthday.png")},
        )
        self.assertTrue(form.is_valid(), form.errors)
        employee = form.save()
        self.assertEqual(str(employee.birthday), "1990-05-13")

    def test_employee_statuses_map_to_access_policies(self):
        employee = Employee.objects.create(photo=image_upload("status.png"), **self.payload)
        expected = {
            Employee.ACTIVE: ("allowed", "Acceso permitido."),
            Employee.VACATION: ("alert", "Acceso permitido con alerta: el empleado está de vacaciones."),
            Employee.INACTIVE: ("denied", "Acceso denegado: empleado inactivo."),
            Employee.RETIRED: ("denied", "Acceso denegado: empleado retirado."),
            Employee.SUSPENDED: ("denied", "Acceso denegado: empleado suspendido."),
        }
        for status, policy in expected.items():
            employee.status = status
            self.assertEqual((employee.access_level, employee.access_message), policy)

    def test_employee_can_be_deleted_without_important_history(self):
        employee = Employee.objects.create(photo=image_upload("deletable.png"), **self.payload)
        self.client.force_login(self.admin)

        response = self.client.post(reverse("employees:delete", args=[employee.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("employees:list"))
        self.assertFalse(Employee.objects.filter(pk=employee.pk).exists())

    def test_employee_delete_is_blocked_by_attendance_history(self):
        employee = Employee.objects.create(photo=image_upload("marked.png"), **self.payload)
        AttendanceLog.objects.create(employee=employee, marked_at="2026-09-21T10:00:00Z", mark_type=AttendanceLog.ENTRY)
        self.client.force_login(self.admin)

        response = self.client.post(reverse("employees:delete", args=[employee.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("employees:detail", args=[employee.pk]))
        self.assertTrue(Employee.objects.filter(pk=employee.pk).exists())

    def test_employee_delete_is_blocked_by_security_history(self):
        employee = Employee.objects.create(photo=image_upload("alerted.png"), **self.payload)
        SecurityEvent.objects.create(employee=employee, event_type=SecurityEvent.BLOCKED_EMPLOYEE, reason="Empleado inactivo", source="Registro manual")
        self.client.force_login(self.admin)

        response = self.client.post(reverse("employees:delete", args=[employee.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("employees:detail", args=[employee.pk]))
        self.assertTrue(Employee.objects.filter(pk=employee.pk).exists())

    def test_structure_can_rename_management_and_department(self):
        management = Management.objects.create(name="Operaciones")
        department = Department.objects.create(name="Compras", management=management)
        self.client.force_login(self.admin)

        management_response = self.client.post(reverse("employees:structure"), {"action": "management_update", "pk": management.pk, "name": "Operaciones y Compras"})
        department_response = self.client.post(reverse("employees:structure"), {"action": "department_update", "pk": department.pk, "name": "Adquisiciones"})

        self.assertEqual(management_response.status_code, 302)
        self.assertEqual(department_response.status_code, 302)
        self.assertTrue(Management.objects.filter(name="Operaciones y Compras").exists())
        self.assertTrue(Department.objects.filter(name="Adquisiciones").exists())

    def test_structure_edit_does_not_validate_creation_forms(self):
        management = Management.objects.create(name="Operaciones")
        self.client.force_login(self.admin)

        response = self.client.post(reverse("employees:structure"), {"action": "management_update", "pk": management.pk, "name": "Operaciones Norte"})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Management.objects.filter(name="Operaciones Norte").exists())

    def test_duplicate_structure_name_keeps_creation_forms_clean(self):
        first = Management.objects.create(name="Operaciones")
        second = Management.objects.create(name="Finanzas")
        self.client.force_login(self.admin)

        response = self.client.post(reverse("employees:structure"), {"action": "management_update", "pk": second.pk, "name": first.name})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["structure_edit_form"].errors["name"])
        self.assertFalse(response.context["management_form"].errors)
        self.assertFalse(response.context["department_form"].errors)
        self.assertTrue(Management.objects.filter(pk=second.pk, name="Finanzas").exists())

    def test_structure_deletion_requires_no_linked_data(self):
        empty_management = Management.objects.create(name="Vacía")
        linked_management = Management.objects.create(name="Vinculada")
        linked_department = Department.objects.create(name="Personal", management=linked_management)
        linked_position = Position.objects.create(name="Asistente", department=linked_department)
        Employee.objects.create(photo=image_upload("linked-structure.png"), **{**self.payload, "position": linked_position})
        self.client.force_login(self.admin)

        empty_response = self.client.post(reverse("employees:structure"), {"action": "management_delete", "pk": empty_management.pk})
        blocked_management = self.client.post(reverse("employees:structure"), {"action": "management_delete", "pk": linked_management.pk})
        blocked_department = self.client.post(reverse("employees:structure"), {"action": "department_delete", "pk": linked_department.pk})

        self.assertEqual(empty_response.status_code, 302)
        self.assertFalse(Management.objects.filter(pk=empty_management.pk).exists())
        self.assertTrue(Management.objects.filter(pk=linked_management.pk).exists())
        self.assertTrue(Department.objects.filter(pk=linked_department.pk).exists())
        self.assertEqual(blocked_management.status_code, 302)
        self.assertEqual(blocked_department.status_code, 302)

    def test_employee_detail_reports_inside_after_latest_entry(self):
        from django.utils import timezone

        employee = Employee.objects.create(photo=image_upload("inside.png"), **self.payload)
        AttendanceLog.objects.create(employee=employee, marked_at=timezone.now(), mark_type=AttendanceLog.ENTRY)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("employees:detail", args=[employee.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["attendance_status"], "inside")
        self.assertEqual(response.context["latest_attendance"].mark_type, AttendanceLog.ENTRY)

    def test_employee_detail_reports_outside_after_latest_exit(self):
        from django.utils import timezone
        from datetime import timedelta

        employee = Employee.objects.create(photo=image_upload("outside.png"), **self.payload)
        now = timezone.now()
        AttendanceLog.objects.create(employee=employee, marked_at=now - timedelta(minutes=10), mark_type=AttendanceLog.ENTRY)
        AttendanceLog.objects.create(employee=employee, marked_at=now, mark_type=AttendanceLog.EXIT)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("employees:detail", args=[employee.pk]))

        self.assertEqual(response.context["attendance_status"], "outside")
        self.assertEqual(response.context["latest_attendance"].mark_type, AttendanceLog.EXIT)

    def test_employee_detail_calculates_average_entry_and_exit_times(self):
        from datetime import datetime
        from django.utils import timezone

        employee = Employee.objects.create(photo=image_upload("averages.png"), **self.payload)
        AttendanceLog.objects.create(employee=employee, marked_at=timezone.make_aware(datetime(2026, 9, 22, 8, 0)), mark_type=AttendanceLog.ENTRY)
        AttendanceLog.objects.create(employee=employee, marked_at=timezone.make_aware(datetime(2026, 9, 22, 9, 0)), mark_type=AttendanceLog.ENTRY)
        AttendanceLog.objects.create(employee=employee, marked_at=timezone.make_aware(datetime(2026, 9, 22, 17, 0)), mark_type=AttendanceLog.EXIT)
        AttendanceLog.objects.create(employee=employee, marked_at=timezone.make_aware(datetime(2026, 9, 22, 18, 0)), mark_type=AttendanceLog.EXIT)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("employees:detail", args=[employee.pk]))

        self.assertEqual(response.context["average_times"], {"entry": "08:00", "exit": "17:00"})

    def test_employee_detail_calculates_period_metrics(self):
        from datetime import datetime, timedelta
        from django.utils import timezone

        employee = Employee.objects.create(photo=image_upload("metrics.png"), **self.payload)
        today = timezone.localdate()
        entry = timezone.make_aware(datetime.combine(today, datetime.min.time()).replace(hour=8))
        exit_time = entry + timedelta(hours=8)
        AttendanceLog.objects.create(employee=employee, marked_at=entry, mark_type=AttendanceLog.ENTRY)
        AttendanceLog.objects.create(employee=employee, marked_at=exit_time, mark_type=AttendanceLog.EXIT)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("employees:detail", args=[employee.pk]), {"period": "week"})

        self.assertEqual(response.context["total_hours"], 8.0)
        self.assertEqual(response.context["session_quality"], 100)
        self.assertEqual(response.context["balance_hours"], 0.0)
        self.assertIn(8.0, [item["hours"] for item in response.context["chart_days"]])

    def test_employee_detail_does_not_overlap_repeated_entries(self):
        from datetime import datetime, timedelta
        from django.utils import timezone

        employee = Employee.objects.create(photo=image_upload("multiple-sessions.png"), **self.payload)
        start = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()))
        for minutes, mark_type in ((480, AttendanceLog.ENTRY), (510, AttendanceLog.ENTRY), (720, AttendanceLog.EXIT), (780, AttendanceLog.EXIT)):
            AttendanceLog.objects.create(employee=employee, marked_at=start + timedelta(minutes=minutes), mark_type=mark_type)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("employees:detail", args=[employee.pk]))

        self.assertEqual(response.context["total_hours"], 4.0)
        self.assertEqual(response.context["complete_sessions"], 1)
        self.assertEqual(len(response.context["incongruences"]), 2)

    def test_employee_detail_ignores_exit_without_entry_and_open_entry(self):
        from datetime import datetime, timedelta
        from django.utils import timezone

        employee = Employee.objects.create(photo=image_upload("incomplete-session.png"), **self.payload)
        start = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()))
        AttendanceLog.objects.create(employee=employee, marked_at=start + timedelta(hours=7), mark_type=AttendanceLog.EXIT)
        AttendanceLog.objects.create(employee=employee, marked_at=start + timedelta(hours=8), mark_type=AttendanceLog.ENTRY)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("employees:detail", args=[employee.pk]))

        self.assertEqual(response.context["total_hours"], 0.0)
        self.assertEqual(response.context["complete_sessions"], 0)
        self.assertTrue(response.context["open_session"])
        self.assertEqual(len(response.context["incongruences"]), 1)

@override_settings(MEDIA_ROOT="test-media", STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class PositionHierarchyTests(TestCase):
    def setUp(self):
        self.admin = create_user_with_role("structure-admin", SYSTEMS)
        self.management = Management.objects.create(name="Tecnología")
        self.department = Department.objects.create(name="Sistemas", management=self.management)
        self.other_department = Department.objects.create(name="Soporte", management=self.management)
        self.position = Position.objects.create(name="Analista", department=self.department)

    def test_employee_derives_department_and_management_from_position(self):
        employee = Employee.objects.create(full_name="Ana Pérez", identification="31395897", position=self.position, photo=image_upload("derived.png"))
        self.assertEqual(employee.department, self.department)
        self.assertEqual(employee.management, self.management)

    def test_employee_form_rejects_position_outside_selected_department(self):
        form = EmployeeForm(data={"full_name": "Ana Pérez", "identification": "31395897", "position": self.position.pk, "department": self.other_department.pk, "hire_date": date.today().isoformat(), "status": Employee.ACTIVE}, files={"photo": image_upload("mismatch.png")})
        self.assertFalse(form.is_valid())
        self.assertIn("position", form.errors)

    def test_employee_form_rejects_position_outside_selected_management(self):
        other_management = Management.objects.create(name="Finanzas")
        form = EmployeeForm(data={"full_name": "Ana Pérez", "identification": "31395897", "position": self.position.pk, "management": other_management.pk, "hire_date": date.today().isoformat(), "status": Employee.ACTIVE}, files={"photo": image_upload("mismatch-management.png")})
        self.assertFalse(form.is_valid())
        self.assertIn("position", form.errors)

    def test_structure_creates_position_and_blocks_deleting_linked_levels(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("employees:structure"), {"action": "position_create", "position-department": self.other_department.pk, "position-name": "Técnico"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Position.objects.filter(name="Técnico", department=self.other_department).exists())

        Employee.objects.create(full_name="Ana Pérez", identification="31395897", position=self.position, photo=image_upload("linked.png"))
        self.client.post(reverse("employees:structure"), {"action": "position_delete", "pk": self.position.pk})
        self.client.post(reverse("employees:structure"), {"action": "department_delete", "pk": self.department.pk})
        self.assertTrue(Position.objects.filter(pk=self.position.pk).exists())
        self.assertTrue(Department.objects.filter(pk=self.department.pk).exists())

    def test_employee_list_searches_by_position(self):
        Employee.objects.create(full_name="Ana Pérez", identification="31395897", position=self.position, photo=image_upload("search.png"))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("employees:list"), {"q": "Analista"})
        self.assertEqual(len(response.context["employees"]), 1)
