"""Pantalla de alertas y la campana de la barra superior."""
import threading
import time

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .alerts import evaluate_alerts, visible_alerts
from .permissions import MANAGE_SYSTEM, MONITOR_DOOR, capability_required

_EVALUATE_EVERY_SECONDS = 60
_last_evaluation = 0.0
_evaluation_lock = threading.Lock()


def _evaluate_if_stale():
    """Respaldo por si el hilo de tareas no corre (p. ej. en desarrollo): evalúa como mucho 1 vez/minuto."""
    global _last_evaluation
    if time.monotonic() - _last_evaluation < _EVALUATE_EVERY_SECONDS or not _evaluation_lock.acquire(blocking=False):
        return
    try:
        _last_evaluation = time.monotonic()
        evaluate_alerts()
    finally:
        _evaluation_lock.release()


def _serialize(alert):
    return {"id": alert.pk, "title": alert.title, "message": alert.message, "severity": alert.severity, "created": timezone.localtime(alert.created_at).strftime("%d/%m %H:%M")}


@capability_required(MONITOR_DOOR, MANAGE_SYSTEM)
def alert_list(request):
    alerts = visible_alerts(request.user)
    show = "resolved" if request.GET.get("show") == "resolved" else "open"
    if show == "open":
        items = alerts.filter(resolved_at__isnull=True).select_related("employee")
    else:
        items = alerts.filter(resolved_at__isnull=False, resolved_at__gte=timezone.now() - timezone.timedelta(days=7)).select_related("employee", "resolved_by")[:200]
    return render(request, "dashboard/alerts.html", {"active_page": "alerts", "alerts": items, "show": show, "open_count": alerts.filter(resolved_at__isnull=True).count()})


@capability_required(MONITOR_DOOR, MANAGE_SYSTEM)
def alert_summary(request):
    """Lo consulta la campana cada 30 s: número de alertas abiertas y las más recientes."""
    _evaluate_if_stale()
    open_alerts = visible_alerts(request.user).filter(resolved_at__isnull=True)
    return JsonResponse({"count": open_alerts.count(), "latest": [_serialize(alert) for alert in open_alerts[:5]]})


@require_POST
@capability_required(MONITOR_DOOR, MANAGE_SYSTEM)
def alert_resolve(request, pk=None):
    open_alerts = visible_alerts(request.user).filter(resolved_at__isnull=True)
    if pk is not None:
        open_alerts = open_alerts.filter(pk=pk)
        if not open_alerts.exists():
            raise Http404
    count = open_alerts.update(resolved_at=timezone.now(), resolved_by=request.user)
    messages.success(request, "Alerta marcada como atendida." if pk else f"{count} alerta{'s' if count != 1 else ''} marcada{'s' if count != 1 else ''} como atendida{'s' if count != 1 else ''}.")
    return redirect("alert_list")
