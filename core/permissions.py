"""Control de acceso por roles (RBAC) de Marcajix.

Cada usuario pertenece a un único grupo de Django que define su rol. Las vistas no
comprueban roles directamente: piden una *capacidad* y esta matriz decide qué roles
la tienen. Los superusuarios tienen todas las capacidades.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

SYSTEMS = "Sistemas"
SECURITY = "Seguridad"
HUMAN_RESOURCES = "Recursos Humanos"
ROLES = (SYSTEMS, SECURITY, HUMAN_RESOURCES)

# Sistemas: configuración, usuarios, auditoría y estructura.
MANAGE_USERS = "manage_users"
VIEW_AUDIT = "view_audit"
CONFIGURE_DEVICES = "configure_devices"
MANAGE_STRUCTURE = "manage_structure"
MANAGE_SYSTEM = "manage_system"
# Seguridad: puerta en tiempo real y registro manual o masivo de marcajes.
MONITOR_DOOR = "monitor_door"
REGISTER_ATTENDANCE = "register_attendance"
# Recursos Humanos: ficha del empleado y analítica de tiempos.
MANAGE_EMPLOYEES = "manage_employees"
VIEW_ANALYTICS = "view_analytics"
# Solo surte efecto si Sistemas activa las correcciones (SystemSettings.allow_attendance_corrections).
CORRECT_ATTENDANCE = "correct_attendance"
# Compartidas.
VIEW_EMPLOYEES = "view_employees"
VIEW_ATTENDANCE_HISTORY = "view_attendance_history"

ROLE_CAPABILITIES = {
    SYSTEMS: {MANAGE_USERS, VIEW_AUDIT, CONFIGURE_DEVICES, MANAGE_STRUCTURE, MANAGE_SYSTEM, CORRECT_ATTENDANCE, MONITOR_DOOR, REGISTER_ATTENDANCE, MANAGE_EMPLOYEES, VIEW_ANALYTICS, VIEW_EMPLOYEES, VIEW_ATTENDANCE_HISTORY},
    SECURITY: {MONITOR_DOOR, REGISTER_ATTENDANCE, VIEW_EMPLOYEES, VIEW_ATTENDANCE_HISTORY},
    HUMAN_RESOURCES: {MANAGE_EMPLOYEES, VIEW_ANALYTICS, CORRECT_ATTENDANCE, VIEW_EMPLOYEES, VIEW_ATTENDANCE_HISTORY},
}
ALL_CAPABILITIES = frozenset().union(*ROLE_CAPABILITIES.values())


def user_role(user):
    """Nombre del rol del usuario, o None si no tiene ninguno."""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return SYSTEMS
    if not hasattr(user, "_marcajix_role"):
        user._marcajix_role = next((name for name in user.groups.values_list("name", flat=True) if name in ROLE_CAPABILITIES), None)
    return user._marcajix_role


def user_capabilities(user):
    if not user.is_authenticated or not user.is_active:
        return frozenset()
    if user.is_superuser:
        return ALL_CAPABILITIES
    return frozenset(ROLE_CAPABILITIES.get(user_role(user), ()))


def has_capability(user, *capabilities):
    """True si el usuario tiene al menos una de las capacidades indicadas."""
    granted = user_capabilities(user)
    return any(capability in granted for capability in capabilities)


def capability_required(*capabilities):
    """Exige sesión iniciada y al menos una de las capacidades; si no, responde 403."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not has_capability(request.user, *capabilities):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def is_display_client(request):
    """Pantallas de garita autorizadas por IP (KIOSK_DISPLAY_IPS): ven el kiosco y las fotos sin sesión."""
    return request.META.get("REMOTE_ADDR", "") in settings.KIOSK_DISPLAY_IPS
