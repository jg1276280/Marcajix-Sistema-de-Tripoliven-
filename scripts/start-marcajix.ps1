param([switch]$NoPause)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$serverUrl = "http://127.0.0.1:8000/dashboard/marcajes/"
$logDirectory = Join-Path $projectRoot "logs"
$outputLogPath = Join-Path $logDirectory "server.out.log"
$errorLogPath = Join-Path $logDirectory "server.err.log"
$serverProcess = $null
$readerProcess = $null
$launcherMutex = $null
$ownsLauncherMutex = $false

function Stop-WithError {
    param([string]$Message)

    Write-Host "`nMarcajix no pudo iniciarse.`n" -ForegroundColor Red
    Write-Host $Message -ForegroundColor Yellow
    Write-Host "`nÚltimas líneas del registro:" -ForegroundColor Cyan
    foreach ($logFile in @($errorLogPath, $outputLogPath)) {
        if ((Test-Path $logFile) -and (Get-Item $logFile).Length -gt 0) {
            Get-Content $logFile -Tail 18
        }
    }
    Write-Host "`nRevisa la conexión de SQL Server y vuelve a ejecutar el acceso directo." -ForegroundColor Gray
    if (-not $NoPause) {
        Read-Host "Pulsa Enter para cerrar"
    }
    exit 1
}

function Test-ServerReady {
    try {
        Invoke-WebRequest -Uri $serverUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

try {
    $launcherMutex = New-Object System.Threading.Mutex($false, "Local\Marcajix.ServerLauncher")
    $ownsLauncherMutex = $launcherMutex.WaitOne(0)
} catch [System.Threading.AbandonedMutexException] {
    $ownsLauncherMutex = $true
}

if (-not $ownsLauncherMutex) {
    if (Test-ServerReady) {
        Start-Process $serverUrl
        exit 0
    }
    Stop-WithError "Ya existe un arranque de Marcajix en curso. Espera unos segundos e inténtalo de nuevo."
}

if (-not (Test-Path $pythonPath)) {
    Stop-WithError "No se encontró el entorno virtual en $pythonPath."
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if (Test-ServerReady) {
    Start-Process $serverUrl
    $launcherMutex.ReleaseMutex()
    $launcherMutex.Dispose()
    exit 0
}

$portOwner = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($portOwner) {
    Stop-WithError "El puerto 8000 está ocupado por otro proceso, pero no responde como Marcajix."
}

Set-Content -Path $outputLogPath -Value "Inicio de Marcajix: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Set-Content -Path $errorLogPath -Value ""
$serverProcess = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @("-m", "daphne", "-b", "127.0.0.1", "-p", "8000", "config.routing:application") `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $outputLogPath `
    -RedirectStandardError $errorLogPath `
    -WindowStyle Hidden `
    -PassThru

$readerProcess = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @("manage.py", "listen_hid", "--reader", "1") `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput (Join-Path $logDirectory "reader.out.log") `
    -RedirectStandardError (Join-Path $logDirectory "reader.err.log") `
    -WindowStyle Hidden `
    -PassThru

for ($attempt = 1; $attempt -le 30; $attempt++) {
    Start-Sleep -Seconds 1
    if (Test-ServerReady) {
        break
    }
    if ($serverProcess.HasExited) {
        Stop-WithError "Django se detuvo durante el arranque."
    }
}

if (-not (Test-ServerReady)) {
    if (-not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Stop-WithError "Django no respondió después de 30 segundos."
}

Start-Process $serverUrl
try {
    Wait-Process -Id $serverProcess.Id
} finally {
    if ($readerProcess -and -not $readerProcess.HasExited) {
        Stop-Process -Id $readerProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($launcherMutex) {
        $launcherMutex.ReleaseMutex()
        $launcherMutex.Dispose()
    }
}