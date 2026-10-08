from django.contrib import admin
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.static import serve

# El admin de Django salta el control por roles: queda reservado a superusuarios.
admin.site.has_permission = lambda request: request.user.is_active and request.user.is_superuser

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("dashboard/empleados/", include("employees.urls")),
    # Las fotos de los empleados son datos personales: solo se sirven a usuarios autenticados.
    re_path(r"^media/(?P<path>.+)$", login_required(lambda request, path: serve(request, path, document_root=settings.MEDIA_ROOT)), name="protected_media"),
]
