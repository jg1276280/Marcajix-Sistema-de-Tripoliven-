#Requires -Version 5.1
<#
    Instalador de Marcajix para Windows 10/11.

    Modo 1 - PC de la garita (servidor): instala Python, el driver ODBC y, si hace falta,
             SQL Server Express; configura .env, crea la base de datos, registra el servidor
             web y el lector HID como tareas que arrancan con Windows y crea los accesos directos.
    Modo 2 - Otra PC de la empresa: solo crea el acceso directo al sistema en el escritorio.

    Se puede volver a ejecutar sin problema: lo que ya está instalado se conserva.
#>
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Port = 8000
. (Join-Path $PSScriptRoot 'comun.ps1')

# --- Elevación: instalar programas, abrir el firewall y registrar tareas requiere administrador ---
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Se necesitan permisos de administrador. Acepte el aviso de Windows para continuar.'
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

function Install-WingetPackage([string]$Id, [string]$Name, [string[]]$ExtraArgs = @()) {
    & winget list --id $Id --exact --accept-source-agreements *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "$Name ya está instalado."
        return
    }
    Write-Host "Instalando $Name (puede tardar varios minutos)..."
    & winget install --id $Id --exact --silent --accept-package-agreements --accept-source-agreements @ExtraArgs
    # 3010 = instalado, requiere reiniciar más tarde.
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 3010) {
        throw "No se pudo instalar $Name (winget devolvió $LASTEXITCODE)."
    }
    Write-Ok "$Name instalado."
}

function Find-BasePython {
    $candidates = @(
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $path = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $path) { return $path.Trim() }
    }
    return $null
}

function Get-LanAddresses {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        Select-Object -ExpandProperty IPAddress
}

function New-SecretKey {
    $bytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes)
}

function Write-EnvFile([hashtable]$Database) {
    $hosts = @('localhost', '127.0.0.1', $env:COMPUTERNAME)
    $domain = (Get-CimInstance Win32_ComputerSystem).Domain
    if ($domain -and $domain -ne 'WORKGROUP') { $hosts += "$($env:COMPUTERNAME).$domain" }
    $hosts += @(Get-LanAddresses)
    $hosts = $hosts | Where-Object { $_ } | Select-Object -Unique
    $origins = ($hosts | ForEach-Object { "http://${_}:$Port" }) -join ','
    $lines = @(
        '# Generado por el instalador de Marcajix. Puede editarse; reinicie las tareas después.',
        'DEBUG=False',
        "SECRET_KEY=$(New-SecretKey)",
        "ALLOWED_HOSTS=$($hosts -join ',')",
        "CSRF_TRUSTED_ORIGINS=$origins",
        'TIME_ZONE=America/Caracas',
        '',
        'DB_ENGINE=sql_server',
        "DB_AUTH=$($Database.Auth)",
        "DB_HOST=$($Database.Host)",
        "DB_PORT=$($Database.Port)",
        "DB_NAME=$($Database.Name)",
        "DB_USER=$($Database.User)",
        "DB_PASSWORD=$($Database.Password)",
        'DB_DRIVER=ODBC Driver 18 for SQL Server',
        'DB_TRUST_CERT=yes',
        '',
        '# Pantallas que ven el kiosco sin iniciar sesión (esta PC). Añada IPs si instala otras pantallas.',
        'KIOSK_DISPLAY_IPS=127.0.0.1,::1',
        'ATTENDANCE_WORKDAY_HOURS=8'
    )
    Write-Utf8File (Join-Path $Root '.env') ($lines -join "`r`n")
}

function Read-DatabaseSettings([bool]$LocalExpress) {
    if ($LocalExpress) {
        return @{ Auth = 'windows'; Host = 'localhost\SQLEXPRESS'; Port = ''; Name = 'marcajix'; User = ''; Password = '' }
    }
    Write-Host 'Datos del SQL Server existente de la empresa:'
    $database = @{
        Host = Read-Value 'Servidor (ej. SRV-SQL o SRV-SQL\INSTANCIA)' ''
        Port = Read-Value 'Puerto (vacío para instancia con nombre)' '1433'
        Name = Read-Value 'Nombre de la base de datos' 'marcajix'
        User = ''
        Password = ''
    }
    if (Read-YesNo '¿Usar autenticación de Windows (la cuenta de esta PC)?' $true) {
        $database.Auth = 'windows'
    } else {
        $database.Auth = 'sql'
        $database.User = Read-Value 'Usuario de SQL Server' 'marcajix'
        $secure = Read-Host 'Contraseña de SQL Server' -AsSecureString
        $database.Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
    }
    return $database
}

function Invoke-Manage([string[]]$Arguments) {
    Push-Location $Root
    try {
        & $Python manage.py @Arguments
        if ($LASTEXITCODE -ne 0) { throw "manage.py $($Arguments -join ' ') falló." }
    } finally {
        Pop-Location
    }
}

function Register-MarcajixTasks {
    $service = Join-Path $Root 'scripts\servicio.bat'
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
    $tasks = @(
        @{ Name = 'Servidor'; Argument = 'web'; Description = 'Servidor web de Marcajix (puerto 8000).' },
        @{ Name = 'Lector HID'; Argument = 'lector'; Description = 'Lector de tarjetas HID de la garita.' }
    )
    $user = "$env:USERDOMAIN\$env:USERNAME"
    Write-Host ''
    Write-Host "Para que Marcajix arranque con Windows aunque nadie inicie sesión, escriba la contraseña"
    Write-Host "de Windows de $user. Si la deja vacía, arrancará al iniciar sesión en Windows."
    $secure = Read-Host 'Contraseña de Windows' -AsSecureString
    $password = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))

    foreach ($task in $tasks) {
        $action = New-ScheduledTaskAction -Execute $service -Argument $task.Argument -WorkingDirectory $Root
        Unregister-ScheduledTask -TaskPath '\Marcajix\' -TaskName $task.Name -Confirm:$false -ErrorAction SilentlyContinue
        $registered = $false
        if ($password) {
            try {
                Register-ScheduledTask -TaskPath '\Marcajix\' -TaskName $task.Name -Description $task.Description -Action $action `
                    -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $settings -User $user -Password $password -RunLevel Limited | Out-Null
                $registered = $true
            } catch {
                Write-Warn "No se aceptó la contraseña ($($_.Exception.Message)). Se usará el inicio de sesión de Windows."
                $password = ''
            }
        }
        if (-not $registered) {
            $principalAtLogon = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
            Register-ScheduledTask -TaskPath '\Marcajix\' -TaskName $task.Name -Description $task.Description -Action $action `
                -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) -Settings $settings -Principal $principalAtLogon | Out-Null
        }
        Start-ScheduledTask -TaskPath '\Marcajix\' -TaskName $task.Name
        Write-Ok "Tarea '$($task.Name)' registrada e iniciada."
    }
}

function Install-ClientShortcut {
    $server = Read-Value 'Nombre o IP de la PC de la garita (servidor)' ''
    if (-not $server) { throw 'Debe indicar el servidor.' }
    $url = "http://${server}:$Port/"
    New-AppShortcut -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Marcajix.lnk') -Url $url -Description 'Marcajix - Control de asistencia'
    Write-Ok "Acceso directo 'Marcajix' creado en el escritorio ($url)."
    try {
        Invoke-WebRequest -Uri "${url}login/" -UseBasicParsing -TimeoutSec 5 | Out-Null
        Write-Ok 'El servidor responde correctamente.'
    } catch {
        Write-Warn "Ahora mismo no se puede conectar con $url. Compruebe que la PC de la garita está encendida."
    }
}

# =============================== Programa principal ===============================
try {
    Write-Host ''
    Write-Host '  MARCAJIX - Instalador' -ForegroundColor Red
    Write-Host '  ----------------------'
    Write-Host '  1) PC de la garita: servidor, base de datos, lector HID y pantallas'
    Write-Host '  2) Otra PC de la empresa: solo el acceso directo'
    $mode = Read-Value 'Elija 1 o 2' '1'
    if ($mode -eq '2') {
        Install-ClientShortcut
        return
    }

    Write-Step 'Comprobando winget (instalador de aplicaciones de Windows)'
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'No se encontró winget. Instale "Instalador de aplicación" desde Microsoft Store y vuelva a ejecutar.'
    }

    Write-Step 'Instalando programas necesarios'
    if (-not (Find-BasePython)) { Install-WingetPackage 'Python.Python.3.12' 'Python 3.12' @('--scope', 'machine') }
    else { Write-Ok 'Python 3.12 ya está instalado.' }
    Install-WingetPackage 'Microsoft.msodbcsql.18' 'Driver ODBC 18 para SQL Server'
    $localExpress = Read-YesNo '¿Instalar SQL Server Express en esta PC? (responda N si la empresa ya tiene un SQL Server)' $true
    if ($localExpress) {
        if (Get-Service 'MSSQL$SQLEXPRESS' -ErrorAction SilentlyContinue) { Write-Ok 'SQL Server Express ya está instalado.' }
        else { Install-WingetPackage 'Microsoft.SQLServer.2022.Express' 'SQL Server 2022 Express' }
    }

    Write-Step 'Preparando el entorno de Python'
    $basePython = Find-BasePython
    if (-not $basePython) { throw 'Python 3.12 no aparece tras la instalación. Reinicie la PC y vuelva a ejecutar el instalador.' }
    if (-not (Test-Path $Python)) { & $basePython -m venv (Join-Path $Root '.venv') }
    & $Python -m pip install --upgrade pip --quiet
    & $Python -m pip install -r (Join-Path $Root 'requirements.txt') --quiet
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de Python.' }
    Write-Ok 'Dependencias instaladas.'

    Write-Step 'Configuración (.env)'
    $envPath = Join-Path $Root '.env'
    if ((Test-Path $envPath) -and (Read-YesNo 'Ya existe una configuración. ¿Conservarla?' $true)) {
        Write-Ok 'Se conserva la configuración actual.'
    } else {
        Write-EnvFile (Read-DatabaseSettings $localExpress)
        Write-Ok 'Configuración creada con una clave secreta nueva.'
    }

    Write-Step 'Base de datos'
    & $Python (Join-Path $Root 'scripts\crear_bd.py')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo preparar la base de datos.' }
    Invoke-Manage @('migrate', '--noinput')
    Invoke-Manage @('collectstatic', '--noinput', '--verbosity', '0')
    Write-Ok 'Base de datos y archivos estáticos listos.'
    if (Read-YesNo '¿Crear ahora un usuario administrador (rol Sistemas)?' $true) {
        Invoke-Manage @('createsuperuser')
    }

    Write-Step 'Red: abrir el puerto para las demás PCs'
    if (-not (Get-NetFirewallRule -DisplayName 'Marcajix' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName 'Marcajix' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain, Private | Out-Null
    }
    Write-Ok "Puerto $Port abierto en redes de dominio y privadas."

    Write-Step 'Servicios en segundo plano'
    Register-MarcajixTasks

    Write-Step 'Accesos directos'
    $desktop = [Environment]::GetFolderPath('Desktop')
    New-AppShortcut -Path (Join-Path $desktop 'Marcajix.lnk') -Url "http://localhost:$Port/" -Description 'Marcajix - Panel'
    $garita = Join-Path $Root 'scripts\abrir-garita.ps1'
    New-ScriptShortcut -Path (Join-Path $desktop 'Marcajix Garita.lnk') -Script $garita -Description 'Abre el kiosco en la pantalla exterior y el panel en la interior'
    Write-Ok "Accesos 'Marcajix' y 'Marcajix Garita' creados en el escritorio."
    if (Read-YesNo '¿Abrir automáticamente las pantallas de la garita al iniciar sesión en Windows?' $true) {
        New-ScriptShortcut -Path (Join-Path ([Environment]::GetFolderPath('Startup')) 'Marcajix Garita.lnk') -Script $garita -Description 'Pantallas de Marcajix'
        Write-Ok 'Las pantallas se abrirán solas al iniciar sesión.'
    }
    if (Read-YesNo '¿Evitar que la PC y las pantallas se suspendan? (recomendado en la garita)' $true) {
        & powercfg /change standby-timeout-ac 0
        & powercfg /change monitor-timeout-ac 0
        Write-Ok 'Suspensión desactivada.'
    }

    Write-Step 'Comprobando el servidor'
    if (Wait-Server "http://localhost:$Port/login/" 60) { Write-Ok 'Marcajix está funcionando.' }
    else { Write-Warn 'El servidor aún no responde. Revise logs\servidor.log.' }

    Write-Host ''
    Write-Host 'Instalación terminada.' -ForegroundColor Green
    Write-Host 'Desde las demás PCs de la empresa, abra en el navegador:'
    Write-Host "   http://$($env:COMPUTERNAME):$Port/"
    foreach ($ip in Get-LanAddresses) { Write-Host "   http://${ip}:$Port/" }
    Write-Host 'o ejecute este mismo instalador allí y elija la opción 2.'
    Write-Host 'Siguiente paso: entre con el administrador, configure el puerto COM del lector en'
    Write-Host 'Dispositivos y cree los usuarios de Seguridad y Recursos Humanos.'
} catch {
    Write-Host ''
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
} finally {
    Write-Host ''
    Read-Host 'Pulse Enter para cerrar'
}
