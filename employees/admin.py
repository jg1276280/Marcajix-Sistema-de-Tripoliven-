from django.contrib import admin

from .models import Department, Employee, Management, Position


@admin.register(Management)
class ManagementAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "management")
    list_filter = ("management",)
    search_fields = ("name", "management__name")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("name", "department")
    list_filter = ("department__management", "department")
    search_fields = ("name", "department__name")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "identification", "position", "status", "updated_at")
    list_filter = ("status", "position__department__management", "position__department")
    list_select_related = ("position",)
    search_fields = ("full_name", "identification", "hid_card_code", "position__name", "position__department__name")
    readonly_fields = ("created_at", "updated_at")
