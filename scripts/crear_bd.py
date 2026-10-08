"""Crea la base de datos de Marcajix en SQL Server si todavía no existe (usa los datos de .env).

Lo ejecuta el instalador antes de `manage.py migrate`, porque Django no puede crear la base de datos.
"""
import os
import re
import sys
from pathlib import Path

import pyodbc
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


def main():
    load_dotenv(BASE_DIR / ".env")
    name = os.getenv("DB_NAME", "").strip()
    host = os.getenv("DB_HOST", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", name) or not host:
        sys.exit("DB_NAME (solo letras, números y _) y DB_HOST son obligatorios en .env.")
    port = os.getenv("DB_PORT", "").strip()
    parts = [
        f"DRIVER={{{os.getenv('DB_DRIVER', 'ODBC Driver 18 for SQL Server')}}}",
        f"SERVER={host},{port}" if port else f"SERVER={host}",
        "DATABASE=master",
        "TrustServerCertificate=yes",
    ]
    if os.getenv("DB_AUTH", "sql").lower() in {"windows", "trusted"}:
        parts.append("Trusted_Connection=yes")
    else:
        parts += [f"UID={os.getenv('DB_USER', '')}", f"PWD={os.getenv('DB_PASSWORD', '')}"]
    try:
        connection = pyodbc.connect(";".join(parts), autocommit=True, timeout=15)
    except pyodbc.Error as error:
        sys.exit(f"No se pudo conectar a SQL Server en {host}: {error}")
    with connection:
        connection.execute(f"IF DB_ID(N'{name}') IS NULL CREATE DATABASE [{name}]")
    print(f"Base de datos '{name}' lista en {host}.")


if __name__ == "__main__":
    main()
