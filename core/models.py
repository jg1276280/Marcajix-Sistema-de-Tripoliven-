from django.contrib.auth.models import User
from django.db import models


class HIDReaderConfig(models.Model):
    BAUD_RATE_CHOICES = [(rate, str(rate)) for rate in (1200, 2400, 4800, 9600, 19200)]
    DATA_BITS_CHOICES = [(7, "7"), (8, "8")]
    PARITY_CHOICES = [("N", "N / Ninguna"), ("E", "E / Par"), ("O", "O / Impar")]
    STOP_BITS_CHOICES = [(1, "1"), (2, "2")]

    name = models.CharField("Nombre", max_length=120, default="Garita Principal")
    port = models.CharField("Puerto", max_length=80, default="COM3", help_text="COM1, COM3 en Windows o /dev/ttyUSB0 en Linux")
    baud_rate = models.IntegerField("Velocidad", choices=BAUD_RATE_CHOICES, default=9600)
    data_bits = models.IntegerField("Bits de datos", choices=DATA_BITS_CHOICES, default=8)
    parity = models.CharField("Paridad", max_length=1, choices=PARITY_CHOICES, default="N")
    stop_bits = models.IntegerField("Bits de parada", choices=STOP_BITS_CHOICES, default=1)
    timeout = models.FloatField("Tiempo de espera (s)", default=1.0)
    wiegand_format = models.CharField("Formato Wiegand", max_length=60, default="Wiegand 26-bit")
    is_active = models.BooleanField("Lector activo", default=True)

    class Meta:
        db_table = "core_hid_reader_config"
        verbose_name = "Configuración de lector HID"
        verbose_name_plural = "Configuración de lectores HID"

    def __str__(self):
        return self.name


class UserSecurity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="security")
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Security for {self.user.username}"


class AttendanceLog(models.Model):
    ENTRY = "entry"
    EXIT = "exit"
    AUTO = "auto"
    MARK_TYPES = ((ENTRY, "Entrada"), (EXIT, "Salida"), (AUTO, "Auto / Sugerido"))
    SESSION_COMPLETE = "complete"
    SESSION_INCOMPLETE = "incomplete"
    SESSION_ORPHAN = "orphan"
    SESSION_STATUSES = ((SESSION_COMPLETE, "Completa"), (SESSION_INCOMPLETE, "Incompleta"), (SESSION_ORPHAN, "Huérfana"))
    HID = "hid"
    MANUAL = "manual"
    CAPTURE_MODES = ((HID, "Lector HID"), (MANUAL, "Registro manual"))

    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="attendance_logs")
    hid_card_code = models.CharField("Código legado", max_length=80, db_index=True, blank=True, null=True)
    marked_at = models.DateTimeField("Fecha y hora del marcaje")
    mark_type = models.CharField("Tipo de marcaje", max_length=10, choices=MARK_TYPES, default=AUTO)
    session_status = models.CharField("Estado de la sesión", max_length=15, choices=SESSION_STATUSES, default=SESSION_COMPLETE, db_index=True)
    source = models.CharField("Origen / dispositivo", max_length=120, default="Web")
    capture_mode = models.CharField("Modo de captura", max_length=10, choices=CAPTURE_MODES, default=MANUAL)
    registered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance_registrations")

    class Meta:
        db_table = "core_attendance_log"
        ordering = ("-marked_at",)
        indexes = [
            models.Index(fields=("marked_at",), name="attendance_time_idx"),
            models.Index(fields=("employee",), name="attendance_employee_idx"),
            models.Index(fields=("employee", "-marked_at", "-id"), name="attendance_latest_idx"),
            models.Index(fields=("employee", "session_status"), name="attendance_session_status_idx"),
        ]
        verbose_name = "Registro de marcaje"
        verbose_name_plural = "Registros de marcaje"

    def __str__(self):
        return f"{self.employee} - {self.marked_at:%Y-%m-%d %H:%M:%S}"


class AttendanceAttempt(models.Model):
    BLOCKED = "blocked"
    STATUSES = ((BLOCKED, "Bloqueado"),)

    employee = models.ForeignKey("employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance_attempts")
    attempted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance_attempts")
    employee_status = models.CharField("Estatus del empleado", max_length=20)
    mark_type = models.CharField("Tipo solicitado", max_length=10, choices=((AttendanceLog.ENTRY, "Entrada"), (AttendanceLog.EXIT, "Salida")))
    status = models.CharField("Estado del intento", max_length=20, choices=STATUSES, default=BLOCKED)
    reason = models.CharField("Motivo", max_length=255)
    source = models.CharField("Origen / dispositivo", max_length=120, default="Registro manual")
    attempted_at = models.DateTimeField("Fecha y hora", auto_now_add=True)

    class Meta:
        db_table = "core_attendance_attempt"
        ordering = ("-attempted_at", "-pk")
        indexes = [models.Index(fields=("attempted_at",), name="attendance_attempted_time_idx"), models.Index(fields=("status",), name="attendance_attempt_status_idx")]
        verbose_name = "Intento de marcaje"
        verbose_name_plural = "Intentos de marcaje"

    def __str__(self):
        return f"{self.employee or 'Empleado eliminado'} - {self.get_status_display()}"


class UnrecognizedAttendanceAttempt(models.Model):
    hid_card_code = models.CharField("Código HID leído", max_length=80, db_index=True)
    attempted_at = models.DateTimeField("Fecha y hora del intento", auto_now_add=True)
    source = models.CharField("Origen / dispositivo", max_length=120, default="Web")

    class Meta:
        db_table = "core_unrecognized_attendance_attempt"
        ordering = ("-attempted_at",)
        indexes = [models.Index(fields=("attempted_at",), name="attendance_attempt_time_idx")]
        verbose_name = "Intento de marcaje no reconocido"
        verbose_name_plural = "Intentos de marcaje no reconocidos"


class SecurityAlert(models.Model):
    INACTIVE_EMPLOYEE = "inactive_employee"
    UNKNOWN_CARD = "unknown_card"
    ALERT_TYPES = ((INACTIVE_EMPLOYEE, "Empleado inactivo"), (UNKNOWN_CARD, "Tarjeta no reconocida"))

    employee = models.ForeignKey("employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_alerts")
    hid_card_code = models.CharField("Código HID leído", max_length=80, db_index=True)
    occurred_at = models.DateTimeField("Fecha y hora", auto_now_add=True)
    source = models.CharField("Origen / dispositivo", max_length=120, default="Web")
    alert_type = models.CharField("Tipo de alerta", max_length=30, choices=ALERT_TYPES)
    reason = models.CharField("Motivo", max_length=255)

    class Meta:
        db_table = "core_security_alert"
        ordering = ("-occurred_at",)
        indexes = [models.Index(fields=("occurred_at",), name="security_alert_time_idx"), models.Index(fields=("alert_type",), name="security_alert_type_idx")]
        verbose_name = "Alerta de seguridad"
        verbose_name_plural = "Alertas de seguridad"