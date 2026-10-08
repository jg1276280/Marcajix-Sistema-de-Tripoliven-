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
    locked_until = models.DateTimeField("Bloqueada hasta", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Security for {self.user.username}"


class AttendanceLog(models.Model):
    ENTRY = "entry"
    EXIT = "exit"
    MARK_TYPES = ((ENTRY, "Entrada"), (EXIT, "Salida"))
    HID = "hid"
    MANUAL = "manual"
    CAPTURE_MODES = ((HID, "Lector HID"), (MANUAL, "Registro manual"))

    # El índice compuesto attendance_latest_idx ya cubre las búsquedas por empleado.
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="attendance_logs", db_index=False)
    marked_at = models.DateTimeField("Fecha y hora del marcaje")
    mark_type = models.CharField("Tipo de marcaje", max_length=10, choices=MARK_TYPES)
    source = models.CharField("Origen / dispositivo", max_length=120, default="Registro manual")
    capture_mode = models.CharField("Modo de captura", max_length=10, choices=CAPTURE_MODES, default=MANUAL)
    registered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance_registrations")

    class Meta:
        db_table = "core_attendance_log"
        ordering = ("-marked_at",)
        indexes = [
            models.Index(fields=("marked_at",), name="attendance_time_idx"),
            models.Index(fields=("employee", "-marked_at", "-id"), name="attendance_latest_idx"),
        ]
        verbose_name = "Registro de marcaje"
        verbose_name_plural = "Registros de marcaje"

    def __str__(self):
        return f"{self.employee} - {self.marked_at:%Y-%m-%d %H:%M:%S}"


class SecurityEvent(models.Model):
    """Lectura o intento de marcaje rechazado: tarjeta desconocida o empleado sin acceso."""

    UNKNOWN_CARD = "unknown_card"
    BLOCKED_EMPLOYEE = "blocked_employee"
    EVENT_TYPES = ((UNKNOWN_CARD, "Tarjeta no reconocida"), (BLOCKED_EMPLOYEE, "Empleado sin acceso"))

    event_type = models.CharField("Tipo de evento", max_length=20, choices=EVENT_TYPES)
    employee = models.ForeignKey("employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="security_events")
    employee_status = models.CharField("Estatus del empleado", max_length=10, blank=True)
    hid_card_code = models.CharField("Código de tarjeta leído", max_length=80, blank=True)
    mark_type = models.CharField("Tipo solicitado", max_length=10, choices=AttendanceLog.MARK_TYPES, blank=True)
    reason = models.CharField("Motivo", max_length=255)
    source = models.CharField("Origen / dispositivo", max_length=120)
    attempted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="security_events")
    occurred_at = models.DateTimeField("Fecha y hora", auto_now_add=True)

    class Meta:
        db_table = "core_security_event"
        ordering = ("-occurred_at", "-pk")
        indexes = [models.Index(fields=("occurred_at",), name="security_event_time_idx")]
        verbose_name = "Evento de seguridad"
        verbose_name_plural = "Eventos de seguridad"

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.employee or self.hid_card_code}"
