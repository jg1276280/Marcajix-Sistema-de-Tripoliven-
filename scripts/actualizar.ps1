#Requires -Version 5.1
<#
    Actualiza Marcajix a la última versión: descarga el código (si se instaló con git),
    actualiza dependencias, aplica migraciones y reinicia el servidor y el lector.
    Si se instaló desde un ZIP: descomprima la versión nueva encima de esta carpeta
    (conservando .env, media y logs) y luego ejecute ACTUALIZAR.bat.
#>
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
. (Join-Path $PSScriptRoot 'comun.ps1')

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

try {
    if (-not (Test-Path $Python)) { throw 'Marcajix no está instalado en esta PC. Ejecute INSTALAR.bat primero.' }

    Write-Step 'Deteniendo Marcajix'
    Get-ScheduledTask -TaskPath '\Marcajix\' -ErrorAction SilentlyContinue | Stop-ScheduledTask

    if ((Test-Path (Join-Path $Root '.git')) -and (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Step 'Descargando la última versión'
        & git -C $Root pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw 'git pull falló. Revise si hay cambios locales en la carpeta.' }
    }

    Write-Step 'Actualizando dependencias y base de datos'
    & $Python -m pip install -r (Join-Path $Root 'requirements.txt') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
    Push-Location $Root
    try {
        foreach ($command in @(@('migrate', '--noinput'), @('collectstatic', '--noinput', '--verbosity', '0'))) {
            & $Python manage.py @command
            if ($LASTEXITCODE -ne 0) { throw "manage.py $($command -join ' ') falló." }
        }
    } finally {
        Pop-Location
    }

    Write-Step 'Iniciando Marcajix'
    Get-ScheduledTask -TaskPath '\Marcajix\' | Start-ScheduledTask
    if (Wait-Server 'http://localhost:8000/login/' 60) { Write-Ok 'Marcajix actualizado y funcionando.' }
    else { Write-Warn 'El servidor aún no responde. Revise logs\servidor.log.' }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    Read-Host 'Pulse Enter para cerrar'
}
