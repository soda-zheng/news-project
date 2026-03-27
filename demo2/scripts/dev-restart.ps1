# 一键结束 5000/5173 并重启前后端（开发用）
# 用法：在 PowerShell 中执行  .\scripts\dev-restart.ps1
# 会各开一个独立窗口：Flask（带 DEV_RELOAD）+ Vite

$ErrorActionPreference = "SilentlyContinue"
$demo2Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backend = Join-Path $demo2Root "backend"
$frontend = Join-Path $demo2Root "frontend"

Write-Host "释放端口 5000、5173 …" -ForegroundColor Cyan
foreach ($port in 5000, 5173) {
  Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}

Write-Host "启动后端（DEV_RELOAD=1 自动重载 Python）…" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$backend'; `$env:DEV_RELOAD='1'; Write-Host 'Flask http://127.0.0.1:5000' -ForegroundColor Green; python app.py"
)

Start-Sleep -Seconds 1

Write-Host "启动前端 Vite …" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$frontend'; Write-Host 'Vite http://localhost:5173' -ForegroundColor Green; npm run dev"
)

Write-Host "已在新窗口启动。前端: http://localhost:5173  后端: http://127.0.0.1:5000" -ForegroundColor Yellow
