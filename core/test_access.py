import shutil
import tempfile

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import AnonymousUser, Group, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.urls import reverse

from employees.models import Department, Employee, Management, Position

from .live import GaritaLiveConsumer
from .permissions import HUMAN_RESOURCES, SECURITY, SYSTEMS
from .test_utils import create_test_image, create_user_with_role

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


@override_settings(MEDIA_ROOT="test-media", STORAGES=STORAGES)
class RoleAccessMatrixTests(TestCase):
    """Cada rol solo llega a sus módulos; el resto responde 403."""

    @classmethod
    def setUpTestData(cls):
        department = Department.objects.create(name="Sistemas", management=Management.objects.create(name="Tecnología"))
        cls.employee = Employee.objects.create(full_name="Ana Pérez", identification="31395897", position=Position.objects.create(name="Analista", department=department), photo=create_test_image("matrix.png"))
        cls.users = {role: create_user_with_role(f"user-{index}", role) for index, role in enumerate((SYSTEMS, SECURITY, HUMAN_RESOURCES))}

    def _status(self, role, url):
        self.client.force_login(self.users[role])
        return self.client.get(url).status_code

    def test_role_matrix(self):
        detail = reverse("employees:detail", args=[self.employee.pk])
        edit = reverse("employees:edit", args=[self.employee.pk])
        expected = {
            reverse("user_list"): {SYSTEMS: 200, SECURITY: 403, HUMAN_RESOURCES: 403},
            reverse("audit_log"): {SYSTEMS: 200, SECURITY: 403, HUMAN_RESOURCES: 403},
            reverse("device_config"): {SYSTEMS: 200, SECURITY: 403, HUMAN_RESOURCES: 403},
            reverse("employees:structure"): {SYSTEMS: 200, SECURITY: 403, HUMAN_RESOURCES: 403},
            reverse("attendance_monitor"): {SYSTEMS: 200, SECURITY: 200, HUMAN_RESOURCES: 403},
            reverse("kiosk_garita"): {SYSTEMS: 200, SECURITY: 200, HUMAN_RESOURCES: 403},
            reverse("employees:list"): {SYSTEMS: 200, SECURITY: 200, HUMAN_RESOURCES: 200},
            reverse("attendance_history"): {SYSTEMS: 200, SECURITY: 200, HUMAN_RESOURCES: 200},
            detail: {SYSTEMS: 200, SECURITY: 403, HUMAN_RESOURCES: 200},
            edit: {SYSTEMS: 200, SECURITY: 403, HUMAN_RESOURCES: 200},
        }
        for url, by_role in expected.items():
            for role, status in by_role.items():
                with self.subTest(url=url, role=role):
                    self.assertEqual(self._status(role, url), status)

    def test_human_resources_cannot_register_attendance(self):
        self.client.force_login(self.users[HUMAN_RESOURCES])
        response = self.client.post(reverse("attendance_register"), {"rows": "[]"})
        self.assertEqual(response.status_code, 403)

    def test_anonymous_users_are_sent_to_login(self):
        for url in (reverse("dashboard"), reverse("employees:list"), reverse("attendance_monitor"), reverse("kiosk_garita"), reverse("attendance_employee_search")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(reverse("login")))

    def test_navigation_only_shows_allowed_modules(self):
        self.client.force_login(self.users[SECURITY])
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, reverse("user_list"))
        self.assertContains(response, reverse("attendance_monitor"))

    def test_django_admin_is_reserved_for_superusers(self):
        self.client.force_login(self.users[SYSTEMS])
        self.assertEqual(self.client.get("/admin/").status_code, 302)


@override_settings(STORAGES=STORAGES)
class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = create_user_with_role("sistemas", SYSTEMS)
        self.client.force_login(self.admin)

    def _payload(self, **overrides):
        payload = {"username": "nuevo", "email": "nuevo@tripoliven.com", "first_name": "Nuevo", "last_name": "Usuario", "is_active": "on", "role": SECURITY, "password1": "Garita-Segura-2026", "password2": "Garita-Segura-2026"}
        payload.update(overrides)
        return payload

    def test_create_user_assigns_exactly_one_role(self):
        response = self.client.post(reverse("user_create"), self._payload())
        self.assertRedirects(response, reverse("user_list"))
        user = User.objects.get(username="nuevo")
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [SECURITY])
        self.assertFalse(user.is_staff)

    def test_weak_passwords_are_rejected(self):
        response = self.client.post(reverse("user_create"), self._payload(password1="12345678", password2="12345678"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="nuevo").exists())

    def test_admin_cannot_lock_themselves_out(self):
        response = self.client.post(reverse("user_edit", args=[self.admin.pk]), self._payload(username="sistemas", role=SECURITY, is_active=""))
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.groups.filter(name=SYSTEMS).exists())

    def test_only_superusers_can_manage_superusers(self):
        root = User.objects.create_superuser(username="root", password="ValidPassword123!")
        self.assertEqual(self.client.get(reverse("user_edit", args=[root.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("user_delete", args=[root.pk])).status_code, 403)
        self.assertTrue(User.objects.filter(pk=root.pk).exists())

    def test_users_with_activity_are_not_deleted(self):
        target = create_user_with_role("con-historial", SECURITY)
        LogEntry.objects.log_action(user_id=target.pk, content_type_id=ContentType.objects.get_for_model(User).pk, object_id=target.pk, object_repr=target.username, action_flag=CHANGE, change_message="Actividad")
        self.client.post(reverse("user_delete", args=[target.pk]))
        self.assertTrue(User.objects.filter(pk=target.pk).exists())

    def test_users_without_activity_can_be_deleted(self):
        target = create_user_with_role("sin-historial", SECURITY)
        self.client.post(reverse("user_delete", args=[target.pk]))
        self.assertFalse(User.objects.filter(pk=target.pk).exists())

    def test_role_groups_are_created_by_migrations(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), {SYSTEMS, SECURITY, HUMAN_RESOURCES})


class ProtectedMediaTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root)
        with open(f"{self.media_root}/foto.png", "wb") as handle:
            handle.write(b"png")

    def test_employee_photos_require_login(self):
        with self.settings(MEDIA_ROOT=self.media_root):
            anonymous = self.client.get("/media/foto.png")
            self.client.force_login(create_user_with_role("rrhh", HUMAN_RESOURCES))
            authenticated = self.client.get("/media/foto.png")
        self.assertEqual(anonymous.status_code, 302)
        self.assertEqual(authenticated.status_code, 200)

    def test_media_view_blocks_path_traversal(self):
        with self.settings(MEDIA_ROOT=self.media_root):
            self.client.force_login(create_user_with_role("rrhh", HUMAN_RESOURCES))
            self.assertIn(self.client.get("/media/../manage.py").status_code, (400, 404))


class GaritaWebsocketTests(TestCase):
    def _connect(self, user):
        async def connect():
            communicator = WebsocketCommunicator(GaritaLiveConsumer.as_asgi(), "/ws/garita-live/")
            communicator.scope["user"] = user
            connected, _ = await communicator.connect()
            await communicator.disconnect()
            return connected

        return async_to_sync(connect)()

    def test_anonymous_clients_are_rejected(self):
        self.assertFalse(self._connect(AnonymousUser()))

    def test_authorized_clients_are_accepted(self):
        self.assertTrue(self._connect(User(username="root", is_superuser=True, is_active=True)))
