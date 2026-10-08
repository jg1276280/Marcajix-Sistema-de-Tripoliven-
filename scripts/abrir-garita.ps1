#Requires -Version 5.1
<#
    Abre las dos pantallas de la garita:
      - Pantalla exterior (monitor secundario): kiosco a pantalla completa, sin sesión.
      - Pantalla interior (monitor principal): panel del inspector de Seguridad.
    El kiosco funciona aunque ningún inspector haya iniciado sesión en el panel.
#>
param([string]$Url = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
Add-Type -AssemblyName System.Windows.Forms

# Al iniciar Windows el servidor puede tardar en arrancar: se espera hasta 3 minutos.
if (-not (Wait-Server "$Url/login/" 180)) {
    [System.Windows.Forms.MessageBox]::Show('El servidor de Marcajix no responde. Revise logs\servidor.log o reinicie la PC.', 'Marcajix') | Out-Null
    exit 1
}

$edge = Find-Edge
$profiles = Join-Path $env:LOCALAPPDATA 'Marcajix'
$screens = [System.Windows.Forms.Screen]::AllScreens
$primary = $screens | Where-Object { $_.Primary } | Select-Object -First 1
$external = $screens | Where-Object { -not $_.Primary } | Select-Object -First 1

function Test-EdgeProfileRunning([string]$ProfileName) {
    $pattern = "*Marcajix\$ProfileName*"
    return [bool](Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" | Where-Object { $_.CommandLine -like $pattern } | Select-Object -First 1)
}

# Cada pantalla usa su propio perfil de Edge para abrirse como una ventana independiente.
if (-not (Test-EdgeProfileRunning 'kiosco')) {
    $kioskArgs = @("--user-data-dir=`"$profiles\kiosco`"", '--no-first-run', '--disable-features=Translate')
    if ($external) {
        $x = $external.Bounds.X + 50
        $y = $external.Bounds.Y + 50
        $kioskArgs += @('--kiosk', "$Url/kiosco/", '--edge-kiosk-type=fullscreen', "--window-position=$x,$y")
    } else {
        # Con un solo monitor el kiosco se abre en una ventana normal para no tapar el panel.
        $kioskArgs += @("--app=$Url/kiosco/")
    }
    Start-Process $edge -ArgumentList $kioskArgs
}

if (-not (Test-EdgeProfileRunning 'panel')) {
    $x = $primary.Bounds.X + 50
    $y = $primary.Bounds.Y + 50
    Start-Process $edge -ArgumentList @("--user-data-dir=`"$profiles\panel`"", '--no-first-run', "--app=$Url/dashboard/", "--window-position=$x,$y", '--start-maximized')
}
