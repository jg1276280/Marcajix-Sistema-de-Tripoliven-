"""Reglas de alertas. Se evalúan cada minuto en segundo plano (core/tasks.py).

Cada alerta tiene una `key` que identifica la situación concreta: mientras la alerta siga
abierta no se vuelve a crear, y las que dependen de un estado (lector desconectado, persona
dentro demasiado tiempo, respaldo fallido) se cierran solas cuando la situación se normaliza.

Para quién es cada alerta:
- Garita (Seguridad y Sistemas): accesos denegados, tarjetas desconocidas repetidas,
  permanencia excesiva y lector desconectado.
- Sistema (solo Sistemas): respaldos fallidos o atrasados.
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from .attendance import people_inside
from .models import Alert, HIDReaderConfig, SecurityEvent, SystemSettings

UNKNOWN_CARD_WINDOW = timedelta(minutes=10)
UNKNOWN_CARD_ATTEMPTS = 3
READER_OFFLINE_GRACE = timedelta(minutes=2)
BACKUP_STALE_AFTER = timedelta(hours=48)


def raise_alert(key, kind, audience, title, message="", severity=Alert.WARNING, employee=None):
    """Crea la alerta si no hay otra abierta con la misma clave. Devuelve la alerta (nueva o existente)."""
    alert = Alert.objects.filter(key=key, resolved_at__isnull=True).first()
    if alert is None:
        alert = Alert.objects.create(key=key, kind=kind, audience=audience, title=title[:160], message=message[:500], severity=severity, employee=employee)
    return alert


def auto_resolve(keep_keys, prefix):
    """Cierra las alertas abiertas de un tipo cuya situación ya no se cumple."""
    stale = Alert.objects.filter(resolved_at__isnull=True, key__startswith=prefix).exclude(key__in=keep_keys)
    stale.update(resolved_at=timezone.now(), auto_resolved=True)


def _denied_access(since):
    for event in SecurityEvent.objects.select_related("employee").filter(event_type=SecurityEvent.BLOCKED_EMPLOYEE, occurred_at__gte=since):
        name = event.employee.full_name if event.employee else "Empleado eliminado"
        raise_alert(f"denied:{event.pk}", "denied", Alert.DOOR, f"Acceso denegado: {name}", f"{event.reason} ({timezone.localtime(event.occurred_at):%d/%m %H:%M})", Alert.CRITICAL, event.employee)


def _unknown_cards(now):
    window_start = now - UNKNOWN_CARD_WINDOW
    repeated = (
        SecurityEvent.objects.filter(event_type=SecurityEvent.UNKNOWN_CARD, occurred_at__gte=window_start)
        .values("hid_card_code").annotate(attempts=Count("pk")).filter(attempts__gte=UNKNOWN_CARD_ATTEMPTS)
    )
    for row in repeated:
        # Una alerta por tarjeta y día: si insiste más tarde, sigue siendo la misma alerta abierta.
        raise_alert(f"unknown:{row['hid_card_code']}:{timezone.localdate(now):%Y%m%d}", "unknown_card", Alert.DOOR, "Tarjeta desconocida insistente", f"La tarjeta {row['hid_card_code']} se intentó {row['attempts']} veces en {int(UNKNOWN_CARD_WINDOW.total_seconds() // 60)} minutos.", Alert.WARNING)


def _long_stays(now):
    keys = []
    hours = settings.ATTENDANCE_MAX_SESSION_HOURS
    for person in people_inside(now=now):
        if person.stale:
            key = f"long-stay:{person.pk}:{person.inside_since:%Y%m%d%H%M%S}"
            keys.append(key)
            raise_alert(key, "long_stay", Alert.DOOR, f"{person.full_name} lleva más de {hours:g} h dentro", f"Entró el {timezone.localtime(person.inside_since):%d/%m a las %H:%M} y no tiene salida registrada. Puede ser un olvido de marcaje.", Alert.WARNING, person)
    auto_resolve(keys, "long-stay:")


def _reader(now):
    keys = []
    config = HIDReaderConfig.objects.filter(is_active=True).order_by("pk").first()
    if config is not None and config.last_seen_at is not None:
        silent_for = now - config.last_seen_at
        offline = config.status == HIDReaderConfig.STATUS_ERROR or silent_for > READER_OFFLINE_GRACE
        if offline:
            keys.append("reader-offline")
            detail = config.status_message if config.status == HIDReaderConfig.STATUS_ERROR else f"Sin señal desde {timezone.localtime(config.last_seen_at):%d/%m %H:%M}."
            raise_alert("reader-offline", "reader_offline", Alert.DOOR, "El lector de la garita no responde", f"{detail} Las tarjetas no se están registrando: use el registro manual mientras tanto.", Alert.CRITICAL)
    auto_resolve(keys, "reader-offline")


def _backups(now):
    keys = []
    config = SystemSettings.load()
    if config.backup_enabled:
        if config.last_backup_status == "error":
            keys.append("backup-failed")
            raise_alert("backup-failed", "backup_failed", Alert.SYSTEM, "Falló el respaldo de la base de datos", config.last_backup_message, Alert.CRITICAL)
        elif config.last_backup_ok_at and now - config.last_backup_ok_at > BACKUP_STALE_AFTER:
            keys.append("backup-stale")
            raise_alert("backup-stale", "backup_stale", Alert.SYSTEM, "No hay respaldos recientes", f"El último respaldo correcto es del {timezone.localtime(config.last_backup_ok_at):%d/%m/%Y %H:%M}.", Alert.WARNING)
    auto_resolve([key for key in keys if key == "backup-failed"], "backup-failed")
    auto_resolve([key for key in keys if key == "backup-stale"], "backup-stale")


def evaluate_alerts(now=None, since=None):
    """Aplica todas las reglas. `since` limita los eventos puntuales revisados (por defecto, 1 hora)."""
    now = now or timezone.now()
    _denied_access(since or now - timedelta(hours=1))
    _unknown_cards(now)
    _long_stays(now)
    _reader(now)
    _backups(now)


def visible_alerts(user):
    """Alertas que puede ver el usuario según su rol (None si no ve ninguna)."""
    from .permissions import MANAGE_SYSTEM, MONITOR_DOOR, has_capability

    audiences = []
    if has_capability(user, MONITOR_DOOR):
        audiences.append(Alert.DOOR)
    if has_capability(user, MANAGE_SYSTEM):
        audiences.append(Alert.SYSTEM)
    if not audiences:
        return None
    return Alert.objects.filter(audience__in=audiences)
