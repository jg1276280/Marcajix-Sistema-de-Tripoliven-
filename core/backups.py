"""Respaldos de la base de datos de SQL Server en una carpeta local o de red.

Cómo se hace:
- SQL Server en esta PC: el archivo .bak se genera primero en una carpeta intermedia
  (BACKUP_STAGING_DIR, creada por el instalador con permisos para SQL Server y para Marcajix) y
  luego Marcajix lo copia a la carpeta elegida. Así funciona aunque la cuenta del servicio de
  SQL Server no tenga acceso a la red.
- SQL Server en otro servidor: el .bak se escribe directamente en la carpeta elegida, que debe
  ser una ruta de red (\\\\SERVIDOR\\Carpeta) donde la cuenta del servicio de SQL Server pueda escribir.
"""
import glob
import logging
import os
import shutil
import threading
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from . import sqlserver
from .models import SystemSettings

logger = logging.getLogger("marcajix.backups")
_lock = threading.Lock()


class BackupError(Exception):
    pass


def check_folder(path):
    """Comprueba que la carpeta existe y que Marcajix puede escribir en ella. Devuelve (ok, mensaje)."""
    path = (path or "").strip()
    if not path:
        return False, "Indique una carpeta."
    if not os.path.isdir(path):
        return False, "La carpeta no existe o no es accesible desde el servidor de Marcajix."
    probe = os.path.join(path, ".marcajix-prueba.tmp")
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
        os.remove(probe)
    except OSError as error:
        return False, f"No se puede escribir en la carpeta: {error.strerror or error}"
    return True, "La carpeta es accesible y se puede escribir en ella."


def _server_backup_directory(cursor):
    """Carpeta de respaldos por defecto de la instancia de SQL Server."""
    cursor.execute("SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000))")
    row = cursor.fetchone()
    if row and row[0]:
        return row[0]
    cursor.execute("DECLARE @dir nvarchar(4000); EXEC master.dbo.xp_instance_regread N'HKEY_LOCAL_MACHINE', N'Software\\Microsoft\\MSSQLServer\\MSSQLServer', N'BackupDirectory', @dir OUTPUT; SELECT @dir")
    row = cursor.fetchone()
    if row and row[0]:
        return row[0]
    raise BackupError("No se pudo determinar la carpeta de respaldos de SQL Server.")


def _backup_database(destination_folder, filename):
    """Genera el .bak y lo deja en la carpeta destino. Devuelve la ruta final."""
    database = sqlserver.database_name()
    connection = sqlserver.connect(timeout=30)
    try:
        cursor = connection.cursor()
        if sqlserver.is_local_server():
            # Preferimos la carpeta intermedia de Marcajix: la carpeta propia de SQL Server suele estar
            # en Program Files y la cuenta que ejecuta Marcajix puede no tener permiso para leerla.
            staging_dir = settings.BACKUP_STAGING_DIR if settings.BACKUP_STAGING_DIR and os.path.isdir(settings.BACKUP_STAGING_DIR) else _server_backup_directory(cursor)
            staging = os.path.join(staging_dir, filename)
        else:
            staging = os.path.join(destination_folder, filename)
        sql = f"DECLARE @path nvarchar(4000) = ?; BACKUP DATABASE [{database}] TO DISK = @path WITH COPY_ONLY, INIT, CHECKSUM, NAME = N'Marcajix'"
        sqlserver.run_to_completion(cursor, sql, staging)
    finally:
        connection.close()
    final = os.path.join(destination_folder, filename)
    if os.path.normcase(os.path.abspath(staging)) != os.path.normcase(os.path.abspath(final)):
        shutil.copy2(staging, final)
        os.remove(staging)
    if not os.path.isfile(final) or os.path.getsize(final) == 0:
        raise BackupError("SQL Server terminó, pero el archivo de respaldo no aparece en la carpeta destino.")
    return final


def _prune(folder, prefix, retention_days):
    """Borra respaldos de Marcajix más antiguos que la retención. Nunca toca otros archivos."""
    limit = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for path in glob.glob(os.path.join(folder, f"{prefix}*.bak")):
        if datetime.fromtimestamp(os.path.getmtime(path)) < limit:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                logger.warning("No se pudo borrar el respaldo antiguo %s", path)
    return removed


def run_backup(config=None):
    """Hace un respaldo completo ahora. Guarda el resultado en SystemSettings y lo devuelve (ok, mensaje)."""
    config = config or SystemSettings.load()
    if not _lock.acquire(blocking=False):
        return False, "Ya hay un respaldo en curso."
    try:
        now = timezone.now()
        config.last_backup_attempt_at = now
        ok_folder, folder_message = check_folder(config.backup_path)
        if not ok_folder:
            raise BackupError(folder_message)
        prefix = f"marcajix-{sqlserver.database_name()}-"
        filename = f"{prefix}{timezone.localtime(now):%Y%m%d-%H%M%S}.bak"
        final = _backup_database(config.backup_path, filename)
        removed = _prune(config.backup_path, prefix, config.backup_retention_days)
        size_mb = os.path.getsize(final) / (1024 * 1024)
        message = f"Respaldo creado ({size_mb:.1f} MB)." + (f" Se borraron {removed} respaldos antiguos." if removed else "")
        config.last_backup_ok_at = now
        config.last_backup_status = "ok"
        config.last_backup_file = final
        config.last_backup_message = message
        logger.info("Respaldo creado en %s", final)
        return True, message
    except Exception as error:  # Cualquier fallo (red, permisos, SQL Server) queda registrado y genera una alerta.
        logger.exception("Falló el respaldo")
        config.last_backup_status = "error"
        config.last_backup_message = str(error)[:500]
        return False, config.last_backup_message
    finally:
        config.save(update_fields=["last_backup_attempt_at", "last_backup_ok_at", "last_backup_status", "last_backup_file", "last_backup_message"])
        _lock.release()


def backup_is_due(config, now=None):
    """Toca respaldar si está activo, ya pasó la hora de hoy y hoy no se intentó después de esa hora."""
    if not config.backup_enabled or not config.backup_path:
        return False
    now = timezone.localtime(now or timezone.now())
    scheduled = timezone.make_aware(datetime.combine(now.date(), config.backup_time), now.tzinfo)
    if now < scheduled:
        return False
    return config.last_backup_attempt_at is None or config.last_backup_attempt_at < scheduled


def list_backups(config, limit=10):
    """Últimos archivos de respaldo de Marcajix en la carpeta configurada (más recientes primero)."""
    if not config.backup_path or not os.path.isdir(config.backup_path):
        return []
    try:
        pattern = os.path.join(config.backup_path, f"marcajix-{sqlserver.database_name()}-*.bak")
    except ValueError:
        return []
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)[:limit]
    return [{"name": os.path.basename(path), "size_mb": os.path.getsize(path) / (1024 * 1024), "modified": timezone.make_aware(datetime.fromtimestamp(os.path.getmtime(path)))} for path in files]


def list_folders(path):
    """Subcarpetas de una ruta para el explorador de la interfaz. Sin ruta: unidades del equipo."""
    path = (path or "").strip()
    if not path:
        if os.name == "nt":
            roots = [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{letter}:\\")]
        else:
            roots = ["/"]
        return {"path": "", "parent": None, "folders": [{"name": root, "path": root} for root in roots]}
    if not os.path.isdir(path):
        raise BackupError("La carpeta no existe o no es accesible desde el servidor.")
    folders = []
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.name.startswith((".", "$")):
                    continue
                try:
                    if entry.is_dir():
                        folders.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
    except PermissionError as error:
        raise BackupError("No hay permiso para ver el contenido de esa carpeta.") from error
    folders.sort(key=lambda item: item["name"].lower())
    parent = os.path.dirname(os.path.normpath(path))
    if parent == os.path.normpath(path):  # Raíz de una unidad o de un recurso compartido.
        parent = ""
    return {"path": os.path.normpath(path), "parent": parent, "folders": folders[:500]}
