import calendar
import re
from datetime import date

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
    name = models.CharField("Nombre", max_length=120)

    class Meta:
        db_table = "employees_department"
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("management", "name"), name="department_unique_per_management")]
        verbose_name = "Departamento"
        verbose_name_plural = "Departamentos"

    def __str__(self):
        return self.name


class Position(models.Model):
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="positions", verbose_name="Departamento")
    name = models.CharField("Nombre", max_length=120)

    class Meta:
        db_table = "employees_position"
        ordering = ("name",)
        constraints = [models.UniqueConstraint(fields=("department", "name"), name="position_unique_per_department")]
        verbose_name = "Cargo"
        verbose_name_plural = "Cargos"

    def __str__(self):
        return self.name


class EmployeeQuerySet(models.QuerySet):
    def with_structure(self):
        return self.select_related("position__department__management")


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

    full_name = models.CharField("Nombre y apellido", max_length=160)
    identification = models.CharField("Cédula / identificación", max_length=40, unique=True)
    hid_card_code = models.CharField("Código de tarjeta", max_length=80, unique=True, blank=True, null=True)
    position = models.ForeignKey(Position, on_delete=models.PROTECT, related_name="employees", verbose_name="Cargo")
    emergency_phone = models.CharField("Teléfono de contacto de emergencia", max_length=40, blank=True)
    emergency_contact_name = models.CharField("Nombre del contacto de emergencia", max_length=160, blank=True)
    photo = models.ImageField("Foto del empleado", upload_to="employees/%Y/%m/", blank=False)
    status = models.CharField("Estado", max_length=10, choices=STATUS_CHOICES, default=ACTIVE, db_index=True)
    birthday = models.DateField("Fecha de nacimiento", null=True, blank=True)
    hire_date = models.DateField("Fecha de ingreso", default=date.today)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EmployeeQuerySet.as_manager()

    class Meta:
        db_table = "employees_employee"
        ordering = ("full_name",)
        verbose_name = "Empleado"
        verbose_name_plural = "Empleados"

    def __str__(self):
        return self.full_name

    @property
    def department(self):
        return self.position.department if self.position_id else None

    @property
    def management(self):
        department = self.department
        return department.management if department else None

    def clean(self):
        super().clean()
        if not self.hire_date:
            raise ValidationError({"hire_date": "La fecha de ingreso es obligatoria."})
        if self.hire_date > date.today():
            raise ValidationError({"hire_date": "La fecha de ingreso no puede ser posterior a la fecha actual."})

        if self.hid_card_code is not None:
            self.hid_card_code = self.hid_card_code.strip().upper() or None
            if self.hid_card_code:
                if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_.]{1,79}", self.hid_card_code):
                    raise ValidationError({"hid_card_code": "El código de tarjeta solo admite letras, números, guiones y puntos."})
                if Employee.objects.filter(hid_card_code__iexact=self.hid_card_code).exclude(pk=self.pk).exists():
                    raise ValidationError({"hid_card_code": "Ya existe otro empleado con este código de tarjeta."})

        if self.emergency_phone:
            normalized_phone = re.sub(r"\s+", "", self.emergency_phone)
            if not re.fullmatch(r"\+?\d{8,15}", normalized_phone):
                raise ValidationError({"emergency_phone": "El teléfono de emergencia debe contener solo números y tener entre 8 y 15 dígitos."})
            self.emergency_phone = normalized_phone

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

    def celebration(self, on_date):
        """«birthday» si cumple años ese día, («anniversary», años) si cumple aniversario laboral, o None.

        Quien nació o ingresó un 29 de febrero lo celebra el 28 en los años no bisiestos.
        """
        def matches(day):
            if day is None:
                return False
            if (day.month, day.day) == (on_date.month, on_date.day):
                return True
            leap_day_in_common_year = (day.month, day.day) == (2, 29) and (on_date.month, on_date.day) == (2, 28)
            return leap_day_in_common_year and not calendar.isleap(on_date.year)

        if matches(self.birthday):
            return {"type": "birthday", "years": on_date.year - self.birthday.year}
        if matches(self.hire_date) and on_date.year > self.hire_date.year:
            return {"type": "anniversary", "years": on_date.year - self.hire_date.year}
        return None

    @property
    def has_important_history(self):
        return self.attendance_logs.exists() or self.security_events.exists()
