@echo off
setlocal
cd /d "%~dp0"
echo Stopping services...
powershell -ExecutionPolicy Bypass -File ".\scripts\stop.ps1"
echo Starting services...
powershell -ExecutionPolicy Bypass -File ".\scripts\start.ps1"
endlocal
