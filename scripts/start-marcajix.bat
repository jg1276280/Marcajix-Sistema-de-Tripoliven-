@echo off
set "LAUNCHER=%~dp0start-marcajix.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LAUNCHER%"
exit /b %ERRORLEVEL%