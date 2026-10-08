# Funciones compartidas por los scripts de Marcajix (instalar, actualizar y abrir la garita).

function Write-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }

function Read-Value([string]$Question, [string]$Default) {
    $suffix = ''
    if ($Default) { $suffix = " [$Default]" }
    $answer = Read-Host "$Question$suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Read-YesNo([string]$Question, [bool]$Default) {
    $hint = 's/N'
    if ($Default) { $hint = 'S/n' }
    while ($true) {
        $answer = (Read-Host "$Question [$hint]").Trim().ToLower()
        if (-not $answer) { return $Default }
        if ($answer -in @('s', 'si', 'sí', 'y', 'yes')) { return $true }
        if ($answer -in @('n', 'no')) { return $false }
    }
}

function Write-Utf8File([string]$Path, [string]$Content) {
    [IO.File]::WriteAllText($Path, $Content, (New-Object Text.UTF8Encoding $false))
}

function Find-Edge {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    throw 'No se encontró Microsoft Edge.'
}

function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$Description, [string]$Icon) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = $Arguments
    $shortcut.Description = $Description
    if ($Icon) { $shortcut.IconLocation = $Icon }
    $shortcut.Save()
}

function New-AppShortcut([string]$Path, [string]$Url, [string]$Description) {
    # Abre Marcajix como una aplicación (ventana propia, sin barra del navegador).
    $edge = Find-Edge
    New-Shortcut $Path $edge "--app=$Url" $Description "$edge,0"
}

function New-ScriptShortcut([string]$Path, [string]$Script, [string]$Description) {
    $powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`""
    New-Shortcut $Path $powershell $arguments $Description "$(Join-Path $env:SystemRoot 'System32\shell32.dll'),15"
}

function Wait-Server([string]$Url, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    return $false
}
