from django.urls import path

from . import views

app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("nuevo/", views.employee_create, name="create"),
    path("<int:pk>/editar/", views.employee_edit, name="edit"),
    path("<int:pk>/estado/", views.employee_toggle_status, name="toggle_status"),
    path("<int:pk>/eliminar/", views.employee_delete, name="delete"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("estructura/", views.structure_settings, name="structure"),
]