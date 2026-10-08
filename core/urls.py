from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="auth/login.html", authentication_form=LoginForm), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("registro/", views.register, name="register"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/dispositivos/", views.device_config_view, name="device_config"),
    path("dashboard/dispositivos/probar/", views.device_config_test, name="device_config_test"),
    path("dashboard/dispositivos/leer/", views.device_read_test, name="device_read_test"),
    path("kiosk/garita/", views.kiosk_garita, name="kiosk_garita"),
    path("kiosk/garita/desbloquear/", views.kiosk_unlock, name="kiosk_unlock"),
    path("dashboard/perfil/", views.profile, name="profile"),
    path("dashboard/perfil/contrasena/", views.profile_password, name="profile_password"),
    path("dashboard/usuarios/", views.user_list, name="user_list"),
    path("dashboard/usuarios/nuevo/", views.user_create, name="user_create"),
    path("dashboard/usuarios/<int:pk>/editar/", views.user_edit, name="user_edit"),
    path("dashboard/usuarios/<int:pk>/eliminar/", views.user_delete, name="user_delete"),
    path("dashboard/historial/", views.audit_log, name="audit_log"),
    path("dashboard/marcajes/", views.attendance_monitor, name="attendance_monitor"),
    path("dashboard/marcajes/registrar/", views.attendance_register, name="attendance_register"),
    path("dashboard/marcajes/empleados/", views.attendance_employee_search, name="attendance_employee_search"),
    path("dashboard/marcajes/historial/", views.attendance_history, name="attendance_history"),
]
