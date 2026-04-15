$ErrorActionPreference = "SilentlyContinue"

# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
# What it does:
#   Kill processes listening on 5000 / 5173

Write-Host "Stopping backend/frontend..." -ForegroundColor Cyan
foreach ($port in 5000, 5173) {
  $procIds = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

  if (-not $procIds) {
    Write-Host "Port $port not listening" -ForegroundColor DarkGray
    continue
  }

  foreach ($procId in $procIds) {
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  }

  Start-Sleep -Milliseconds 300
  $left = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($left) {
    Write-Host "Port $port still in use" -ForegroundColor Red
  } else {
    Write-Host "Port $port closed" -ForegroundColor Green
  }
}

Write-Host "Done." -ForegroundColor Yellow
