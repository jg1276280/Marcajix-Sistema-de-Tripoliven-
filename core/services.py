from datetime import timedelta
from functools import wraps

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
from django.db import transaction
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType

from employees.models import Employee

from .models import AttendanceAttempt, AttendanceLog

MANUAL_ATTENDANCE_WINDOW = timedelta(hours=72)
MINIMUM_MARK_GAP_SECONDS = 90


class AttendanceRegistrationError(Exception):
    """Raised when a manual attendance row is invalid."""

    def __init__(self, message, *, employee=None, code="invalid", warning=False):
        super().__init__(message)
        self.employee = employee
        self.code = code
        self.warning = warning


def _validate_mark_transition(employee, marked_at, mark_type):
    latest_log = employee.attendance_logs.filter(marked_at__lte=marked_at).order_by("-marked_at", "-pk").first()
    if mark_type == AttendanceLog.ENTRY and latest_log and latest_log.mark_type == AttendanceLog.ENTRY:
        delta_seconds = abs((marked_at - latest_log.marked_at).total_seconds())
        if delta_seconds < MINIMUM_MARK_GAP_SECONDS:
            raise AttendanceRegistrationError("No se puede registrar otra Entrada dentro de los 90 segundos de la última Entrada.", employee=employee, code="duplicate_mark")
        raise AttendanceRegistrationError("No se puede registrar otra Entrada sin una Salida previa.", employee=employee, code="entry_without_exit")
    if mark_type == AttendanceLog.EXIT:
        if latest_log is None:
            raise AttendanceRegistrationError("No se puede registrar una Salida sin una Entrada previa.", employee=employee, code="exit_without_entry")
        if latest_log.mark_type == AttendanceLog.EXIT:
            delta_seconds = abs((marked_at - latest_log.marked_at).total_seconds())
            if delta_seconds < MINIMUM_MARK_GAP_SECONDS:
                raise AttendanceRegistrationError("No se puede registrar otra Salida dentro de los 90 segundos de la última Salida.", employee=employee, code="duplicate_mark")
            raise AttendanceRegistrationError("No se puede registrar otra Salida sin una Entrada previa.", employee=employee, code="exit_without_entry")


def validate_manual_attendance(func):
    @wraps(func)
    def wrapper(employee_id, marked_at, mark_type, *args, **kwargs):
        if mark_type not in (AttendanceLog.ENTRY, AttendanceLog.EXIT):
            raise AttendanceRegistrationError("Cada fila debe indicar Entrada o Salida.", code="invalid_mark_type")
        employee = Employee.objects.select_related("department").filter(pk=employee_id).first()
        if employee is None:
            raise AttendanceRegistrationError("El empleado no existe.", code="not_found")
        _validate_mark_transition(employee, marked_at, mark_type)
        return func(employee_id, marked_at, mark_type, *args, **kwargs)

    return wrapper


@validate_manual_attendance
def register_manual_entry(employee_id, marked_at, mark_type, source="Registro manual", registered_by=None, capture_mode=AttendanceLog.MANUAL):
    employee = Employee.objects.select_related("department").filter(pk=employee_id).first()
    if employee is None:
        raise AttendanceRegistrationError("El empleado no existe.", code="not_found")
    latest_log = employee.attendance_logs.filter(marked_at__lte=marked_at).order_by("-marked_at", "-pk").first()
    has_open_entry = latest_log is not None and latest_log.mark_type == AttendanceLog.ENTRY and latest_log.session_status != AttendanceLog.SESSION_INCOMPLETE
    if employee.status not in Employee.ACCESS_ALLOWED_STATUSES and not (mark_type == AttendanceLog.EXIT and has_open_entry):
        reason = employee.access_message
        with transaction.atomic():
            attempt = AttendanceAttempt.objects.create(
                employee=employee,
                attempted_by=registered_by,
                employee_status=employee.status,
                mark_type=mark_type,
                reason=reason,
                source=source[:120],
            )
            if registered_by:
                LogEntry.objects.log_action(
                    user_id=registered_by.pk,
                    content_type_id=ContentType.objects.get_for_model(AttendanceAttempt).pk,
                    object_id=attempt.pk,
                    object_repr=employee.full_name,
                    action_flag=CHANGE,
                    change_message=(
                        f"Intento de marcaje manual denegado para {employee.full_name}: "
                        f"estatus {employee.get_status_display()} ({employee.status}). Motivo: {reason}"
                    ),
                )
        raise AttendanceRegistrationError(reason, employee=employee, code="blocked")
    now = timezone.now()
    if marked_at < now - MANUAL_ATTENDANCE_WINDOW:
        raise AttendanceRegistrationError("La fecha no puede ser anterior a 72 horas.", employee=employee)
    if marked_at > now:
        raise AttendanceRegistrationError("La fecha no puede ser futura.", employee=employee)
    with transaction.atomic():
        log = _create_attendance_log(employee, source, mark_type, registered_by, marked_at, capture_mode)
        return log


def _create_attendance_log(employee, source, mark_type, registered_by, marked_at, capture_mode=AttendanceLog.MANUAL):
    latest_log = employee.attendance_logs.filter(marked_at__lte=marked_at).order_by("-marked_at", "-pk").first()
    if mark_type == AttendanceLog.ENTRY and latest_log and latest_log.mark_type == AttendanceLog.ENTRY:
        raise AttendanceRegistrationError("No se puede registrar otra Entrada sin una Salida previa.", employee=employee, code="entry_without_exit")
    session_status = AttendanceLog.SESSION_COMPLETE
    if mark_type == AttendanceLog.ENTRY and latest_log and latest_log.mark_type == AttendanceLog.EXIT and (marked_at - latest_log.marked_at).total_seconds() < MINIMUM_MARK_GAP_SECONDS:
        session_status = AttendanceLog.SESSION_INCOMPLETE
    return AttendanceLog.objects.create(employee=employee, marked_at=marked_at, mark_type=mark_type, session_status=session_status, source=source[:120], capture_mode=capture_mode, registered_by=registered_by)


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
            "position": log.employee.position,
            "photo": log.employee.photo.url if log.employee.photo else "",
            "mark_type": log.mark_type,
            "marked_at": log.marked_at.isoformat(),
            "status": log.employee.status,
            "session_status": log.session_status,
        },
    }
    async_to_sync(channel_layer.group_send)("garita-live", {"type": "broadcast.event", "payload": payload})
    async_to_sync(channel_layer.group_send)("admin-alerts", {"type": "broadcast.event", "payload": {"type": "system.notice", "event": "attendance_processed", "data": payload["data"]}})


def broadcast_kiosk_event(event, data=None, message=""):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    payload = {"type": event, "event": event, "message": message, "data": data or {}}
    async_to_sync(channel_layer.group_send)("garita-live", {"type": "broadcast.event", "payload": payload})


def broadcast_alert_event(event_type, message, level="info", **payload):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    notice = {"type": "system.alert", "event": event_type, "level": level, "message": message, "payload": payload}
    async_to_sync(channel_layer.group_send)("admin-alerts", {"type": "broadcast.event", "payload": notice})
