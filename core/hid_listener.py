import logging
import time

from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from employees.models import Employee

from .models import AttendanceLog, HIDReaderConfig
from .services import AttendanceRegistrationError, next_mark_type, record_unknown_card, register_attendance

logger = logging.getLogger("marcajix.hid")

DUPLICATE_READ_SECONDS = 5
HEARTBEAT_SECONDS = 15
RETRY_SECONDS = 5


def _serial_settings(config):
    return (config.port, config.baud_rate, config.data_bits, config.parity, config.stop_bits, config.timeout)


def _report(config, status, message=""):
    """Guarda el estado del lector en la BD: el kiosco y el monitor lo leen desde ahí."""
    try:
        HIDReaderConfig.objects.filter(pk=config.pk).update(status=status, status_message=message[:255], last_seen_at=timezone.now())
    except DatabaseError:
        logger.exception("No se pudo guardar el estado del lector")


def process_card(card_code, source):
    """Registra una lectura. Devuelve el marcaje, o None si se rechazó (queda como evento de seguridad)."""
    employee = Employee.objects.filter(hid_card_code__iexact=card_code).first()
    if employee is None:
        record_unknown_card(card_code, source)
        logger.warning("Tarjeta no reconocida: %s", card_code)
        return None
    try:
        log = register_attendance(employee.pk, timezone.now(), next_mark_type(employee), source=source, capture_mode=AttendanceLog.HID)
    except AttendanceRegistrationError as error:
        logger.warning("Marcaje rechazado para %s: %s", employee.full_name, error)
        return None
    logger.info("%s: %s", log.get_mark_type_display(), employee.full_name)
    return log


def listen_hid_reader(config):
    """Lee códigos de tarjeta (uno por línea) del lector RS-232 y los registra. No termina nunca."""
    try:
        import serial
    except ImportError as error:
        raise RuntimeError("pyserial no está instalado; no se puede iniciar el lector HID.") from error

    recent_reads = {}
    while True:
        try:
            close_old_connections()
            config.refresh_from_db()
        except DatabaseError:
            logger.exception("Sin conexión con la base de datos; reintentando")
            time.sleep(RETRY_SECONDS)
            continue
        if not config.is_active:
            _report(config, HIDReaderConfig.STATUS_STOPPED, "Lector desactivado en la configuración.")
            time.sleep(RETRY_SECONDS)
            continue

        source = f"HID · {config.name}"
        connected_with = _serial_settings(config)
        reader = None
        try:
            reader = serial.Serial(port=config.port, baudrate=config.baud_rate, bytesize=config.data_bits, parity=config.parity, stopbits=config.stop_bits, timeout=config.timeout)
            logger.info("Lector conectado en %s", config.port)
            _report(config, HIDReaderConfig.STATUS_CONNECTED, f"Escuchando en {config.port}.")
            last_heartbeat = time.monotonic()
            while True:
                card_code = reader.readline().decode("utf-8", errors="ignore").strip()
                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    close_old_connections()
                    config.refresh_from_db()
                    if not config.is_active or _serial_settings(config) != connected_with:
                        logger.info("La configuración del lector cambió; reconectando")
                        break
                    _report(config, HIDReaderConfig.STATUS_CONNECTED, f"Escuchando en {config.port}.")
                    recent_reads = {code: seen for code, seen in recent_reads.items() if now - seen < DUPLICATE_READ_SECONDS}
                    last_heartbeat = now
                if not card_code or now - recent_reads.get(card_code, 0) < DUPLICATE_READ_SECONDS:
                    continue
                recent_reads[card_code] = now
                close_old_connections()
                process_card(card_code, source)
        except (serial.SerialException, ValueError) as error:
            logger.error("No se puede usar %s: %s", config.port, error)
            _report(config, HIDReaderConfig.STATUS_ERROR, f"No se puede abrir {config.port}: {error}")
            time.sleep(RETRY_SECONDS)
        except DatabaseError:
            logger.exception("Error de base de datos procesando una lectura; reintentando")
            time.sleep(RETRY_SECONDS)
        finally:
            if reader is not None:
                reader.close()