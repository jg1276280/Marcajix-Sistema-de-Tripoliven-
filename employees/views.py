from django.conf import settings
from django.contrib import messages
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Q, When
from django.core.paginator import Paginator
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from datetime import timedelta

from core.permissions import MANAGE_EMPLOYEES, MANAGE_STRUCTURE, VIEW_ANALYTICS, VIEW_EMPLOYEES, capability_required

from core.attendance import PERIODS, daily_summaries, employee_totals, resolve_period
from core.models import AttendanceLog

from .forms import DepartmentForm, DepartmentRenameForm, EmployeeForm, ManagementForm, ManagementRenameForm, PositionForm, PositionRenameForm
from .models import Department, Employee, Management, Position


def _audit(request, employee, action, detail):
    LogEntry.objects.log_action(user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(Employee).pk, object_id=employee.pk, object_repr=employee.full_name, action_flag=action, change_message=detail)


@capability_required(VIEW_EMPLOYEES)
def employee_list(request):
    query = request.GET.get("q", "").strip()
    view_mode = request.GET.get("view", "grid")
    if view_mode not in {"grid", "list"}:
        view_mode = "grid"
    employees = Employee.objects.with_structure().annotate(
        inactive_sort=Case(
            When(status__in=(Employee.INACTIVE, Employee.RETIRED), then=1),
            default=0,
            output_field=IntegerField(),
        )
    ).order_by("inactive_sort", "full_name")
    if query:
        employees = employees.filter(Q(full_name__icontains=query) | Q(identification__icontains=query) | Q(hid_card_code__icontains=query) | Q(position__name__icontains=query) | Q(position__department__name__icontains=query) | Q(position__department__management__name__icontains=query))
    page = Paginator(employees, 24).get_page(request.GET.get("page"))
    querystring = request.GET.copy()
    querystring.pop("page", None)
    return render(request, "dashboard/employees/index.html", {"querystring": querystring.urlencode(), "employees": page, "page_obj": page, "query": query, "view_mode": view_mode, "employee_form": EmployeeForm(), "active_page": "employees"})


@capability_required(MANAGE_EMPLOYEES)
def employee_create(request):
    form = EmployeeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        _audit(request, employee, ADDITION, "Empleado creado desde el módulo Personal.")
        messages.success(request, "Empleado creado correctamente.")
        return redirect("employees:list")
    employees = Paginator(Employee.objects.with_structure(), 12).get_page(request.GET.get("page"))
    return render(request, "dashboard/employees/index.html", {"employees": employees, "page_obj": employees, "query": "", "view_mode": request.GET.get("view", "grid"), "employee_form": form, "open_modal": "create", "active_page": "employees"})


@capability_required(MANAGE_EMPLOYEES)
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        employee = form.save()
        _audit(request, employee, CHANGE, "Ficha del empleado actualizada desde el módulo Personal.")
        messages.success(request, "Empleado actualizado correctamente.")
        return redirect("employees:list")
    employees = Paginator(Employee.objects.with_structure(), 12).get_page(request.GET.get("page"))
    return render(request, "dashboard/employees/index.html", {"employees": employees, "page_obj": employees, "query": "", "view_mode": request.GET.get("view", "grid"), "employee_form": form, "editing_employee": employee, "open_modal": "edit", "active_page": "employees"})


@capability_required(MANAGE_EMPLOYEES)
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


@capability_required(MANAGE_EMPLOYEES)
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


@capability_required(VIEW_ANALYTICS)
def employee_detail(request, pk):
    employee = get_object_or_404(Employee.objects.with_structure(), pk=pk)
    period, start, end = resolve_period(request.GET)
    summaries = daily_summaries(start, end, employee_ids=[employee.pk])
    totals = employee_totals(summaries, [employee])[0]
    by_day = {summary.day: summary for summary in summaries}
    chart_start = max(start, end - timedelta(days=13))
    chart_days = [chart_start + timedelta(days=offset) for offset in range((end - chart_start).days + 1)]
    peak = max((by_day[day].worked_hours for day in chart_days if day in by_day), default=0) or 1
    chart = [{"day": day, "hours": by_day[day].worked_hours if day in by_day else 0, "percent": round((by_day[day].worked_hours if day in by_day else 0) / peak * 100)} for day in chart_days]
    latest = employee.attendance_logs.order_by("-marked_at", "-pk").first()
    return render(request, "dashboard/employees/detail.html", {
        "employee": employee,
        "period": period,
        "periods": PERIODS,
        "start": start,
        "end": end,
        "totals": totals,
        "days": list(reversed(summaries)),
        "chart": chart,
        "is_inside": latest is not None and latest.mark_type == AttendanceLog.ENTRY,
        "latest": latest,
        "recent_marks": employee.attendance_logs.select_related("registered_by").order_by("-marked_at", "-pk")[:8],
        "workday_hours": settings.ATTENDANCE_WORKDAY_HOURS,
        "active_page": "employees",
    })


_STRUCTURE_LEVELS = {
    "management": {"model": Management, "create_form": ManagementForm, "rename_form": ManagementRenameForm, "children": "departments", "deleted": "Gerencia eliminada correctamente.", "blocked": "No se puede eliminar la gerencia porque tiene departamentos vinculados."},
    "department": {"model": Department, "create_form": DepartmentForm, "rename_form": DepartmentRenameForm, "children": "positions", "deleted": "Departamento eliminado correctamente.", "blocked": "No se puede eliminar el departamento porque tiene cargos vinculados."},
    "position": {"model": Position, "create_form": PositionForm, "rename_form": PositionRenameForm, "children": "employees", "deleted": "Cargo eliminado correctamente.", "blocked": "No se puede eliminar el cargo porque tiene empleados vinculados."},
}


@capability_required(MANAGE_STRUCTURE)
def structure_settings(request):
    action = request.POST.get("action", "") if request.method == "POST" else ""
    level_name, _, operation = action.partition("_")
    level = _STRUCTURE_LEVELS.get(level_name)
    create_forms = {name: config["create_form"](request.POST if operation == "create" and name == level_name else None, prefix=name) for name, config in _STRUCTURE_LEVELS.items()}
    editing = None
    if request.method == "POST":
        if level is None or operation not in {"create", "update", "delete"}:
            messages.error(request, "Acción de estructura no reconocida.")
            return redirect("employees:structure")
        if operation == "delete":
            instance = get_object_or_404(level["model"], pk=request.POST.get("pk"))
            try:
                with transaction.atomic():
                    if getattr(instance, level["children"]).exists():
                        raise ProtectedError(level["blocked"], instance)
                    instance.delete()
            except ProtectedError:
                messages.error(request, level["blocked"])
            else:
                messages.success(request, level["deleted"])
            return redirect("employees:structure")
        if operation == "create":
            form = create_forms[level_name]
        else:
            instance = get_object_or_404(level["model"], pk=request.POST.get("pk"))
            form = level["rename_form"](request.POST, instance=instance)
            editing = {"level": level_name, "pk": instance.pk}
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "Estructura organizativa actualizada correctamente.")
            return redirect("employees:structure")
    positions = Position.objects.annotate(employee_count=Count("employees"))
    departments = Department.objects.annotate(position_count=Count("positions")).prefetch_related(Prefetch("positions", queryset=positions))
    managements = Management.objects.annotate(department_count=Count("departments")).prefetch_related(Prefetch("departments", queryset=departments))
    return render(request, "dashboard/employees/structure.html", {
        "managements": managements,
        "management_form": create_forms["management"],
        "department_form": create_forms["department"],
        "position_form": create_forms["position"],
        "editing": editing,
        "structure_edit_form": form if editing else None,
        "active_page": "structure",
    })
