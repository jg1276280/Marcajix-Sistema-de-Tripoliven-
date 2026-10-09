from datetime import timedelta

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


# ---------------------------------------------------------------------------
# Correcciones de Recursos Humanos (solo si Sistemas las activa).
# ---------------------------------------------------------------------------
MIN_REASON_LENGTH = 5


def corrections_enabled():
    from .models import SystemSettings

    return SystemSettings.load().allow_attendance_corrections


def _clean_reason(reason):
    reason = " ".join((reason or "").split())
    if len(reason) < MIN_REASON_LENGTH:
        raise AttendanceRegistrationError("Indique el motivo de la corrección (mínimo 5 caracteres).", code="reason_required")
    return reason[:255]


def _audit_correction(user, log, message):
    LogEntry.objects.log_action(user_id=user.pk, content_type_id=ContentType.objects.get_for_model(AttendanceLog).pk, object_id=log.pk, object_repr=f"{log.employee.full_name} · {timezone.localtime(log.marked_at):%d/%m/%Y %H:%M}", action_flag=CHANGE, change_message=message)


def add_correction(employee_id, marked_at, mark_type, reason, user):
    """Añade un marcaje olvidado. Debe alternar con el marcaje anterior y con el siguiente."""
    reason = _clean_reason(reason)
    if mark_type not in (AttendanceLog.ENTRY, AttendanceLog.EXIT):
        raise AttendanceRegistrationError("Indique si es Entrada o Salida.", code="invalid_mark_type")
    if marked_at > timezone.now():
        raise AttendanceRegistrationError("La fecha no puede ser futura.", code="future")
    with transaction.atomic():
        employee = Employee.objects.select_for_update().filter(pk=employee_id).first()
        if employee is None:
            raise AttendanceRegistrationError("El empleado no existe.", code="not_found")
        _validate_mark_transition(employee, latest_mark(employee, until=marked_at), marked_at, mark_type)
        following = employee.attendance_logs.filter(marked_at__gt=marked_at).order_by("marked_at", "pk").first()
        if following is not None and following.mark_type == mark_type:
            label = following.get_mark_type_display()
            raise AttendanceRegistrationError(f"El marcaje siguiente ({timezone.localtime(following.marked_at):%d/%m %H:%M}) ya es una {label}: no puede haber dos seguidas.", employee=employee, code="sequence")
        log = AttendanceLog.objects.create(employee=employee, marked_at=marked_at, mark_type=mark_type, source="Corrección de RRHH", capture_mode=AttendanceLog.CORRECTION, registered_by=user, correction_reason=reason)
        _audit_correction(user, log, f"Corrección: se añadió una {log.get_mark_type_display()} para {employee.full_name}. Motivo: {reason}")
    return log


def void_mark(log_id, reason, user):
    """Anula un marcaje erróneo. No se borra: deja de contar y queda en el historial y la auditoría."""
    reason = _clean_reason(reason)
    with transaction.atomic():
        log = AttendanceLog.objects.select_for_update().select_related("employee").filter(pk=log_id).first()
        if log is None:
            raise AttendanceRegistrationError("El marcaje no existe o ya fue anulado.", code="not_found")
        log.voided_at = timezone.now()
        log.voided_by = user
        log.void_reason = reason
        log.save(update_fields=["voided_at", "voided_by", "void_reason"])
        _audit_correction(user, log, f"Corrección: se anuló una {log.get_mark_type_display()} de {log.employee.full_name}. Motivo: {reason}")
    return log
