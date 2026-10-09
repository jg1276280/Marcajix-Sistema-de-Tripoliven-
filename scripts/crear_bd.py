"""Crea la base de datos de Marcajix en SQL Server si todavía no existe (usa los datos de .env).

Lo ejecuta el instalador antes de `manage.py migrate`, porque Django no puede crear la base de datos.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from core import sqlserver  # noqa: E402  (core/sqlserver.py no depende de Django)


def main():
    load_dotenv(BASE_DIR / ".env")
    try:
        name = sqlserver.database_name()
        connection = sqlserver.connect()
    except ValueError as error:
        sys.exit(str(error))
    except Exception as error:  # pyodbc.Error y similares: se muestra el motivo al instalador.
        sys.exit(f"No se pudo conectar a SQL Server: {error}")
    with connection:
        connection.execute(f"IF DB_ID(N'{name}') IS NULL CREATE DATABASE [{name}]")
    print(f"Base de datos '{name}' lista.")


if __name__ == "__main__":
    main()
