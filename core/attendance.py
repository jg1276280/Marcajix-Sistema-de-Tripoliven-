"""Cálculo de tiempos a partir de la secuencia de movimientos (entradas y salidas) de cada persona.

El sistema no conoce turnos ni horarios: una *sesión* es el intervalo entre una entrada y la
salida siguiente, y pertenece al día en que empezó (así un turno nocturno que termina de
madrugada cuenta para el día en que entró). Lo que no encaja en ese patrón se informa como
*incidencia* y no suma horas:

- Entrada sin salida: tras una entrada viene otra entrada, o pasó demasiado tiempo sin salida.
- Salida sin entrada: una salida que no cierra ninguna entrada.
- Sesión demasiado larga: entre entrada y salida hay más de ATTENDANCE_MAX_SESSION_HOURS.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from employees.models import Employee

from .models import AttendanceLog

ENTRY_WITHOUT_EXIT = "Entrada sin salida"
EXIT_WITHOUT_ENTRY = "Salida sin entrada"
SESSION_TOO_LONG = "Sesión demasiado larga"


def workday_seconds():
    return settings.ATTENDANCE_WORKDAY_HOURS * 3600


def max_session():
    return timedelta(hours=settings.ATTENDANCE_MAX_SESSION_HOURS)


@dataclass
class Incident:
    label: str
    at: datetime


@dataclass
class DaySummary:
    """Resumen de un empleado en un día: primera llegada, última salida, horas y extras."""

    employee_id: int
    day: object
    first_entry: datetime = None
    last_exit: datetime = None
    worked_seconds: float = 0
    sessions: int = 0
    is_open: bool = False
    incidents: list = field(default_factory=list)

    @property
    def worked_hours(self):
        return round(self.worked_seconds / 3600, 2)

    @property
    def overtime_hours(self):
        return round(max(0, self.worked_seconds - workday_seconds()) / 3600, 2)


def _local_day(moment):
    return timezone.localtime(moment).date()


def _day_bounds(start_day, end_day):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(start_day, time.min), tz), timezone.make_aware(datetime.combine(end_day + timedelta(days=1), time.min), tz)


def summarize_marks(marks, now=None):
    """Convierte los movimientos de UN empleado (ordenados por hora) en resúmenes diarios.

    `marks` es una lista de tuplas (marked_at, mark_type). Devuelve {día: DaySummary}.
    """
    now = now or timezone.now()
    limit = max_session()
    days = {}
    open_entry = None

    def day_summary(employee_day):
        if employee_day not in days:
            days[employee_day] = DaySummary(employee_id=None, day=employee_day)
        return days[employee_day]

    def close_without_exit(entry):
        day_summary(_local_day(entry)).incidents.append(Incident(ENTRY_WITHOUT_EXIT, entry))

    for marked_at, mark_type in marks:
        if mark_type == AttendanceLog.ENTRY:
            if open_entry is not None:
                close_without_exit(open_entry)
            open_entry = marked_at
            day = day_summary(_local_day(marked_at))
            day.first_entry = day.first_entry or marked_at
            continue
        if open_entry is None:
            day_summary(_local_day(marked_at)).incidents.append(Incident(EXIT_WITHOUT_ENTRY, marked_at))
            continue
        day = day_summary(_local_day(open_entry))
        duration = marked_at - open_entry
        if duration > limit:
            day.incidents.append(Incident(SESSION_TOO_LONG, open_entry))
        else:
            day.worked_seconds += duration.total_seconds()
            day.sessions += 1
            day.last_exit = marked_at
        open_entry = None

    if open_entry is not None:
        if now - open_entry > limit:
            close_without_exit(open_entry)
        else:
            day_summary(_local_day(open_entry)).is_open = True
    return days


def daily_summaries(start_day, end_day, employee_ids=None, now=None):
    """Resúmenes diarios de todos los empleados (o de los indicados) entre dos fechas incluidas.

    Hace UNA consulta: trae los movimientos del rango ampliado con el margen de una sesión
    máxima a cada lado, para no cortar sesiones que cruzan la medianoche del primer o último día.
    """
    start, end = _day_bounds(start_day, end_day)
    margin = max_session()
    logs = AttendanceLog.objects.filter(marked_at__gte=start - margin, marked_at__lt=end + margin)
    if employee_ids is not None:
        logs = logs.filter(employee_id__in=list(employee_ids))
    marks_by_employee = defaultdict(list)
    for employee_id, marked_at, mark_type in logs.order_by("employee_id", "marked_at", "pk").values_list("employee_id", "marked_at", "mark_type"):
        marks_by_employee[employee_id].append((marked_at, mark_type))

    results = []
    for employee_id, marks in marks_by_employee.items():
        for day, summary in summarize_marks(marks, now=now).items():
            if start_day <= day <= end_day:
                summary.employee_id = employee_id
                results.append(summary)
    results.sort(key=lambda item: (item.day, item.employee_id))
    return results


@dataclass
class EmployeeTotals:
    employee: Employee
    days_worked: int = 0
    worked_seconds: float = 0
    overtime_seconds: float = 0
    incidents: int = 0
    arrivals: list = field(default_factory=list)
    departures: list = field(default_factory=list)

    @property
    def worked_hours(self):
        return round(self.worked_seconds / 3600, 2)

    @property
    def overtime_hours(self):
        return round(self.overtime_seconds / 3600, 2)

    @property
    def average_arrival(self):
        return average_clock(self.arrivals)

    @property
    def average_departure(self):
        return average_clock(self.departures)


def employee_totals(summaries, employees):
    """Agrupa los resúmenes diarios por empleado (para el informe de RRHH)."""
    by_id = {employee.pk: EmployeeTotals(employee=employee) for employee in employees}
    limit = workday_seconds()
    for summary in summaries:
        totals = by_id.get(summary.employee_id)
        if totals is None:
            continue
        if summary.sessions:
            totals.days_worked += 1
        totals.worked_seconds += summary.worked_seconds
        totals.overtime_seconds += max(0, summary.worked_seconds - limit)
        totals.incidents += len(summary.incidents)
        if summary.first_entry:
            totals.arrivals.append(timezone.localtime(summary.first_entry))
        if summary.last_exit:
            totals.departures.append(timezone.localtime(summary.last_exit))
    return list(by_id.values())


def average_clock(moments):
    """Hora media (HH:MM) de una lista de fechas locales, ignorando el día."""
    if not moments:
        return None
    seconds = round(sum(moment.hour * 3600 + moment.minute * 60 + moment.second for moment in moments) / len(moments))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}"


def people_inside(now=None):
    """Empleados cuyo último movimiento es una entrada, con la hora en que entraron.

    Si la entrada supera la sesión máxima se marca `stale`: probablemente olvidó marcar la salida.
    """
    now = now or timezone.now()
    latest = AttendanceLog.objects.filter(employee_id=OuterRef("pk")).order_by("-marked_at", "-pk")
    employees = (
        Employee.objects.with_structure()
        .annotate(last_mark=Subquery(latest.values("mark_type")[:1]), inside_since=Subquery(latest.values("marked_at")[:1]))
        .filter(last_mark=AttendanceLog.ENTRY)
        .order_by("-inside_since")
    )
    limit = max_session()
    people = list(employees)
    for employee in people:
        employee.stale = now - employee.inside_since > limit
    return people


PERIODS = {"today": "Hoy", "week": "Esta semana", "month": "Este mes", "range": "Rango"}


def resolve_period(params, default="week"):
    """Interpreta ?period=today|week|month|range&from=AAAA-MM-DD&to=AAAA-MM-DD → (clave, inicio, fin)."""
    from django.utils.dateparse import parse_date

    period = params.get("period", default)
    today = timezone.localdate()
    if period == "today":
        return period, today, today
    if period == "month":
        return period, today.replace(day=1), today
    if period == "range":
        start, end = parse_date(params.get("from", "") or ""), parse_date(params.get("to", "") or "")
        if start and end:
            if start > end:
                start, end = end, start
            return period, start, min(end, start + timedelta(days=366))
    return "week", today - timedelta(days=today.weekday()), today


def presence_board(now=None):
    """Situación de hoy en la puerta: quién está dentro, quién ya salió y quién no ha marcado."""
    from django.db.models import Min, Q

    now = now or timezone.now()
    today = timezone.localdate(now)
    today_start, _ = _day_bounds(today, today)
    latest = AttendanceLog.objects.filter(employee_id=OuterRef("pk")).order_by("-marked_at", "-pk")
    employees = list(
        Employee.objects.with_structure()
        .filter(status__in=Employee.ACCESS_ALLOWED_STATUSES)
        .annotate(
            last_mark=Subquery(latest.values("mark_type")[:1]),
            last_mark_at=Subquery(latest.values("marked_at")[:1]),
            first_entry_today=Min("attendance_logs__marked_at", filter=Q(attendance_logs__mark_type=AttendanceLog.ENTRY, attendance_logs__marked_at__gte=today_start, attendance_logs__voided_at__isnull=True)),
        )
        .order_by("full_name")
    )
    limit = max_session()
    inside, left, absent, celebrations = [], [], [], []
    for employee in employees:
        employee.celebration_today = employee.celebration(today)
        if employee.celebration_today:
            celebrations.append(employee)
        if employee.last_mark == AttendanceLog.ENTRY:
            employee.stale = now - employee.last_mark_at > limit
            inside.append(employee)
        elif employee.last_mark == AttendanceLog.EXIT and employee.last_mark_at >= today_start:
            left.append(employee)
        else:
            absent.append(employee)
    inside.sort(key=lambda item: item.last_mark_at, reverse=True)
    left.sort(key=lambda item: item.last_mark_at, reverse=True)
    return {"inside": inside, "left": left, "absent": absent, "celebrations": celebrations, "today": today}
