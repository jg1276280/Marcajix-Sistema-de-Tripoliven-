@echo off
rem Ejecutado por las tareas programadas "Marcajix\Servidor" y "Marcajix\Lector HID".
rem Uso: servicio.bat web ^| lector
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set "PY=%CD%\.venv\Scripts\python.exe"
set PYTHONUNBUFFERED=1

if /i "%~1"=="web" (
    set "LOG=logs\servidor.log"
) else if /i "%~1"=="lector" (
    set "LOG=logs\lector.log"
) else (
    echo Uso: servicio.bat web^|lector
    exit /b 2
)

rem Rotacion simple: si el log supera 10 MB se guarda como .old y se empieza uno nuevo.
if exist "%LOG%" for %%F in ("%LOG%") do if %%~zF GTR 10485760 move /y "%LOG%" "%LOG%.old" >nul

echo [%date% %time%] Iniciando %~1 >> "%LOG%"
if /i "%~1"=="web" (
    "%PY%" -m waitress --listen=*:8000 --threads=8 config.wsgi:application >> "%LOG%" 2>&1
) else (
    "%PY%" manage.py listen_hid >> "%LOG%" 2>&1
)
exit /b %ERRORLEVEL%
