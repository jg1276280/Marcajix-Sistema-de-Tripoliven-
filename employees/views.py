from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Max, Min, Q, When
from django.core.paginator import Paginator
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import date, datetime, time, timedelta

from core.permissions import staff_required

from core.models import AttendanceLog

from .forms import DepartmentForm, DepartmentRenameForm, EmployeeForm, ManagementForm, ManagementRenameForm
from .models import Department, Employee, Management


def _average_clock(values):
    if not values:
        return None
    average_seconds = round(sum(value.hour * 3600 + value.minute * 60 + value.second for value in values) / len(values))
    return f"{average_seconds // 3600:02d}:{(average_seconds % 3600) // 60:02d}"


def _build_attendance_sessions(logs):
    sessions = []
    incongruences = []
    open_entry = None
    for log in sorted(logs, key=lambda item: (item.marked_at, item.pk)):
        if log.session_status in {AttendanceLog.SESSION_INCOMPLETE, AttendanceLog.SESSION_ORPHAN}:
            if log.mark_type == AttendanceLog.ENTRY:
                if open_entry is not None:
                    incongruences.append({"label": "Entrada repetida", "at": timezone.localtime(log.marked_at)})
                else:
                    open_entry = log
                    incongruences.append({"label": "Sesión incompleta", "at": timezone.localtime(log.marked_at)})
            else:
                incongruences.append({"label": "Salida huérfana", "at": timezone.localtime(log.marked_at)})
            continue
        if log.mark_type == "entry":
            if open_entry is not None:
                incongruences.append({"label": "Entrada repetida", "at": timezone.localtime(log.marked_at)})
                continue
            open_entry = log
            continue
        if log.mark_type == "exit":
            if open_entry is None:
                incongruences.append({"label": "Salida sin entrada", "at": timezone.localtime(log.marked_at)})
                continue
            duration = (log.marked_at - open_entry.marked_at).total_seconds()
            if duration <= 0:
                incongruences.append({"label": "Intervalo inválido", "at": timezone.localtime(log.marked_at)})
            else:
                sessions.append({"entry": open_entry, "exit": log, "hours": round(duration / 3600, 2)})
            open_entry = None
    return sessions, incongruences, open_entry


def _audit(request, employee, action, detail):
    LogEntry.objects.log_action(user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(Employee).pk, object_id=employee.pk, object_repr=employee.full_name, action_flag=action, change_message=detail)


@login_required
def employee_list(request):
    query = request.GET.get("q", "").strip()
    view_mode = request.GET.get("view", "grid")
    if view_mode not in {"grid", "list"}:
        view_mode = "grid"
    employees = Employee.objects.select_related("user", "department", "management").annotate(
        inactive_sort=Case(
            When(status__in=(Employee.INACTIVE, Employee.RETIRED), then=1),
            default=0,
            output_field=IntegerField(),
        )
    ).order_by("inactive_sort", "full_name")
    if query:
        employees = employees.filter(Q(full_name__icontains=query) | Q(identification__icontains=query) | Q(hid_card_code__icontains=query) | Q(department__name__icontains=query) | Q(management__name__icontains=query))
    page = Paginator(employees, 12).get_page(request.GET.get("page"))
    return render(request, "dashboard/employees/index.html", {"employees": page, "page_obj": page, "query": query, "view_mode": view_mode, "employee_form": EmployeeForm(), "active_page": "employees"})


@staff_required
def employee_create(request):
    form = EmployeeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        _audit(request, employee, ADDITION, "Empleado creado desde el módulo Personal.")
        messages.success(request, "Empleado creado correctamente.")
        return redirect("employees:list")
    employees = Paginator(Employee.objects.select_related("user", "department", "management"), 12).get_page(request.GET.get("page"))
    return render(request, "dashboard/employees/index.html", {"employees": employees, "page_obj": employees, "query": "", "view_mode": request.GET.get("view", "grid"), "employee_form": form, "open_modal": "create", "active_page": "employees"})


@staff_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        _audit(request, employee, CHANGE, "Ficha del empleado actualizada desde el módulo Personal.")
        messages.success(request, "Empleado actualizado correctamente.")
        return redirect("employees:list")
    employees = Paginator(Employee.objects.select_related("user", "department", "management"), 12).get_page(request.GET.get("page"))
    return render(request, "dashboard/employees/index.html", {"employees": employees, "page_obj": employees, "query": "", "view_mode": request.GET.get("view", "grid"), "employee_form": form, "editing_employee": employee, "open_modal": "edit", "active_page": "employees"})


@staff_required
def employee_toggle_status(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        if employee.status in (Employee.ACTIVE, Employee.INACTIVE):
            employee.status = Employee.INACTIVE if employee.status == Employee.ACTIVE else Employee.ACTIVE
            employee.save(update_fields=["status", "updated_at"])
            _audit(request, employee, CHANGE, f"Estado del empleado cambiado a {employee.get_status_display()} desde el módulo Personal.")
            messages.success(request, f"Empleado marcado como {employee.get_status_display()} correctamente.")
        else:
            messages.warning(request, "Este estado debe cambiarse desde la edición de la ficha del empleado.")
    return redirect("employees:list")


@staff_required
def employee_delete(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == "POST":
        if employee.has_important_history:
            messages.error(request, "No es posible eliminar al empleado porque posee marcajes o historial de seguridad. Utilice la opción de inactivación (borrado lógico).")
            return redirect("employees:detail", pk=employee.pk)
        try:
            employee.delete()
        except ProtectedError:
            messages.error(request, "No es posible eliminar al empleado porque posee historial relacionado. Utilice la opción de inactivación (borrado lógico).")
            return redirect("employees:detail", pk=employee.pk)
        messages.success(request, "Empleado eliminado correctamente.")
        return redirect("employees:list")
    return redirect("employees:detail", pk=employee.pk)


@login_required
def employee_detail(request, pk):

    employee = get_object_or_404(Employee.objects.select_related("user", "department", "management"), pk=pk)
    latest_attendance = employee.attendance_logs.order_by("-marked_at", "-pk").first()
    period = request.GET.get("period", "all")
    if period not in {"all", "today", "week", "month", "range"}:
        period = "all"
    today = timezone.localdate()
    date_from = request.GET.get("from", "")
    date_to = request.GET.get("to", "")
    if period == "all":
        bounds = employee.attendance_logs.aggregate(min_date=Min("marked_at"), max_date=Max("marked_at"))
        if bounds["min_date"] and bounds["max_date"]:
            period_start = timezone.localtime(bounds["min_date"]).date()
            period_end = timezone.localtime(bounds["max_date"]).date()
        else:
            period_start = period_end = today
    elif period == "today":
        period_start = period_end = today
    elif period == "week":
        period_start = today - timedelta(days=today.weekday())
        period_end = period_start + timedelta(days=6)
    elif period == "month":
        period_start = today.replace(day=1)
        period_end = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    else:
        try:
            period_start, period_end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except ValueError:
            period_start = period_end = today

    start_dt = timezone.make_aware(datetime.combine(period_start, time.min))
    end_dt = timezone.make_aware(datetime.combine(period_end + timedelta(days=1), time.min))
    period_logs = list(employee.attendance_logs.select_related("registered_by").filter(marked_at__gte=start_dt, marked_at__lt=end_dt))
    sessions, incongruences, open_entry = _build_attendance_sessions(period_logs)
    total_seconds = sum(session["hours"] * 3600 for session in sessions)
    local_entries = [timezone.localtime(session["entry"].marked_at) for session in sessions]
    local_exits = [timezone.localtime(session["exit"].marked_at) for session in sessions]
    session_quality = round((len(sessions) / (len(sessions) + len(incongruences))) * 100) if sessions or incongruences else None
    daily_hours = {}
    for session in sessions:
        day = timezone.localtime(session["entry"].marked_at).date().isoformat()
        daily_hours[day] = daily_hours.get(day, 0) + session["hours"]
    chart_start = max(period_start, period_end - timedelta(days=6))
    chart_days = [{"label": day.strftime("%d/%m"), "hours": round(daily_hours.get(day.isoformat(), 0), 2)} for day in (chart_start + timedelta(days=index) for index in range((period_end - chart_start).days + 1))]
    chart_max = max((item["hours"] for item in chart_days), default=1) or 1
    for item in chart_days:
        item["height"] = max(4, round(item["hours"] / chart_max * 100))
    recent_statuses = [{"date": timezone.localtime(session["entry"].marked_at).strftime("%d/%m"), "time": timezone.localtime(session["entry"].marked_at).strftime("%H:%M"), "label": "Sesión completa", "tone": "on-time"} for session in sessions[-5:]]
    attendance_status = "unknown"
    attendance_status_label = "Sin movimientos"
    if latest_attendance:
        attendance_status = "inside" if latest_attendance.mark_type == AttendanceLog.ENTRY else "outside"
        attendance_status_label = "Dentro" if attendance_status == "inside" else "Fuera"
    return render(request, "dashboard/employees/detail.html", {"employee": employee, "latest_attendance": latest_attendance, "average_times": {"entry": _average_clock(local_entries), "exit": _average_clock(local_exits)}, "attendance_status": attendance_status, "attendance_status_label": attendance_status_label, "period": period, "date_from": date_from, "date_to": date_to, "period_start": period_start, "period_end": period_end, "total_hours": round(total_seconds / 3600, 2), "balance_hours": round(total_seconds / 3600 - float(employee.workday_hours) * len(sessions), 2), "complete_sessions": len(sessions), "session_quality": session_quality, "incongruences": incongruences, "open_session": open_entry is not None, "chart_days": chart_days, "recent_statuses": recent_statuses, "active_page": "employees"})


@staff_required
def structure_settings(request):
    action = request.POST.get("action") if request.method == "POST" else None
    management_form = ManagementForm(request.POST if action == "management_create" else None, prefix="management")
    department_form = DepartmentForm(request.POST if action == "department_create" else None, prefix="department")
    editing_management = None
    editing_department = None
    if request.method == "POST":
        if action == "management_create":
            form = management_form
        elif action == "department_create":
            form = department_form
        elif action == "management_update":
            management = get_object_or_404(Management, pk=request.POST.get("pk"))
            form = ManagementRenameForm(request.POST, instance=management)
            editing_management = management
        elif action == "department_update":
            department = get_object_or_404(Department, pk=request.POST.get("pk"))
            form = DepartmentRenameForm(request.POST, instance=department)
            editing_department = department
        elif action == "management_delete":
            management = get_object_or_404(Management, pk=request.POST.get("pk"))
            try:
                with transaction.atomic():
                    if management.departments.exists() or management.employees.exists():
                        raise ProtectedError("La gerencia tiene datos vinculados.", management)
                    management.delete()
            except ProtectedError:
                messages.error(request, "No se puede eliminar la gerencia porque tiene departamentos o empleados vinculados.")
            else:
                messages.success(request, "Gerencia eliminada correctamente.")
            return redirect("employees:structure")
        elif action == "department_delete":
            department = get_object_or_404(Department, pk=request.POST.get("pk"))
            try:
                with transaction.atomic():
                    if department.employees.exists():
                        raise ProtectedError("El departamento tiene empleados vinculados.", department)
                    department.delete()
            except ProtectedError:
                messages.error(request, "No se puede eliminar el departamento porque tiene empleados vinculados.")
            else:
                messages.success(request, "Departamento eliminado correctamente.")
            return redirect("employees:structure")
        else:
            messages.error(request, "Acción de estructura no reconocida.")
            return redirect("employees:structure")

        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "Estructura organizativa actualizada correctamente.")
            return redirect("employees:structure")
    managements = Management.objects.annotate(
        department_count=Count("departments", distinct=True),
        employee_count=Count("employees", distinct=True),
    ).prefetch_related("departments")
    structure_edit_form = form if request.method == "POST" and action in {"management_update", "department_update"} else None
    return render(request, "dashboard/employees/structure.html", {"managements": managements, "management_form": management_form, "department_form": department_form, "editing_management": editing_management, "editing_department": editing_department, "editing_structure_pk": editing_management.pk if editing_management else editing_department.pk if editing_department else None, "structure_edit_form": structure_edit_form, "active_page": "structure"})