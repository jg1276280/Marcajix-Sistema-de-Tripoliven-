from django.contrib import admin
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import include, path, re_path
from django.views.static import serve

from core.permissions import is_display_client


def protected_media(request, path):
    if not (request.user.is_authenticated or is_display_client(request)):
        return redirect_to_login(request.get_full_path())
    return serve(request, path, document_root=settings.MEDIA_ROOT)


# El admin de Django salta el control por roles: queda reservado a superusuarios.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("dashboard/empleados/", include("employees.urls")),
    # Las fotos de los empleados son datos personales: solo para usuarios autenticados y la pantalla de garita.
    re_path(r"^media/(?P<path>.+)$", protected_media, name="protected_media"),
]
