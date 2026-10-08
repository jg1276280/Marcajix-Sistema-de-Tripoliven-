from django.contrib.auth.models import User
from django.db import transaction

from .models import UserSecurity

MAX_LOGIN_ATTEMPTS = 3


def register_failed_login(user_id):
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user_id)
        security, _ = UserSecurity.objects.get_or_create(user=user)
        security = UserSecurity.objects.select_for_update().get(pk=security.pk)
        security.failed_login_attempts += 1
        locked = security.failed_login_attempts >= MAX_LOGIN_ATTEMPTS
        if locked:
            user.is_active = False
            user.save(update_fields=["is_active"])
        security.save(update_fields=["failed_login_attempts", "updated_at"])
        return security.failed_login_attempts, locked


def reset_failed_logins(user_id):
    UserSecurity.objects.filter(user_id=user_id, failed_login_attempts__gt=0).update(failed_login_attempts=0)