from .permissions import ALL_CAPABILITIES, user_capabilities, user_role


def access(request):
    """Expone a las plantillas `access.<capacidad>` y `user_role` para mostrar solo lo permitido."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"access": {}, "user_role": None}
    granted = user_capabilities(user)
    return {"access": {capability: capability in granted for capability in ALL_CAPABILITIES}, "user_role": user_role(user)}
