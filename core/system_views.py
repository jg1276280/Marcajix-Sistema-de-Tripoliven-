"""Pantalla «Sistema» (rol Sistemas): respaldos de la base de datos y opciones generales."""
from django.contrib import messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .backups import BackupError, check_folder, list_backups, list_folders, run_backup
from .forms import SystemSettingsForm
from .models import SystemSettings
from .permissions import MANAGE_SYSTEM, capability_required


def _audit(request, config, message):
    LogEntry.objects.log_action(user_id=request.user.pk, content_type_id=ContentType.objects.get_for_model(SystemSettings).pk, object_id=config.pk, object_repr="Configuración del sistema", action_flag=CHANGE, change_message=message)


@capability_required(MANAGE_SYSTEM)
def system_settings(request):
    config = SystemSettings.load()
    form = SystemSettingsForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        changed = [str(form.fields[name].label) for name in form.changed_data]
        _audit(request, config, f"Configuración actualizada: {', '.join(changed)}." if changed else "Configuración guardada sin cambios.")
        messages.success(request, "Configuración guardada.")
        return redirect("system_settings")
    return render(request, "dashboard/system.html", {"form": form, "config": config, "backups": list_backups(config), "active_page": "system"})


@capability_required(MANAGE_SYSTEM)
def browse_folders(request):
    """Explorador de carpetas del servidor para elegir dónde guardar los respaldos."""
    try:
        return JsonResponse(list_folders(request.GET.get("path", "")))
    except BackupError as error:
        return JsonResponse({"error": str(error)}, status=400)


@require_POST
@capability_required(MANAGE_SYSTEM)
def test_backup_folder(request):
    ok, message = check_folder(request.POST.get("path", ""))
    return JsonResponse({"ok": ok, "message": message}, status=200 if ok else 400)


@require_POST
@capability_required(MANAGE_SYSTEM)
def backup_now(request):
    config = SystemSettings.load()
    ok, message = run_backup(config)
    _audit(request, config, f"Respaldo manual: {message}")
    (messages.success if ok else messages.error)(request, message)
    return redirect("system_settings")
