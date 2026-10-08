from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import UserSecurity

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)


def locked_until(user):
    """Fecha hasta la que la cuenta está bloqueada por intentos fallidos, o None."""
    security = UserSecurity.objects.filter(user=user).only("locked_until").first()
    if security and security.locked_until and security.locked_until > timezone.now():
        return security.locked_until
    return None


def register_failed_login(user):
    """Cuenta un intento fallido; al llegar al máximo bloquea la cuenta temporalmente.

    El bloqueo es temporal y no desactiva al usuario: así nadie puede dejar fuera
    a un administrador solo con conocer su nombre de usuario.
    """
    with transaction.atomic():
        security, _ = UserSecurity.objects.select_for_update().get_or_create(user=user)
        security.failed_login_attempts += 1
        if security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS:
            security.failed_login_attempts = 0
            security.locked_until = timezone.now() + LOCKOUT_DURATION
        security.save(update_fields=["failed_login_attempts", "locked_until", "updated_at"])
        return security.locked_until if security.locked_until and security.locked_until > timezone.now() else None


def reset_failed_logins(user):
    UserSecurity.objects.filter(user=user).update(failed_login_attempts=0, locked_until=None)
