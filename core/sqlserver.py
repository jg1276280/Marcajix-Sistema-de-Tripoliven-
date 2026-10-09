"""Conexión directa a SQL Server con los datos de .env (sin Django).

La usan el instalador (scripts/crear_bd.py, antes de que exista la base de datos) y los
respaldos (BACKUP DATABASE no puede ejecutarse dentro de una transacción de Django).
"""
import os
import re
import socket

LOCAL_HOSTS = {"localhost", ".", "127.0.0.1", "(local)", "::1"}


def database_name():
    name = os.getenv("DB_NAME", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError("DB_NAME solo puede contener letras, números y guion bajo.")
    return name


def connection_string(database="master"):
    host = os.getenv("DB_HOST", "").strip()
    if not host:
        raise ValueError("Falta DB_HOST en .env.")
    port = os.getenv("DB_PORT", "").strip()
    parts = [
        f"DRIVER={{{os.getenv('DB_DRIVER', 'ODBC Driver 18 for SQL Server')}}}",
        f"SERVER={host},{port}" if port else f"SERVER={host}",
        f"DATABASE={database}",
        "TrustServerCertificate=yes",
    ]
    if os.getenv("DB_AUTH", "sql").lower() in {"windows", "trusted"}:
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={os.getenv('DB_USER', '')}", f"PWD={os.getenv('DB_PASSWORD', '')}"]
    return ";".join(parts)


def connect(database="master", timeout=15):
    import pyodbc

    return pyodbc.connect(connection_string(database), autocommit=True, timeout=timeout)


def is_local_server():
    """True si SQL Server corre en esta misma PC (su disco es el nuestro)."""
    host = re.split(r"[\\,]", os.getenv("DB_HOST", "").strip(), maxsplit=1)[0].lower()
    return host in LOCAL_HOSTS or host in {socket.gethostname().lower(), os.getenv("COMPUTERNAME", "").lower()}


def run_to_completion(cursor, sql, *params):
    """Ejecuta una sentencia y consume todos sus resultados: BACKUP solo termina al leerlos."""
    cursor.execute(sql, *params)
    while cursor.nextset():
        pass
