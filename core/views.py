from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, OuterRef, Q, Subquery
from django.core.paginator import Paginator
from django.contrib.auth import update_session_auth_hash
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from datetime import datetime, time, timedelta
import json
from employees.models import Department, Employee

from .forms import AdminUserCreateForm, AdminUserUpdateForm, HIDReaderConfigForm, LoginForm, ProfileForm, ProfilePasswordForm, RegisterForm
from .permissions import staff_required
from .security import reset_failed_logins
from .models import AttendanceLog, HIDReaderConfig, SecurityEvent
from .services import AttendanceRegistrationError, broadcast_attendance_event, register_attendance


def _reader_port_status(config):
    """Check physical port availability and detect device type (RS-232 HID vs Bluetooth)."""
    try:
        from serial import Serial, SerialException
        from serial.tools import list_ports
        com_list = list(list_ports.comports())
        available = {item.device.upper(): item for item in com_list}
        if not available:
            return {
                "level": "warning",
                "code": "no_hardware",
                "message": "No se detectan puertos serie o lectores USB/RS-232 conectados físicamente a este equipo.",
                "available": [],
                "devices": [],
            }
        devices = []
        for device, info in available.items():
            hwid = info.hwid or ""
            is_bt = "BTHENUM" in hwid or "bluetooth" in (info.description or "").lower()
            devices.append({
                "port": info.device,
                "description": info.description or "Desconocido",
                "type": "bluetooth" if is_bt else "serial",
                "type_label": "Bluetooth (no compatible con HID RS-232)" if is_bt else "Serie / USB-Serial (compatible)",
            })
        devices.sort(key=lambda d: d["port"])
        available_names = sorted(available.keys())
        if config.port.upper() not in available:
            return {
                "level": "warning",
                "code": "missing",
                "message": f"El puerto {config.port} no está presente. Puertos detectados: {', '.join(available_names)}.",
                "available": available_names,
                "devices": devices,
            }
        port_info = available[config.port.upper()]
        hwid = port_info.hwid or ""
        is_bt = "BTHENUM" in hwid or "bluetooth" in (port_info.description or "").lower()
        if is_bt:
            warning_msg = (
                f"ADVERTENCIA: {config.port} ({port_info.description}) es un puerto Bluetooth virtual, "
                "no un lector HID RS-232 físico. Los lectores de tarjetas HID usan USB-Serial o RS-232 directo. "
                "Este puerto no producirá marcajes reales."
            )
        else:
            warning_msg = None
        try:
            reader = Serial(
                port=config.port,
                baudrate=config.baud_rate,
                bytesize=config.data_bits,
                parity=config.parity,
                stopbits=config.stop_bits,
                timeout=0.1,
            )
            reader.close()
        except (SerialException, ValueError) as error:
            return {
                "level": "error",
                "code": "unavailable",
                "message": f"El puerto {config.port} existe en el SO pero no se puede abrir: {error}",
                "available": available_names,
                "devices": devices,
            }
        if is_bt:
            return {
                "level": "warning",
                "code": "bluetooth",
                "message": warning_msg,
                "available": available_names,
                "devices": devices,
            }
        return {
            "level": "success",
            "code": "ready",
            "message": f"Puerto {config.port} listo y disponible ({port_info.description}). Puertos activos: {', '.join(available_names)}.",
            "available": available_names,
            "devices": devices,
        }
    except ImportError:
        return {"level": "error", "code": "dependency", "message": "La librería pyserial no está instalada en el entorno.", "available": [], "devices": []}


def _reader_read_test(config, timeout_seconds=10):
    """Open the port and attempt to read a single card code within timeout_seconds.

    Returns a dict with the read result, or an error/warning if the port cannot be opened.
    This function BLOCKS for up to timeout_seconds — call only from a regular (sync) view.
    """
    import time
    try:
        from serial import Serial, SerialException
    except ImportError:
        return {"level": "error", "code": "dependency", "message": "pyserial no está instalado.", "card_code": None}
    try:
        reader = Serial(
            port=config.port,
            baudrate=config.baud_rate,
            bytesize=config.data_bits,
            parity=config.parity,
            stopbits=config.stop_bits,
            timeout=1.0,
        )
    except Exception as exc:
        if "sem" in str(exc).lower() or "timeout" in str(exc).lower() or "could not open" in str(exc).lower():
            return {
                "level": "error",
                "code": "port_locked",
                "message": f"No se pudo abrir {config.port}. Puede que el listener HID ya esté corriendo en ese puerto, o que el puerto esté siendo utilizado por otro programa.",
                "card_code": None,
            }
        return {
            "level": "error",
            "code": "open_failed",
            "message": f"Error al abrir {config.port}: {exc}",
            "card_code": None,
        }
    deadline = time.monotonic() + timeout_seconds
    card_code = None
    try:
        while time.monotonic() < deadline:
            line = reader.readline()
            if line:
                decoded = line.decode("utf-8", errors="ignore").strip()
                if decoded:
                    card_code = decoded
                    break
    except Exception as exc:
        reader.close()
        return {
            "level": "error",
            "code": "read_error",
            "message": f"Error durante la lectura en {config.port}: {exc}",
            "card_code": None,
        }
    finally:
        reader.close()
    if card_code:
        return {
            "level": "success",
            "code": "card_read",
            "message": f"Tarjeta leída correctamente en {config.port}.",
            "card_code": card_code,
        }
    return {
        "level": "warning",
        "code": "no_card",
        "message": f"No se recibió ninguna tarjeta en {timeout_seconds} segundos. El puerto {config.port} está funcionando — acerque una tarjeta al lector y vuelva a intentar.",
        "card_code": None,
    }


def home(request):
    return redirect("dashboard" if request.user.is_authenticated else "login")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        messages.success(request, "Tu cuenta ya está lista.")
        return redirect("dashboard")
    return render(request, "auth/register.html", {"form": form})


@login_required
def dashboard(request):
    context = {"section": "Resumen", "active_page": "overview", "is_admin": request.user.is_staff}
    if request.user.is_staff:
        today = timezone.localdate()
        today_start = timezone.make_aware(datetime.combine(today, time.min))
        tomorrow_start = today_start + timedelta(days=1)
        user_counts = User.objects.aggregate(active=Count("pk", filter=Q(is_active=True)), total=Count("pk"))
        employee_counts = Employee.objects.aggregate(active=Count("pk", filter=Q(status=Employee.ACTIVE)), total=Count("pk"))
        context.update(
            active_user_count=user_counts["active"],
            user_count=user_counts["total"],
            active_employees_count=employee_counts["active"],
            employee_count=employee_counts["total"],
            today_logs_count=AttendanceLog.objects.filter(marked_at__gte=today_start, marked_at__lt=tomorrow_start).count(),
        )
    return render(request, "dashboard/index.html", context)


@staff_required
def device_config_view(request):
    config, _ = HIDReaderConfig.objects.get_or_create(id=1)
    form = HIDReaderConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "La configuración del lector se actualizó correctamente.")
        return redirect("device_config")
    return render(request, "dashboard/devices/config.html", {"form": form, "active_page": "device_config", "reader_status": _reader_port_status(config)})


@staff_required
def device_config_test(request):
    """Quick port availability check — no blocking read."""
    config, _ = HIDReaderConfig.objects.get_or_create(id=1)
    if request.method == "POST":
        form = HIDReaderConfigForm(request.POST, instance=config)
        if form.is_valid():
            config = form.save()
    return JsonResponse(_reader_port_status(config))


@staff_required
def device_read_test(request):
    """Block and try to read ONE card from the serial port within 10 seconds.

    This is a blocking HTTP call — the browser will wait up to ~12s for a response.
    Intended to be called from the config page when the user wants to verify that
    the physical reader actually delivers card codes correctly.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido."}, status=405)
    config, _ = HIDReaderConfig.objects.get_or_create(id=1)
    result = _reader_read_test(config, timeout_seconds=10)
    return JsonResponse(result)


def kiosk_unlock(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido."}, status=405)
    form = LoginForm(request, data=request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Las credenciales no son válidas."}, status=403)
    user = form.get_user()
    if not user.is_staff:
        return JsonResponse({"error": "Se requiere una cuenta de administrador."}, status=403)
    login(request, user)
    return JsonResponse({"redirect": "/dashboard/"})


def kiosk_garita(request):
    return render(request, "dashboard/kiosk/live.html")


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Tu perfil se actualizó correctamente.")
        return redirect("profile")
    password_form = ProfilePasswordForm(request.user)
    return render(request, "dashboard/profile.html", {"form": form, "password_form": password_form, "active_page": "profile"})


@login_required
def profile_password(request):
    form = ProfilePasswordForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, request.user)
        reset_failed_logins(request.user.pk)
        messages.success(request, "Tu contraseña se actualizó correctamente.")
        return redirect("profile")
    profile_form = ProfileForm(instance=request.user)
    return render(request, "dashboard/profile.html", {"form": profile_form, "password_form": form, "active_page": "profile", "password_error": True})


@staff_required
def user_list(request):
    query = request.GET.get("q", "").strip()
    users = User.objects.order_by("username")
    if query:
        users = users.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))
    return render(request, "dashboard/users/index.html", {"users": users, "query": query, "active_page": "users", "section": "Usuarios", "create_form": AdminUserCreateForm()})


@staff_required
def user_create(request):
    form = AdminUserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        created_user = form.save()
        LogEntry.objects.log_action(user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(User).pk, object_id=created_user.pk, object_repr=created_user.username, action_flag=ADDITION, change_message="Usuario creado desde el panel.")
        messages.success(request, "Usuario creado correctamente.")
        return redirect("user_list")
    users = User.objects.order_by("username")
    return render(request, "dashboard/users/index.html", {"users": users, "query": "", "active_page": "users", "create_form": form, "open_modal": "create"})


@staff_required
def user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = AdminUserUpdateForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        form.save()
        if user.is_active:
            reset_failed_logins(user.pk)
        LogEntry.objects.log_action(user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(User).pk, object_id=user.pk, object_repr=user.username, action_flag=CHANGE, change_message="Datos del usuario actualizados desde el panel.")
        messages.success(request, "Usuario actualizado correctamente.")
        return redirect("user_list")
    users = User.objects.order_by("username")
    return render(request, "dashboard/users/index.html", {"users": users, "query": "", "active_page": "users", "edit_form": form, "editing_user": user, "open_modal": "edit"})


@staff_required
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        if user.pk == request.user.pk:
            messages.error(request, "No puedes eliminar tu propia cuenta.")
        else:
            LogEntry.objects.log_action(user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(User).pk, object_id=user.pk, object_repr=user.username, action_flag=DELETION, change_message="Usuario eliminado desde el panel.")
            user.delete()
            messages.success(request, "Usuario eliminado correctamente.")
    return redirect("user_list")


@staff_required
def audit_log(request):
    query = request.GET.get("q", "").strip()
    logs = LogEntry.objects.select_related("user", "content_type").order_by("-action_time")
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()
    if not date_from and not date_to:
        today = timezone.localdate().isoformat()
        date_from = date_to = today
    if date_from:
        parsed_from = parse_date(date_from)
        if parsed_from:
            logs = logs.filter(action_time__gte=timezone.make_aware(datetime.combine(parsed_from, time.min)))
    if date_to:
        parsed_to = parse_date(date_to)
        if parsed_to:
            logs = logs.filter(action_time__lt=timezone.make_aware(datetime.combine(parsed_to + timedelta(days=1), time.min)))
    if query:
        logs = logs.filter(Q(object_repr__icontains=query) | Q(change_message__icontains=query) | Q(user__username__icontains=query))
    page = Paginator(logs, 25).get_page(request.GET.get("page"))
    return render(request, "dashboard/audit.html", {"logs": page, "page_obj": page, "query": query, "date_from": date_from, "date_to": date_to, "active_page": "audit"})


@login_required
def attendance_monitor(request):
    return render(request, "dashboard/attendance.html", {"active_page": "attendance"})


@login_required
def attendance_register(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido."}, status=405)
    if request.POST.get("capture_mode", AttendanceLog.MANUAL) != AttendanceLog.MANUAL:
        return JsonResponse({"error": "Marcajix solo permite registros manuales."}, status=400)
    source = f"Registro manual · {request.META.get('REMOTE_ADDR', 'desconocido')}"
    try:
        rows = json.loads(request.POST.get("rows", "[]"))
    except (TypeError, ValueError):
        rows = []
    if not isinstance(rows, list):
        rows = []
    successes, errors, warnings = [], [], []
    try:
        for row in rows:
            if not isinstance(row, dict):
                errors.append({"employee_id": None, "error": "Cada fila debe ser un objeto con employee_id, mark_type y marked_at.", "code": "invalid_row"})
                continue
            try:
                row_mark_type = row.get("mark_type")
                if row_mark_type not in (AttendanceLog.ENTRY, AttendanceLog.EXIT):
                    raise AttendanceRegistrationError("Cada fila debe indicar Entrada o Salida.")
                marked_at = parse_datetime(row.get("marked_at", ""))
                if marked_at is None:
                    raise AttendanceRegistrationError("La fecha y hora no son válidas.")
                if timezone.is_naive(marked_at):
                    marked_at = timezone.make_aware(marked_at, timezone.get_current_timezone())
                log = register_attendance(row.get("employee_id"), marked_at, row_mark_type, source=source, registered_by=request.user)
                payload = _attendance_payload(log)
                successes.append(payload)
                if log.employee.status == Employee.VACATION:
                    warnings.append({"employee_id": log.employee_id, "message": f"{log.employee.full_name}: el marcaje fue procesado, pero el empleado está de vacaciones. Verifica su presencia física o actualiza su estatus."})
                broadcast_attendance_event(log)
            except (AttendanceRegistrationError, TypeError, ValueError) as error:
                errors.append({"employee_id": row.get("employee_id"), "error": str(error), "code": getattr(error, "code", "invalid")})
    except Exception as exc:  # pragma: no cover - defensive catch for invalid payloads or unexpected runtime errors.
        return JsonResponse({"error": "No se pudo procesar el lote de marcajes.", "detail": str(exc), "errors": errors, "successes": successes, "warnings": warnings, "count": len(successes), "pending": len(errors)}, status=500)
    status = 201 if successes else 400
    return JsonResponse({"logs": successes, "successes": successes, "warnings": warnings, "errors": errors, "count": len(successes), "pending": len(errors), **(successes[0] if successes else {})}, status=status)


def _attendance_payload(log):
    return {"id": log.pk, "employee_id": log.employee_id, "employee": log.employee.full_name, "department": log.employee.department.name, "photo": log.employee.photo.url, "marked_at": log.marked_at.strftime("%d/%m/%Y %H:%M:%S"), "mark_type": log.get_mark_type_display(), "capture_mode": log.capture_mode, "employee_status": log.employee.status}


@login_required
def attendance_employee_search(request):
    query = request.GET.get("q", "").strip()
    latest_mark_type = Subquery(AttendanceLog.objects.filter(employee_id=OuterRef("pk")).order_by("-marked_at", "-pk").values("mark_type")[:1])
    employees = Employee.objects.with_structure().annotate(latest_mark_type=latest_mark_type)
    if request.GET.get("include_inactive") != "1":
        employees = employees.filter(status__in=Employee.ACCESS_ALLOWED_STATUSES)
    if query:
        employees = employees.filter(Q(full_name__icontains=query) | Q(identification__icontains=query) | Q(hid_card_code__icontains=query) | Q(position__department__name__icontains=query))
    results = []
    for employee in employees.order_by("full_name")[:30]:
        last_mark = dict(AttendanceLog.MARK_TYPES).get(employee.latest_mark_type, "Sin marcajes")
        results.append({"id": employee.pk, "name": employee.full_name, "hid_card_code": employee.hid_card_code or "Sin tarjeta", "department": employee.department.name, "initial": employee.full_name[:1], "last_mark": last_mark, "status": employee.status, "status_label": employee.get_status_display()})
    return JsonResponse({"employees": results})


@login_required
def attendance_history(request):
    logs = AttendanceLog.objects.select_related("employee__position__department", "registered_by")
    attempts = SecurityEvent.objects.select_related("employee__position__department", "attempted_by")
    query = request.GET.get("q", "").strip()
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()
    department = request.GET.get("department", "").strip()
    employee_ids = [value for value in request.GET.getlist("employee") if value.isdigit()]
    if not date_from and not date_to and not employee_ids:
        today = timezone.localdate().isoformat()
        date_from = date_to = today
    if query:
        logs = logs.filter(Q(employee__full_name__icontains=query) | Q(employee__identification__icontains=query))
        attempts = attempts.filter(Q(employee__full_name__icontains=query) | Q(employee__identification__icontains=query) | Q(hid_card_code__icontains=query) | Q(reason__icontains=query))
    if date_from:
        date_from_value = parse_date(date_from)
        if date_from_value:
            start = timezone.make_aware(datetime.combine(date_from_value, time.min))
            logs = logs.filter(marked_at__gte=start)
            attempts = attempts.filter(occurred_at__gte=start)
    if date_to:
        date_to_value = parse_date(date_to)
        if date_to_value:
            next_day = date_to_value + timedelta(days=1)
            end = timezone.make_aware(datetime.combine(next_day, time.min))
            logs = logs.filter(marked_at__lt=end)
            attempts = attempts.filter(occurred_at__lt=end)
    if department:
        logs = logs.filter(employee__position__department__name__icontains=department)
        attempts = attempts.filter(employee__position__department__name__icontains=department)
    if employee_ids:
        logs = logs.filter(employee_id__in=employee_ids)
        attempts = attempts.filter(employee_id__in=employee_ids)
    events = [{"kind": "log", "record": log, "timestamp": log.marked_at} for log in logs] + [{"kind": "attempt", "record": attempt, "timestamp": attempt.occurred_at} for attempt in attempts]
    events.sort(key=lambda event: event["timestamp"], reverse=True)
    page = Paginator(events, 25).get_page(request.GET.get("page"))
    departments = Department.objects.values_list("name", flat=True).distinct().order_by("name")
    selected_employees = Employee.objects.with_structure().filter(pk__in=employee_ids).order_by("full_name")
    return render(request, "dashboard/attendance_history.html", {"events": page, "page_obj": page, "query": query, "date_from": date_from, "date_to": date_to, "department": department, "employee_ids": employee_ids, "selected_employees": selected_employees, "departments": departments, "active_page": "attendance_history"})
