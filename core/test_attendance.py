from datetime import date, datetime, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from employees.models import Department, Employee, Management, Position

from .attendance import ENTRY_WITHOUT_EXIT, EXIT_WITHOUT_ENTRY, SESSION_TOO_LONG, daily_summaries, employee_totals, people_inside, summarize_marks
from .models import AttendanceLog
from .test_utils import create_test_image

ENTRY, EXIT = AttendanceLog.ENTRY, AttendanceLog.EXIT
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


def at(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 9, day, hour, minute))


@override_settings(ATTENDANCE_WORKDAY_HOURS=8, ATTENDANCE_MAX_SESSION_HOURS=16)
class SessionRulesTests(TestCase):
    """Reglas puras sobre la secuencia de movimientos, sin turnos ni horarios."""

    NOW = at(30, 12)

    def summarize(self, *marks):
        return summarize_marks(list(marks), now=self.NOW)

    def test_single_session_counts_hours_and_overtime(self):
        day = self.summarize((at(1, 8), ENTRY), (at(1, 17), EXIT))[date(2026, 9, 1)]
        self.assertEqual(day.worked_hours, 9.0)
        self.assertEqual(day.overtime_hours, 1.0)
        self.assertEqual((day.first_entry, day.last_exit), (at(1, 8), at(1, 17)))

    def test_lunch_break_is_not_counted(self):
        day = self.summarize((at(1, 8), ENTRY), (at(1, 12), EXIT), (at(1, 13), ENTRY), (at(1, 17), EXIT))[date(2026, 9, 1)]
        self.assertEqual(day.worked_hours, 8.0)
        self.assertEqual(day.sessions, 2)
        self.assertEqual(day.overtime_hours, 0)

    def test_night_shift_belongs_to_the_day_it_started(self):
        days = self.summarize((at(1, 22), ENTRY), (at(2, 6), EXIT))
        self.assertEqual(days[date(2026, 9, 1)].worked_hours, 8.0)
        self.assertNotIn(date(2026, 9, 2), days)

    def test_repeated_entry_flags_the_first_one(self):
        day = self.summarize((at(1, 8), ENTRY), (at(1, 9), ENTRY), (at(1, 17), EXIT))[date(2026, 9, 1)]
        self.assertEqual(day.worked_hours, 8.0)
        self.assertEqual([incident.label for incident in day.incidents], [ENTRY_WITHOUT_EXIT])
        self.assertEqual(day.first_entry, at(1, 8))

    def test_exit_without_entry_is_an_incident(self):
        day = self.summarize((at(1, 17), EXIT),)[date(2026, 9, 1)]
        self.assertEqual(day.worked_hours, 0)
        self.assertEqual(day.incidents[0].label, EXIT_WITHOUT_ENTRY)

    def test_recent_open_entry_means_the_person_is_inside(self):
        day = self.summarize((at(30, 8), ENTRY),)[date(2026, 9, 30)]
        self.assertTrue(day.is_open)
        self.assertEqual(day.incidents, [])

    def test_forgotten_exit_becomes_an_incident(self):
        day = self.summarize((at(28, 8), ENTRY),)[date(2026, 9, 28)]
        self.assertFalse(day.is_open)
        self.assertEqual(day.incidents[0].label, ENTRY_WITHOUT_EXIT)

    def test_too_long_session_does_not_add_hours(self):
        day = self.summarize((at(1, 8), ENTRY), (at(2, 9), EXIT))[date(2026, 9, 1)]
        self.assertEqual(day.worked_hours, 0)
        self.assertEqual(day.incidents[0].label, SESSION_TOO_LONG)


@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES, ATTENDANCE_WORKDAY_HOURS=8, ATTENDANCE_MAX_SESSION_HOURS=16)
class DailySummariesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        position = Position.objects.create(name="Operador", department=Department.objects.create(name="Planta", management=Management.objects.create(name="Operaciones")))
        cls.ana = Employee.objects.create(full_name="Ana Pérez", identification="1000001", position=position, photo=create_test_image("ana.png"))
        cls.luis = Employee.objects.create(full_name="Luis Torres", identification="1000002", position=position, photo=create_test_image("luis.png"))

    def mark(self, employee, moment, mark_type):
        AttendanceLog.objects.create(employee=employee, marked_at=moment, mark_type=mark_type)

    def test_range_keeps_sessions_crossing_its_edges(self):
        self.mark(self.ana, at(9, 22), ENTRY)   # Día anterior al rango: su salida cae dentro.
        self.mark(self.ana, at(10, 6), EXIT)
        self.mark(self.ana, at(10, 22), ENTRY)  # Último día del rango: su salida cae fuera.
        self.mark(self.ana, at(11, 6), EXIT)
        summaries = daily_summaries(date(2026, 9, 10), date(2026, 9, 10), now=at(30, 12))
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].worked_hours, 8.0)
        self.assertEqual(summaries[0].incidents, [])  # La salida de las 6:00 cierra la sesión del día 9.

    def test_uses_a_single_query_for_all_employees(self):
        for employee in (self.ana, self.luis):
            self.mark(employee, at(10, 8), ENTRY)
            self.mark(employee, at(10, 18), EXIT)
        with self.assertNumQueries(1):
            summaries = daily_summaries(date(2026, 9, 1), date(2026, 9, 30), now=at(30, 12))
        totals = {item.employee.pk: item for item in employee_totals(summaries, [self.ana, self.luis])}
        self.assertEqual(totals[self.ana.pk].worked_hours, 10.0)
        self.assertEqual(totals[self.ana.pk].overtime_hours, 2.0)
        self.assertEqual(totals[self.ana.pk].average_arrival, "08:00")
        self.assertEqual(totals[self.luis.pk].days_worked, 1)

    def test_people_inside_lists_open_entries_and_flags_forgotten_exits(self):
        now = timezone.now()
        self.mark(self.ana, now - timedelta(hours=2), ENTRY)
        self.mark(self.luis, now - timedelta(hours=30), ENTRY)
        inside = {employee.pk: employee for employee in people_inside()}
        self.assertEqual(set(inside), {self.ana.pk, self.luis.pk})
        self.assertFalse(inside[self.ana.pk].stale)
        self.assertTrue(inside[self.luis.pk].stale)


@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES, HID_REPEAT_SECONDS=60)
class CardRepeatTests(TestCase):
    def test_second_swipe_right_after_marking_is_ignored(self):
        from .hid_listener import process_card

        position = Position.objects.create(name="Operador", department=Department.objects.create(name="Planta", management=Management.objects.create(name="Operaciones")))
        Employee.objects.create(full_name="Ana Pérez", identification="1000001", hid_card_code="CARD-1", position=position, photo=create_test_image("repeat.png"))
        self.assertIsNotNone(process_card("CARD-1", "HID"))
        self.assertIsNone(process_card("CARD-1", "HID"))
        self.assertEqual(AttendanceLog.objects.count(), 1)


@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES, ATTENDANCE_WORKDAY_HOURS=8, KIOSK_DISPLAY_IPS=set())
class ReportsAndDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from .permissions import HUMAN_RESOURCES, SECURITY, SYSTEMS
        from .test_utils import create_user_with_role

        position = Position.objects.create(name="Operador", department=Department.objects.create(name="Planta", management=Management.objects.create(name="Operaciones")))
        cls.ana = Employee.objects.create(full_name="Ana Pérez", identification="1000001", position=position, photo=create_test_image("report.png"))
        today = timezone.localdate()
        start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
        AttendanceLog.objects.create(employee=cls.ana, marked_at=start + timedelta(hours=7), mark_type=ENTRY)
        AttendanceLog.objects.create(employee=cls.ana, marked_at=start + timedelta(hours=17), mark_type=EXIT)
        cls.users = {role: create_user_with_role(f"report-{index}", role) for index, role in enumerate((SYSTEMS, SECURITY, HUMAN_RESOURCES))}
        cls.hr, cls.security = cls.users[HUMAN_RESOURCES], cls.users[SECURITY]

    def test_summary_report_totals_hours_and_overtime(self):
        self.client.force_login(self.hr)
        response = self.client.get("/dashboard/reportes/", {"period": "today"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["overview"]["worked_hours"], 10.0)
        self.assertEqual(response.context["overview"]["overtime_hours"], 2.0)
        self.assertContains(response, "Ana Pérez")

    def test_daily_report_and_csv_export(self):
        self.client.force_login(self.hr)
        daily = self.client.get("/dashboard/reportes/", {"period": "today", "view": "daily"})
        self.assertEqual(daily.context["page_obj"][0].worked_hours, 10.0)
        export = self.client.get("/dashboard/reportes/exportar/", {"period": "today"})
        self.assertEqual(export["Content-Type"], "text/csv; charset=utf-8")
        content = export.content.decode("utf-8-sig")
        self.assertIn("Horas trabajadas", content)
        self.assertIn("Ana Pérez;1000001;Operaciones;Planta;Operador;07:00;17:00;10,00;2,00", content)

    def test_security_cannot_open_reports(self):
        self.client.force_login(self.security)
        self.assertEqual(self.client.get("/dashboard/reportes/").status_code, 403)
        self.assertEqual(self.client.get("/dashboard/reportes/exportar/").status_code, 403)

    def test_dashboard_adapts_to_each_role(self):
        for role, user in self.users.items():
            with self.subTest(role=role):
                self.client.force_login(user)
                response = self.client.get("/dashboard/")
                self.assertEqual(response.status_code, 200)
        self.client.force_login(self.security)
        self.assertTrue(self.client.get("/dashboard/").context["door"])
        self.client.force_login(self.hr)
        response = self.client.get("/dashboard/")
        self.assertTrue(response.context["analytics"])
        self.assertNotIn("door", response.context)
