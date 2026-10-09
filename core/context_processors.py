from .alerts import visible_alerts
from .permissions import ALL_CAPABILITIES, user_capabilities, user_role


def access(request):
    """Expone a las plantillas `access.<capacidad>` y `user_role` para mostrar solo lo permitido."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"access": {}, "user_role": None}
    granted = user_capabilities(user)
    alerts = visible_alerts(user)
    return {
        "access": {capability: capability in granted for capability in ALL_CAPABILITIES},
        "user_role": user_role(user),
        "can_see_alerts": alerts is not None,
        "open_alert_count": alerts.filter(resolved_at__isnull=True).count() if alerts is not None else 0,
    }
