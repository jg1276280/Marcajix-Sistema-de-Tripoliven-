from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from django.db import transaction
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType

from employees.models import Employee

from .models import AttendanceLog, SecurityEvent

MANUAL_ATTENDANCE_WINDOW = timedelta(hours=72)
MINIMUM_MARK_GAP_SECONDS = 90


class AttendanceRegistrationError(Exception):
    """Raised when an attendance mark cannot be registered."""

    def __init__(self, message, *, employee=None, code="invalid", warning=False):
        super().__init__(message)
        self.employee = employee
        self.code = code
        self.warning = warning


def latest_mark(employee, until=None):
    logs = employee.attendance_logs.all()
    if until is not None:
        logs = logs.filter(marked_at__lte=until)
    return logs.order_by("-marked_at", "-pk").first()


def next_mark_type(employee):
    """El siguiente movimiento alterna con el último: tras una entrada toca salida."""
    latest = latest_mark(employee)
    return AttendanceLog.EXIT if latest and latest.mark_type == AttendanceLog.ENTRY else AttendanceLog.ENTRY


def _validate_mark_transition(employee, latest_log, marked_at, mark_type):
    if latest_log is None:
        if mark_type == AttendanceLog.EXIT:
            raise AttendanceRegistrationError("No se puede registrar una Salida sin una Entrada previa.", employee=employee, code="exit_without_entry")
        return
    if latest_log.mark_type != mark_type:
        return
    label = latest_log.get_mark_type_display()
    if abs((marked_at - latest_log.marked_at).total_seconds()) < MINIMUM_MARK_GAP_SECONDS:
        raise AttendanceRegistrationError(f"No se puede registrar otra {label} dentro de los 90 segundos de la última {label}.", employee=employee, code="duplicate_mark")
    if mark_type == AttendanceLog.ENTRY:
        raise AttendanceRegistrationError("No se puede registrar otra Entrada sin una Salida previa.", employee=employee, code="entry_without_exit")
    raise AttendanceRegistrationError("No se puede registrar otra Salida sin una Entrada previa.", employee=employee, code="exit_without_entry")


def _record_blocked_attempt(employee, mark_type, source, registered_by):
    reason = employee.access_message
    with transaction.atomic():
        event = SecurityEvent.objects.create(
            event_type=SecurityEvent.BLOCKED_EMPLOYEE,
            employee=employee,
            employee_status=employee.status,
            hid_card_code=employee.hid_card_code or "",
            mark_type=mark_type,
            reason=reason,
            source=source[:120],
            attempted_by=registered_by,
        )
        if registered_by:
            LogEntry.objects.log_action(
                user_id=registered_by.pk,
                content_type_id=ContentType.objects.get_for_model(SecurityEvent).pk,
                object_id=event.pk,
                object_repr=employee.full_name,
                action_flag=CHANGE,
                change_message=(
                    f"Intento de marcaje manual denegado para {employee.full_name}: "
                    f"estatus {employee.get_status_display()} ({employee.status}). Motivo: {reason}"
                ),
            )
    raise AttendanceRegistrationError(reason, employee=employee, code="blocked")


def record_unknown_card(card_code, source):
    return SecurityEvent.objects.create(event_type=SecurityEvent.UNKNOWN_CARD, hid_card_code=card_code[:80], reason="Tarjeta no reconocida.", source=source[:120])


def register_attendance(employee_id, marked_at, mark_type, source="Registro manual", registered_by=None, capture_mode=AttendanceLog.MANUAL):
    """Único punto de entrada para registrar un movimiento, sea del lector HID o manual."""
    if mark_type not in (AttendanceLog.ENTRY, AttendanceLog.EXIT):
        raise AttendanceRegistrationError("Cada fila debe indicar Entrada o Salida.", code="invalid_mark_type")
    with transaction.atomic():
        # Bloquea la fila del empleado para que dos lecturas simultáneas no rompan la secuencia.
        employee = Employee.objects.select_for_update().filter(pk=employee_id).first()
        if employee is None:
            raise AttendanceRegistrationError("El empleado no existe.", code="not_found")
        latest_log = latest_mark(employee, until=marked_at)
        _validate_mark_transition(employee, latest_log, marked_at, mark_type)
        closes_open_entry = mark_type == AttendanceLog.EXIT and latest_log is not None and latest_log.mark_type == AttendanceLog.ENTRY
        if employee.status in Employee.ACCESS_ALLOWED_STATUSES or closes_open_entry:
            now = timezone.now()
            if marked_at < now - MANUAL_ATTENDANCE_WINDOW:
                raise AttendanceRegistrationError("La fecha no puede ser anterior a 72 horas.", employee=employee)
            if marked_at > now:
                raise AttendanceRegistrationError("La fecha no puede ser futura.", employee=employee)
            return AttendanceLog.objects.create(employee=employee, marked_at=marked_at, mark_type=mark_type, source=source[:120], capture_mode=capture_mode, registered_by=registered_by)
    # Fuera de la transacción del marcaje: el intento bloqueado debe quedar guardado aunque se lance el error.
    _record_blocked_attempt(employee, mark_type, source, registered_by)


def broadcast_attendance_event(log):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    payload = {
        "type": "attendance.processed",
        "event": "attendance_processed",
        "data": {
            "id": log.pk,
            "employee_id": log.employee_id,
            "employee": log.employee.full_name,
            "department": log.employee.department.name,
            "position": log.employee.position.name,
            "photo": log.employee.photo.url if log.employee.photo else "",
            "mark_type": log.mark_type,
            "marked_at": log.marked_at.isoformat(),
            "status": log.employee.status,
        },
    }
    async_to_sync(channel_layer.group_send)("garita-live", {"type": "broadcast.event", "payload": payload})


def broadcast_kiosk_event(event, data=None, message=""):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    payload = {"type": event, "event": event, "message": message, "data": data or {}}
    async_to_sync(channel_layer.group_send)("garita-live", {"type": "broadcast.event", "payload": payload})
