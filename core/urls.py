from django.contrib.auth import views as auth_views
from django.urls import path

from . import alert_views, live, reports, system_views, views
from .forms import LoginForm

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="auth/login.html", authentication_form=LoginForm, redirect_authenticated_user=True), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/dispositivos/", views.device_config_view, name="device_config"),
    path("dashboard/dispositivos/probar/", views.device_config_test, name="device_config_test"),
    path("dashboard/dispositivos/leer/", views.device_read_test, name="device_read_test"),
    path("kiosco/", live.kiosk_display, name="kiosk_display"),
    path("kiosco/eventos/", live.live_feed, name="live_feed"),
    path("dashboard/perfil/", views.profile, name="profile"),
    path("dashboard/perfil/contrasena/", views.profile_password, name="profile_password"),
    path("dashboard/usuarios/", views.user_list, name="user_list"),
    path("dashboard/usuarios/nuevo/", views.user_create, name="user_create"),
    path("dashboard/usuarios/<int:pk>/editar/", views.user_edit, name="user_edit"),
    path("dashboard/usuarios/<int:pk>/eliminar/", views.user_delete, name="user_delete"),
    path("dashboard/historial/", views.audit_log, name="audit_log"),
    path("dashboard/sistema/", system_views.system_settings, name="system_settings"),
    path("dashboard/sistema/carpetas/", system_views.browse_folders, name="browse_folders"),
    path("dashboard/sistema/probar-carpeta/", system_views.test_backup_folder, name="test_backup_folder"),
    path("dashboard/sistema/respaldar/", system_views.backup_now, name="backup_now"),
    path("dashboard/marcajes/", views.attendance_monitor, name="attendance_monitor"),
    path("dashboard/presencia/", views.presence, name="presence"),
    path("dashboard/alertas/", alert_views.alert_list, name="alert_list"),
    path("dashboard/alertas/resumen/", alert_views.alert_summary, name="alert_summary"),
    path("dashboard/alertas/atender/", alert_views.alert_resolve, name="alert_resolve_all"),
    path("dashboard/alertas/<int:pk>/atender/", alert_views.alert_resolve, name="alert_resolve"),
    path("dashboard/marcajes/registrar/", views.attendance_register, name="attendance_register"),
    path("dashboard/marcajes/empleados/", views.attendance_employee_search, name="attendance_employee_search"),
    path("dashboard/marcajes/historial/", views.attendance_history, name="attendance_history"),
    path("dashboard/reportes/", reports.attendance_report, name="attendance_report"),
    path("dashboard/reportes/exportar/", reports.attendance_report_export, name="attendance_report_export"),
]
