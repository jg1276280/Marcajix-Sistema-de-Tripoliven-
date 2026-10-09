"""Eventos en vivo de la garita.

El lector HID corre en su propio proceso (manage.py listen_hid) y solo escribe en la base de
datos. El kiosco exterior y el monitor de Seguridad consultan este feed cada pocos segundos
pidiendo lo ocurrido desde el último evento que ya mostraron. Así el sistema no depende de
que haya alguien con sesión iniciada ni de servicios extra (Redis, WebSockets).
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import AttendanceLog, HIDReaderConfig, SecurityEvent
from .permissions import MONITOR_DOOR, has_capability, is_display_client

FEED_BATCH_SIZE = 20


def can_view_garita(request):
    """La pantalla de la garita no inicia sesión: se autoriza por su IP. El resto necesita el rol."""
    return is_display_client(request) or has_capability(request.user, MONITOR_DOOR)


def _employee_payload(employee):
    if employee is None:
        return {"name": "", "department": "", "position": "", "photo": ""}
    return {
        "name": employee.full_name,
        "department": employee.department.name,
        "position": employee.position.name,
        "photo": reverse("protected_media", args=[employee.photo.name]) if employee.photo else "",
    }


def _event_payload(kind, occurred_at, employee=None, message="", card_code=""):
    local = timezone.localtime(occurred_at)
    payload = {"kind": kind, "at": local.isoformat(), "time": local.strftime("%H:%M:%S"), "date": local.strftime("%d/%m/%Y"), "message": message, "card_code": card_code, "celebration": None, **_employee_payload(employee)}
    if employee is not None and kind in (AttendanceLog.ENTRY, AttendanceLog.EXIT):
        # Cumpleaños o aniversario laboral: el kiosco lo celebra con una animación.
        payload["celebration"] = employee.celebration(local.date())
    return payload


def _door_logs():
    """Marcajes que se ven en la garita: las correcciones de RRHH no son movimientos en vivo."""
    return AttendanceLog.objects.exclude(capture_mode=AttendanceLog.CORRECTION).select_related("employee__position__department")


def recent_events(limit=10):
    """Últimos movimientos y alertas de la garita, del más reciente al más antiguo."""
    structure = ("employee__position__department",)
    events = [(log.marked_at, _event_payload(log.mark_type, log.marked_at, log.employee)) for log in _door_logs().order_by("-pk")[:limit]]
    for event in SecurityEvent.objects.select_related(*structure).order_by("-pk")[:limit]:
        if event.event_type == SecurityEvent.UNKNOWN_CARD:
            events.append((event.occurred_at, _event_payload("unknown_card", event.occurred_at, message="Tarjeta no reconocida", card_code=event.hid_card_code)))
        else:
            events.append((event.occurred_at, _event_payload("denied", event.occurred_at, event.employee, message=event.reason)))
    events.sort(key=lambda item: item[0], reverse=True)
    return [payload for _, payload in events[:limit]]


def reader_status():
    config = HIDReaderConfig.objects.filter(is_active=True).order_by("pk").first()
    if config is None:
        return {"online": False, "label": "Lector no configurado", "message": ""}
    online = config.is_online
    return {"online": online, "label": "Lector conectado" if online else "Lector sin conexión", "message": "" if online else config.status_message}


def _parse_cursor(value):
    return int(value) if value and value.isdigit() else None


def build_feed(log_cursor, event_cursor):
    """Eventos posteriores a los cursores; sin cursores, solo devuelve los cursores actuales."""
    if log_cursor is None or event_cursor is None:
        latest_log = AttendanceLog.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        latest_event = SecurityEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        return {"events": [], "cursor": {"log": latest_log, "event": latest_event}, "reader": reader_status()}

    structure = ("employee__position__department",)
    logs = list(_door_logs().filter(pk__gt=log_cursor).order_by("pk")[:FEED_BATCH_SIZE])
    security_events = list(SecurityEvent.objects.select_related(*structure).filter(pk__gt=event_cursor).order_by("pk")[:FEED_BATCH_SIZE])
    events = [_event_payload(log.mark_type, log.marked_at, log.employee) for log in logs]
    for event in security_events:
        if event.event_type == SecurityEvent.UNKNOWN_CARD:
            events.append(_event_payload("unknown_card", event.occurred_at, message="Tarjeta no reconocida", card_code=event.hid_card_code))
        else:
            events.append(_event_payload("denied", event.occurred_at, event.employee, message=event.reason))
    events.sort(key=lambda item: item["at"])
    return {
        "events": events,
        "cursor": {"log": logs[-1].pk if logs else log_cursor, "event": security_events[-1].pk if security_events else event_cursor},
        "reader": reader_status(),
    }


def live_feed(request):
    if not can_view_garita(request):
        raise PermissionDenied
    return JsonResponse(build_feed(_parse_cursor(request.GET.get("log")), _parse_cursor(request.GET.get("event"))))


def kiosk_display(request):
    """Pantalla exterior de la garita: muestra cada lectura sin necesidad de iniciar sesión."""
    if not can_view_garita(request):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        raise PermissionDenied
    return render(request, "dashboard/kiosk/live.html", {"feed_url": reverse("live_feed"), "time_zone": settings.TIME_ZONE})

