import os
import shutil
import tempfile
import time as time_module
from datetime import date, datetime, time, timedelta
from unittest import mock

from django.contrib.admin.models import LogEntry
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from employees.models import Department, Employee, Management, Position

from . import backups
from .alerts import evaluate_alerts
from .attendance import daily_summaries, presence_board
from .live import build_feed
from .models import Alert, AttendanceLog, HIDReaderConfig, SecurityEvent, SystemSettings
from .permissions import HUMAN_RESOURCES, SECURITY, SYSTEMS
from .services import record_unknown_card
from .test_utils import create_test_image, create_user_with_role

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
ENTRY, EXIT = AttendanceLog.ENTRY, AttendanceLog.EXIT


class FeatureTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        position = Position.objects.create(name="Operador", department=Department.objects.create(name="Planta", management=Management.objects.create(name="Operaciones")))
        cls.ana = Employee.objects.create(full_name="Ana Pérez", identification="2000001", hid_card_code="CARD-ANA", position=position, photo=create_test_image("f-ana.png"), birthday=date(1990, 3, 15), hire_date=date(2020, 6, 1))
        cls.luis = Employee.objects.create(full_name="Luis Torres", identification="2000002", position=position, photo=create_test_image("f-luis.png"))
        cls.sistemas = create_user_with_role("f-sistemas", SYSTEMS)
        cls.seguridad = create_user_with_role("f-seguridad", SECURITY)
        cls.rrhh = create_user_with_role("f-rrhh", HUMAN_RESOURCES)

    def mark(self, employee, moment, mark_type, **extra):
        return AttendanceLog.objects.create(employee=employee, marked_at=moment, mark_type=mark_type, **extra)


# ---------------------------------------------------------------------------
# Respaldos
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES)
class BackupTests(FeatureTestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        os.makedirs(os.path.join(self.folder, "Marcajix"))
        self.env = mock.patch.dict(os.environ, {"DB_NAME": "marcajix"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def fake_backup(self, destination, filename):
        path = os.path.join(destination, filename)
        with open(path, "wb") as handle:
            handle.write(b"BAK")
        return path

    def test_check_folder(self):
        self.assertTrue(backups.check_folder(self.folder)[0])
        self.assertFalse(backups.check_folder(os.path.join(self.folder, "no-existe"))[0])
        self.assertFalse(backups.check_folder("")[0])

    def test_folder_browser_lists_subfolders_and_parent(self):
        listing = backups.list_folders(self.folder)
        self.assertEqual([item["name"] for item in listing["folders"]], ["Marcajix"])
        self.assertEqual(listing["parent"], os.path.dirname(os.path.normpath(self.folder)))
        self.assertTrue(backups.list_folders("")["folders"])

    def test_successful_backup_records_status_and_prunes_old_files(self):
        config = SystemSettings.load()
        config.backup_path = self.folder
        config.backup_retention_days = 7
        config.save()
        old = os.path.join(self.folder, "marcajix-marcajix-20200101-000000.bak")
        unrelated = os.path.join(self.folder, "otro-archivo.bak")
        for path in (old, unrelated):
            open(path, "wb").close()
            past = time_module.time() - 30 * 86400
            os.utime(path, (past, past))
        with mock.patch.object(backups, "_backup_database", side_effect=self.fake_backup):
            ok, message = backups.run_backup(config)
        self.assertTrue(ok, message)
        config.refresh_from_db()
        self.assertEqual(config.last_backup_status, "ok")
        self.assertTrue(os.path.isfile(config.last_backup_file))
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(unrelated))  # Nunca se borran archivos que no son de Marcajix.
        self.assertEqual(len(backups.list_backups(config)), 1)

    def test_failed_backup_is_recorded_and_raises_an_alert(self):
        config = SystemSettings.load()
        config.backup_enabled = True
        config.backup_path = os.path.join(self.folder, "no-existe")
        config.save()
        ok, _ = backups.run_backup(config)
        self.assertFalse(ok)
        config.refresh_from_db()
        self.assertEqual(config.last_backup_status, "error")
        evaluate_alerts()
        self.assertTrue(Alert.objects.filter(key="backup-failed", audience=Alert.SYSTEM, resolved_at__isnull=True).exists())

    def test_backup_is_due_once_a_day_after_the_scheduled_time(self):
        config = SystemSettings(backup_enabled=True, backup_path=self.folder, backup_time=time(23, 0))
        tz = timezone.get_current_timezone()
        before = timezone.make_aware(datetime(2026, 10, 9, 22, 0), tz)
        after = timezone.make_aware(datetime(2026, 10, 9, 23, 30), tz)
        self.assertFalse(backups.backup_is_due(config, before))
        self.assertTrue(backups.backup_is_due(config, after))
        config.last_backup_attempt_at = after
        self.assertFalse(backups.backup_is_due(config, after + timedelta(minutes=10)))
        config.backup_enabled = False
        self.assertFalse(backups.backup_is_due(config, after + timedelta(days=1)))

    def test_system_page_is_only_for_systems_role(self):
        for user, status in ((self.sistemas, 200), (self.rrhh, 403), (self.seguridad, 403)):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("system_settings")).status_code, status)

    def test_settings_form_and_folder_endpoints(self):
        self.client.force_login(self.sistemas)
        response = self.client.post(reverse("system_settings"), {"backup_enabled": "on", "backup_path": self.folder, "backup_time": "22:30", "backup_retention_days": "15", "allow_attendance_corrections": "on"})
        self.assertRedirects(response, reverse("system_settings"))
        config = SystemSettings.load()
        self.assertEqual((config.backup_path, config.backup_time, config.backup_retention_days), (self.folder, time(22, 30), 15))
        self.assertTrue(config.allow_attendance_corrections)
        self.assertTrue(LogEntry.objects.filter(change_message__startswith="Configuración actualizada").exists())
        browse = self.client.get(reverse("browse_folders"), {"path": self.folder}).json()
        self.assertEqual(browse["folders"][0]["name"], "Marcajix")
        self.assertEqual(self.client.post(reverse("test_backup_folder"), {"path": self.folder}).status_code, 200)
        self.assertEqual(self.client.post(reverse("test_backup_folder"), {"path": "/no/existe"}).status_code, 400)

    def test_enabling_backups_requires_a_folder(self):
        self.client.force_login(self.sistemas)
        response = self.client.post(reverse("system_settings"), {"backup_enabled": "on", "backup_path": "", "backup_time": "23:00", "backup_retention_days": "30"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("backup_path", response.context["form"].errors)


# ---------------------------------------------------------------------------
# Correcciones de marcajes
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES, KIOSK_DISPLAY_IPS=set())
class CorrectionTests(FeatureTestCase):
    def setUp(self):
        self.entry = self.mark(self.ana, (timezone.now() - timedelta(hours=30)).replace(second=0, microsecond=0), ENTRY)
        self.add_url = reverse("employees:correction_add", args=[self.ana.pk])

    def enable(self, value=True):
        config = SystemSettings.load()
        config.allow_attendance_corrections = value
        config.save()

    def payload(self, **overrides):
        moment = timezone.localtime(self.entry.marked_at + timedelta(hours=9))
        data = {"mark_type": EXIT, "marked_at": moment.strftime("%Y-%m-%dT%H:%M"), "reason": "Olvidó marcar la salida"}
        data.update(overrides)
        return data

    def test_corrections_are_blocked_until_systems_enables_them(self):
        self.client.force_login(self.rrhh)
        self.assertEqual(self.client.post(self.add_url, self.payload()).status_code, 403)
        self.enable()
        self.client.force_login(self.seguridad)
        self.assertEqual(self.client.post(self.add_url, self.payload()).status_code, 403)

    def test_hr_adds_a_forgotten_exit_and_it_counts(self):
        self.enable()
        self.client.force_login(self.rrhh)
        self.client.post(self.add_url, self.payload())
        correction = AttendanceLog.objects.get(capture_mode=AttendanceLog.CORRECTION)
        self.assertEqual((correction.mark_type, correction.registered_by, correction.correction_reason), (EXIT, self.rrhh, "Olvidó marcar la salida"))
        self.assertTrue(LogEntry.objects.filter(change_message__contains="Corrección: se añadió una Salida").exists())
        day = timezone.localtime(self.entry.marked_at).date()
        summary = daily_summaries(day, day, employee_ids=[self.ana.pk])[0]
        self.assertEqual(summary.worked_hours, 9.0)
        self.assertEqual(summary.incidents, [])

    def test_corrections_need_a_reason_and_a_valid_sequence(self):
        self.enable()
        self.client.force_login(self.rrhh)
        self.client.post(self.add_url, self.payload(reason=""))
        self.client.post(self.add_url, self.payload(mark_type=ENTRY))  # Dos entradas seguidas.
        self.assertFalse(AttendanceLog.objects.filter(capture_mode=AttendanceLog.CORRECTION).exists())

    def test_voided_marks_stop_counting_but_stay_in_history(self):
        self.enable()
        self.client.force_login(self.rrhh)
        url = reverse("employees:correction_void", args=[self.ana.pk, self.entry.pk])
        self.client.post(url, {"reason": "Marcaje duplicado"})
        self.assertFalse(AttendanceLog.objects.filter(pk=self.entry.pk).exists())
        voided = AttendanceLog.all_objects.get(pk=self.entry.pk)
        self.assertEqual((voided.voided_by, voided.void_reason), (self.rrhh, "Marcaje duplicado"))
        self.client.force_login(self.seguridad)
        history = self.client.get(reverse("attendance_history"), {"from": "2000-01-01"})
        self.assertContains(history, "Anulado")

    def test_detail_shows_correction_tools_only_when_enabled(self):
        self.client.force_login(self.rrhh)
        detail = reverse("employees:detail", args=[self.ana.pk])
        self.assertFalse(self.client.get(detail).context["can_correct"])
        self.enable()
        self.assertTrue(self.client.get(detail).context["can_correct"])

    def test_kiosk_feed_ignores_corrections(self):
        cursor = build_feed(None, None)["cursor"]
        self.mark(self.ana, timezone.now() - timedelta(hours=20), EXIT, capture_mode=AttendanceLog.CORRECTION)
        self.assertEqual(build_feed(cursor["log"], cursor["event"])["events"], [])


# ---------------------------------------------------------------------------
# Presencia
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES, KIOSK_DISPLAY_IPS=set())
class PresenceTests(FeatureTestCase):
    def test_board_splits_inside_left_and_absent(self):
        now = timezone.now()
        Employee.objects.filter(pk=self.luis.pk).update(status=Employee.ACTIVE)
        self.mark(self.ana, now - timedelta(minutes=30), ENTRY)
        board = presence_board(now)
        self.assertEqual([person.pk for person in board["inside"]], [self.ana.pk])
        self.assertEqual([person.pk for person in board["absent"]], [self.luis.pk])
        self.mark(self.ana, now - timedelta(minutes=5), EXIT)
        board = presence_board(now)
        self.assertEqual([person.pk for person in board["left"]], [self.ana.pk])

    def test_page_is_for_door_roles_and_supports_partial_refresh(self):
        self.client.force_login(self.seguridad)
        self.assertEqual(self.client.get(reverse("presence")).status_code, 200)
        partial = self.client.get(reverse("presence"), {"partial": "1"})
        self.assertNotContains(partial, "<html")
        self.client.force_login(self.rrhh)
        self.assertEqual(self.client.get(reverse("presence")).status_code, 403)


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES, KIOSK_DISPLAY_IPS=set(), ATTENDANCE_MAX_SESSION_HOURS=16)
class AlertTests(FeatureTestCase):
    def test_denied_access_creates_one_critical_alert(self):
        event = SecurityEvent.objects.create(event_type=SecurityEvent.BLOCKED_EMPLOYEE, employee=self.ana, reason="Acceso denegado: empleado suspendido.", source="HID")
        evaluate_alerts()
        evaluate_alerts()
        alert = Alert.objects.get(key=f"denied:{event.pk}")
        self.assertEqual((alert.severity, alert.audience), (Alert.CRITICAL, Alert.DOOR))

    def test_repeated_unknown_card_raises_a_single_alert(self):
        for _ in range(2):
            record_unknown_card("X-1", "HID")
        evaluate_alerts()
        self.assertFalse(Alert.objects.filter(kind="unknown_card").exists())
        record_unknown_card("X-1", "HID")
        evaluate_alerts()
        record_unknown_card("X-1", "HID")
        evaluate_alerts()
        self.assertEqual(Alert.objects.filter(kind="unknown_card").count(), 1)

    def test_long_stay_alert_resolves_itself_when_the_person_leaves(self):
        self.mark(self.ana, timezone.now() - timedelta(hours=20), ENTRY)
        evaluate_alerts()
        alert = Alert.objects.get(kind="long_stay")
        self.assertIsNone(alert.resolved_at)
        self.mark(self.ana, timezone.now(), EXIT)
        evaluate_alerts()
        alert.refresh_from_db()
        self.assertTrue(alert.auto_resolved)

    def test_reader_offline_alert_and_recovery(self):
        config = HIDReaderConfig.objects.create(pk=1, status=HIDReaderConfig.STATUS_CONNECTED, last_seen_at=timezone.now() - timedelta(minutes=10))
        evaluate_alerts()
        self.assertTrue(Alert.objects.filter(key="reader-offline", resolved_at__isnull=True).exists())
        HIDReaderConfig.objects.filter(pk=config.pk).update(last_seen_at=timezone.now())
        evaluate_alerts()
        self.assertFalse(Alert.objects.filter(key="reader-offline", resolved_at__isnull=True).exists())

    def test_visibility_summary_and_resolution(self):
        Alert.objects.create(key="door-1", kind="denied", audience=Alert.DOOR, title="Puerta")
        Alert.objects.create(key="system-1", kind="backup_failed", audience=Alert.SYSTEM, title="Sistema")
        self.client.force_login(self.seguridad)
        summary = self.client.get(reverse("alert_summary")).json()
        self.assertEqual([item["title"] for item in summary["latest"]], ["Puerta"])
        self.client.force_login(self.sistemas)
        self.assertEqual(self.client.get(reverse("alert_summary")).json()["count"], 2)
        self.client.force_login(self.rrhh)
        self.assertEqual(self.client.get(reverse("alert_list")).status_code, 403)
        self.client.force_login(self.seguridad)
        door = Alert.objects.get(key="door-1")
        self.client.post(reverse("alert_resolve", args=[door.pk]))
        door.refresh_from_db()
        self.assertEqual(door.resolved_by, self.seguridad)
        system = Alert.objects.get(key="system-1")
        self.assertEqual(self.client.post(reverse("alert_resolve", args=[system.pk])).status_code, 404)


# ---------------------------------------------------------------------------
# Celebraciones
# ---------------------------------------------------------------------------
@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES)
class CelebrationTests(FeatureTestCase):
    def test_birthday_anniversary_and_leap_day(self):
        self.assertEqual(self.ana.celebration(date(2026, 3, 15)), {"type": "birthday", "years": 36})
        self.assertEqual(self.ana.celebration(date(2026, 6, 1)), {"type": "anniversary", "years": 6})
        self.assertIsNone(self.ana.celebration(date(2020, 6, 1)))  # El día de ingreso no es aniversario.
        self.assertIsNone(self.ana.celebration(date(2026, 3, 16)))
        self.ana.birthday = date(2000, 2, 29)
        self.assertEqual(self.ana.celebration(date(2027, 2, 28))["type"], "birthday")
        self.assertIsNone(self.ana.celebration(date(2028, 2, 28)))

    def test_kiosk_feed_announces_the_celebration(self):
        today = timezone.localdate()
        Employee.objects.filter(pk=self.ana.pk).update(birthday=today.replace(year=1995))
        cursor = build_feed(None, None)["cursor"]
        self.mark(self.ana, timezone.now(), ENTRY, capture_mode=AttendanceLog.HID)
        event = build_feed(cursor["log"], cursor["event"])["events"][0]
        self.assertEqual(event["celebration"]["type"], "birthday")
