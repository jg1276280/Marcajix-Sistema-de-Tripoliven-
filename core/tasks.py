"""Tareas periódicas en segundo plano: respaldos programados y evaluación de alertas.

Corren en un hilo del proceso del servidor web, solo cuando la variable de entorno
MARCAJIX_BACKGROUND_TASKS=1 está activa (la pone scripts/servicio.bat al arrancar el servidor).
Así no se ejecutan durante migraciones, pruebas ni otros comandos de manage.py.
"""
import logging
import os
import threading
import time

from django.db import close_old_connections

logger = logging.getLogger("marcajix.tasks")
INTERVAL_SECONDS = 60
_started = False


def run_once():
    from .alerts import evaluate_alerts
    from .backups import backup_is_due, run_backup
    from .models import SystemSettings

    config = SystemSettings.load()
    if backup_is_due(config):
        run_backup(config)
    evaluate_alerts()


def _loop():
    time.sleep(10)  # Deja que el servidor termine de arrancar.
    while True:
        close_old_connections()
        try:
            run_once()
        except Exception:  # Un fallo puntual (p. ej. la BD reiniciándose) no debe detener las tareas.
            logger.exception("Error en las tareas en segundo plano")
        finally:
            close_old_connections()
        time.sleep(INTERVAL_SECONDS)


def start_background_tasks():
    global _started
    if _started or os.environ.get("MARCAJIX_BACKGROUND_TASKS") != "1":
        return
    _started = True
    threading.Thread(target=_loop, name="marcajix-tareas", daemon=True).start()
    logger.info("Tareas en segundo plano iniciadas")
