$ErrorActionPreference = "Stop"

# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
# What it does:
#   1) Free ports 5000 and 5173
#   2) Open two PowerShell windows for backend and frontend

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

Write-Host "Checking folders..." -ForegroundColor Cyan
if (-not (Test-Path $backend)) { throw "Backend folder not found: $backend" }
if (-not (Test-Path $frontend)) { throw "Frontend folder not found: $frontend" }

Write-Host "Freeing ports 5000 and 5173..." -ForegroundColor Cyan
foreach ($port in 5000, 5173) {
  $procIds = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($procId in $procIds) {
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "Starting backend (Flask 5000)..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$backend'; Write-Host 'Backend: http://127.0.0.1:5000' -ForegroundColor Green; python app.py"
)

Start-Sleep -Milliseconds 700

Write-Host "Starting frontend (Vite 5173)..." -ForegroundColor Green
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$frontend'; Write-Host 'Frontend: http://localhost:5173' -ForegroundColor Green; npm run dev"
)

Write-Host "Started:" -ForegroundColor Yellow
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor Yellow
Write-Host "  Backend : http://127.0.0.1:5000" -ForegroundColor Yellow
