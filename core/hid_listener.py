import time

from django.db import close_old_connections
from django.utils import timezone

from employees.models import Employee

from .models import AttendanceLog, HIDReaderConfig, UnrecognizedAttendanceAttempt
from .services import AttendanceRegistrationError, broadcast_attendance_event, broadcast_kiosk_event, register_manual_entry


def listen_hid_reader(config=None):
    """Read newline-delimited card codes from the configured RS-232 reader."""
    try:
        import serial
    except ImportError as error:
        broadcast_kiosk_event("reader_error", {"port": getattr(config, "port", "desconocido")}, "Falta pyserial en el entorno de Marcajix. Instala las dependencias para activar el lector HID.")
        raise RuntimeError("pyserial no está instalado; no se puede iniciar el lector HID.") from error

    config = config or HIDReaderConfig.objects.get(pk=1)
    recent_reads = {}
    while config.is_active:
        reader = None
        try:
            reader = serial.Serial(port=config.port, baudrate=config.baud_rate, bytesize=config.data_bits, parity=config.parity, stopbits=config.stop_bits, timeout=config.timeout)
            broadcast_kiosk_event("reader_connected", {"port": config.port, "name": config.name}, "Lector conectado.")
            while config.is_active:
                close_old_connections()
                config.refresh_from_db()
                card_code = reader.readline().decode("utf-8", errors="ignore").strip()
                if not card_code:
                    continue
                now = time.monotonic()
                if now - recent_reads.get(card_code, 0) < 5:
                    broadcast_kiosk_event("attendance_duplicate", {"card_code": card_code}, "Lectura duplicada. Espere unos segundos.")
                    continue
                recent_reads[card_code] = now
                employee = Employee.objects.select_related("department").filter(hid_card_code__iexact=card_code).first()
                if employee is None:
                    UnrecognizedAttendanceAttempt.objects.create(hid_card_code=card_code, source=f"HID · {config.name}")
                    broadcast_kiosk_event("card_unrecognized", {"card_code": card_code}, "Tarjeta no reconocida.")
                    continue
                latest = employee.attendance_logs.order_by("-marked_at", "-pk").first()
                mark_type = AttendanceLog.EXIT if latest and latest.mark_type == AttendanceLog.ENTRY else AttendanceLog.ENTRY
                try:
                    log = register_manual_entry(employee.pk, timezone.now(), mark_type, source=f"HID · {config.name}", capture_mode=AttendanceLog.HID)
                except AttendanceRegistrationError as error:
                    broadcast_kiosk_event("attendance_rejected", {"employee": employee.full_name, "reason": str(error)}, str(error))
                    continue
                broadcast_attendance_event(log)
        except (serial.SerialException, ValueError) as error:
            broadcast_kiosk_event("reader_error", {"port": config.port}, f"No se puede abrir {config.port}: {error}")
            time.sleep(5)
            config.refresh_from_db()
        finally:
            if reader is not None:
                reader.close()