from datetime import time

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


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
    # Estado que escribe el proceso del lector (manage.py listen_hid) para que el kiosco y el monitor lo muestren.
    STATUS_CONNECTED = "connected"
    STATUS_ERROR = "error"
    STATUS_STOPPED = "stopped"
    STATUSES = ((STATUS_CONNECTED, "Conectado"), (STATUS_ERROR, "Con error"), (STATUS_STOPPED, "Detenido"))
    HEARTBEAT_TIMEOUT_SECONDS = 60
    status = models.CharField("Estado del lector", max_length=10, choices=STATUSES, default=STATUS_STOPPED)
    status_message = models.CharField("Detalle del estado", max_length=255, blank=True)
    last_seen_at = models.DateTimeField("Última señal del lector", null=True, blank=True)

    class Meta:
        db_table = "core_hid_reader_config"
        verbose_name = "Configuración de lector HID"
        verbose_name_plural = "Configuración de lectores HID"

    def __str__(self):
        return self.name

    @property
    def is_online(self):
        """El lector está en línea si informó conexión hace menos de HEARTBEAT_TIMEOUT_SECONDS."""
        return self.status == self.STATUS_CONNECTED and self.last_seen_at is not None and (timezone.now() - self.last_seen_at).total_seconds() < self.HEARTBEAT_TIMEOUT_SECONDS


class UserSecurity(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="security")
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField("Bloqueada hasta", null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Security for {self.user.username}"


class ValidAttendanceManager(models.Manager):
    """Por defecto se excluyen los marcajes anulados: no cuentan para horas, presencia ni reportes."""

    def get_queryset(self):
        return super().get_queryset().filter(voided_at__isnull=True)


class AttendanceLog(models.Model):
    ENTRY = "entry"
    EXIT = "exit"
    MARK_TYPES = ((ENTRY, "Entrada"), (EXIT, "Salida"))
    HID = "hid"
    MANUAL = "manual"
    CORRECTION = "correction"
    CAPTURE_MODES = ((HID, "Lector HID"), (MANUAL, "Registro manual"), (CORRECTION, "Corrección de RRHH"))

    # El índice compuesto attendance_latest_idx ya cubre las búsquedas por empleado.
    employee = models.ForeignKey("employees.Employee", on_delete=models.PROTECT, related_name="attendance_logs", db_index=False)
    marked_at = models.DateTimeField("Fecha y hora del marcaje")
    mark_type = models.CharField("Tipo de marcaje", max_length=10, choices=MARK_TYPES)
    source = models.CharField("Origen / dispositivo", max_length=120, default="Registro manual")
    capture_mode = models.CharField("Modo de captura", max_length=10, choices=CAPTURE_MODES, default=MANUAL)
    registered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="attendance_registrations")
    correction_reason = models.CharField("Motivo de la corrección", max_length=255, blank=True)
    # Anulación lógica: el marcaje original se conserva para la auditoría.
    voided_at = models.DateTimeField("Anulado el", null=True, blank=True)
    voided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="voided_attendance_logs")
    void_reason = models.CharField("Motivo de la anulación", max_length=255, blank=True)

    objects = ValidAttendanceManager()
    all_objects = models.Manager()

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


class SystemSettings(models.Model):
    """Configuración general editable desde la interfaz por el rol Sistemas (registro único)."""

    backup_enabled = models.BooleanField("Respaldos automáticos activos", default=False)
    backup_path = models.CharField("Carpeta de respaldos", max_length=400, blank=True, help_text="Ruta local o de red, p. ej. \\\\SERVIDOR\\Respaldos\\Marcajix")
    backup_time = models.TimeField("Hora del respaldo diario", default=time(23, 0))
    backup_retention_days = models.PositiveSmallIntegerField("Conservar respaldos (días)", default=30)
    last_backup_attempt_at = models.DateTimeField("Último intento de respaldo", null=True, blank=True)
    last_backup_ok_at = models.DateTimeField("Último respaldo correcto", null=True, blank=True)
    last_backup_status = models.CharField("Estado del último respaldo", max_length=10, blank=True)
    last_backup_message = models.CharField("Detalle del último respaldo", max_length=500, blank=True)
    last_backup_file = models.CharField("Último archivo de respaldo", max_length=500, blank=True)

    allow_attendance_corrections = models.BooleanField("Permitir correcciones de marcajes", default=False)

    class Meta:
        db_table = "core_system_settings"
        verbose_name = "Configuración del sistema"
        verbose_name_plural = "Configuración del sistema"

    def __str__(self):
        return "Configuración del sistema"

    @classmethod
    def load(cls):
        settings_obj, _ = cls.objects.get_or_create(pk=1)
        return settings_obj


class Alert(models.Model):
    """Aviso que requiere atención. `key` evita duplicados mientras la alerta sigue abierta."""

    DOOR = "door"
    SYSTEM = "system"
    AUDIENCES = ((DOOR, "Garita"), (SYSTEM, "Sistema"))
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    SEVERITIES = ((INFO, "Información"), (WARNING, "Advertencia"), (CRITICAL, "Crítica"))

    key = models.CharField(max_length=120, db_index=True)
    kind = models.CharField("Tipo", max_length=30)
    audience = models.CharField("Para", max_length=10, choices=AUDIENCES)
    severity = models.CharField("Gravedad", max_length=10, choices=SEVERITIES, default=WARNING)
    title = models.CharField("Título", max_length=160)
    message = models.CharField("Detalle", max_length=500, blank=True)
    employee = models.ForeignKey("employees.Employee", on_delete=models.SET_NULL, null=True, blank=True, related_name="alerts")
    created_at = models.DateTimeField("Fecha", auto_now_add=True)
    resolved_at = models.DateTimeField("Resuelta", null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_alerts")
    auto_resolved = models.BooleanField(default=False)

    class Meta:
        db_table = "core_alert"
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=("resolved_at", "audience"), name="alert_open_idx")]
        verbose_name = "Alerta"
        verbose_name_plural = "Alertas"

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.resolved_at is None
