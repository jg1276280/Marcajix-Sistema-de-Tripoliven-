import re
from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


class Management(models.Model):
    name = models.CharField("Nombre", max_length=120, unique=True)

    class Meta:
        db_table = "employees_management"
        ordering = ("name",)
        verbose_name = "Gerencia"
        verbose_name_plural = "Gerencias"

    def __str__(self):
        return self.name


class Department(models.Model):
    management = models.ForeignKey(Management, on_delete=models.PROTECT, related_name="departments", verbose_name="Gerencia")
    name = models.CharField("Nombre", max_length=120, unique=True)

    class Meta:
        db_table = "employees_department"
        ordering = ("name",)
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"

    def __str__(self):
        return self.name


class Employee(models.Model):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RETIRED = "retired"
    VACATION = "vacation"
    SUSPENDED = "suspended"
    STATUS_CHOICES = (
        (ACTIVE, "Activo"),
        (INACTIVE, "Inactivo"),
        (RETIRED, "Retirado"),
        (VACATION, "Vacaciones"),
        (SUSPENDED, "Suspendido"),
    )
    ACCESS_ALLOWED_STATUSES = (ACTIVE, VACATION)
    ACCESS_ALERT_STATUSES = (VACATION,)

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="employee_profile")
    full_name = models.CharField("Nombre y apellido", max_length=160)
    identification = models.CharField("Cédula / identificación", max_length=40, unique=True)
    hid_card_code = models.CharField("Código de tarjeta", max_length=80, unique=True, db_index=True, blank=True, null=True)
    position = models.CharField("Cargo / puesto", max_length=120)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="employees", verbose_name="Departamento")
    management = models.ForeignKey(Management, on_delete=models.PROTECT, related_name="employees", verbose_name="Gerencia")
    emergency_phone = models.CharField("Teléfono de contacto de emergencia", max_length=40, blank=True)
    emergency_contact_name = models.CharField("Nombre del contacto de emergencia", max_length=160, blank=True)
    photo = models.ImageField("Foto del empleado", upload_to="employees/%Y/%m/", blank=False)
    status = models.CharField("Estado", max_length=10, choices=STATUS_CHOICES, default=ACTIVE, db_index=True)
    birthday = models.DateField("Fecha de nacimiento", null=True, blank=True)
    hire_date = models.DateField("Fecha de ingreso", default=date.today)
    workday_hours = models.DecimalField("Horas de jornada", max_digits=4, decimal_places=2, default=9)
    punctuality_tolerance_minutes = models.PositiveSmallIntegerField("Tolerancia de puntualidad (minutos)", default=15, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "employees_employee"
        ordering = ("full_name",)
        verbose_name = "Empleado"
        verbose_name_plural = "Empleados"

    def __str__(self):
        return self.full_name

    def clean(self):
        super().clean()
        if not self.hire_date:
            raise ValidationError({"hire_date": "La fecha de ingreso es obligatoria."})
        if self.hire_date > date.today():
            raise ValidationError({"hire_date": "La fecha de ingreso no puede ser posterior a la fecha actual."})

        if self.hid_card_code is not None:
            self.hid_card_code = self.hid_card_code.strip()
            if not self.hid_card_code:
                self.hid_card_code = None
            else:
                normalized = self.hid_card_code.upper()
                if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_.]{1,79}", normalized):
                    raise ValidationError({"hid_card_code": "El código de tarjeta solo admite letras, números, guiones y puntos."})
                if Employee.objects.filter(hid_card_code__iexact=normalized).exclude(pk=self.pk).exists():
                    raise ValidationError({"hid_card_code": "Ya existe otro empleado con este código de tarjeta."})
                self.hid_card_code = normalized

        if self.emergency_phone:
            normalized_phone = re.sub(r"\s+", "", self.emergency_phone)
            if not re.fullmatch(r"\+?\d{8,15}", normalized_phone):
                raise ValidationError({"emergency_phone": "El teléfono de emergencia debe contener solo números y tener entre 8 y 15 dígitos."})
            self.emergency_phone = normalized_phone

        if self.department_id and self.management_id and self.department.management_id != self.management_id:
            raise ValidationError({"department": "El departamento no pertenece a la gerencia seleccionada."})

        if self.workday_hours in (None, ""):
            self.workday_hours = 9
        if self.punctuality_tolerance_minutes in (None, ""):
            self.punctuality_tolerance_minutes = 15

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def access_level(self):
        if self.status in self.ACCESS_ALERT_STATUSES:
            return "alert"
        if self.status in self.ACCESS_ALLOWED_STATUSES:
            return "allowed"
        return "denied"

    @property
    def access_message(self):
        messages = {
            self.ACTIVE: "Acceso permitido.",
            self.VACATION: "Acceso permitido con alerta: el empleado está de vacaciones.",
            self.INACTIVE: "Acceso denegado: empleado inactivo.",
            self.RETIRED: "Acceso denegado: empleado retirado.",
            self.SUSPENDED: "Acceso denegado: empleado suspendido.",
        }
        return messages[self.status]

    @property
    def has_important_history(self):
        return self.attendance_logs.exists() or self.security_alerts.exists()
