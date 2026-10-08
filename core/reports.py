"""Informes de Recursos Humanos: horas trabajadas, horas extra, llegadas, salidas e incidencias."""
import csv

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from employees.models import Department, Employee, Management

from .attendance import PERIODS, daily_summaries, employee_totals, resolve_period
from .permissions import VIEW_ANALYTICS, capability_required


def _filtered_employees(params):
    employees = Employee.objects.with_structure().order_by("full_name")
    query = params.get("q", "").strip()
    if query:
        employees = employees.filter(Q(full_name__icontains=query) | Q(identification__icontains=query) | Q(hid_card_code__icontains=query))
    if params.get("management", "").isdigit():
        employees = employees.filter(position__department__management_id=params["management"])
    if params.get("department", "").isdigit():
        employees = employees.filter(position__department_id=params["department"])
    return employees


def _report_data(params):
    period, start, end = resolve_period(params)
    employees = list(_filtered_employees(params))
    summaries = daily_summaries(start, end, employee_ids=[employee.pk for employee in employees])
    return period, start, end, employees, summaries


def _local_time(moment):
    return timezone.localtime(moment).strftime("%H:%M") if moment else ""


@capability_required(VIEW_ANALYTICS)
def attendance_report(request):
    period, start, end, employees, summaries = _report_data(request.GET)
    view = "daily" if request.GET.get("view") == "daily" else "summary"
    totals = employee_totals(summaries, employees)
    if view == "summary":
        # Primero quien tiene actividad o incidencias; dentro, por nombre.
        rows = sorted(totals, key=lambda item: (item.days_worked == 0 and item.incidents == 0, item.employee.full_name))
    else:
        names = {employee.pk: employee for employee in employees}
        rows = [summary for summary in reversed(summaries)]
        for summary in rows:
            summary.employee = names[summary.employee_id]
    page = Paginator(rows, 50).get_page(request.GET.get("page"))
    overview = {
        "worked_hours": round(sum(item.worked_seconds for item in totals) / 3600, 1),
        "overtime_hours": round(sum(item.overtime_seconds for item in totals) / 3600, 1),
        "incidents": sum(item.incidents for item in totals),
        "people": sum(1 for item in totals if item.days_worked),
    }
    query = request.GET.copy()
    query.pop("page", None)
    filters_query = query.copy()
    for key in ("period", "from", "to"):
        filters_query.pop(key, None)
    return render(request, "dashboard/reports.html", {
        "active_page": "reports",
        "page_obj": page,
        "view": view,
        "period": period,
        "periods": PERIODS,
        "start": start,
        "end": end,
        "overview": overview,
        "managements": Management.objects.order_by("name"),
        "departments": Department.objects.select_related("management").order_by("name"),
        "filters": request.GET,
        "querystring": query.urlencode(),
        "filters_querystring": filters_query.urlencode(),
        "workday_hours": f"{settings.ATTENDANCE_WORKDAY_HOURS:g} h",
    })


@capability_required(VIEW_ANALYTICS)
def attendance_report_export(request):
    """Detalle diario en CSV (separado por ';' y con BOM para que Excel en español lo abra bien)."""
    _, start, end, employees, summaries = _report_data(request.GET)
    names = {employee.pk: employee for employee in employees}
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="marcajix-{start:%Y%m%d}-{end:%Y%m%d}.csv"'
    response.write("﻿")
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Fecha", "Empleado", "Cédula", "Gerencia", "Departamento", "Cargo", "Primera entrada", "Última salida", "Horas trabajadas", "Horas extra", "Sesiones", "Incidencias"])
    for summary in summaries:
        employee = names[summary.employee_id]
        writer.writerow([
            summary.day.strftime("%d/%m/%Y"),
            employee.full_name,
            employee.identification,
            employee.management.name,
            employee.department.name,
            employee.position.name,
            _local_time(summary.first_entry),
            _local_time(summary.last_exit),
            f"{summary.worked_hours:.2f}".replace(".", ","),
            f"{summary.overtime_hours:.2f}".replace(".", ","),
            summary.sessions,
            " | ".join(f"{incident.label} {_local_time(incident.at)}" for incident in summary.incidents),
        ])
    return response
