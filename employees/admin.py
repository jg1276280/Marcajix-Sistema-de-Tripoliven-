from django.contrib import admin

from .models import Department, Employee, Management


@admin.register(Management)
class ManagementAdmin(admin.ModelAdmin):
    search_fields = ("name",)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "management")
    list_filter = ("management",)
    search_fields = ("name", "management__name")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "identification", "management", "department", "status", "updated_at")
    list_filter = ("status", "department", "management")
    search_fields = ("full_name", "identification", "hid_card_code", "department__name", "management__name")
    readonly_fields = ("created_at", "updated_at")
