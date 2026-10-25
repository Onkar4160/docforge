# =======================================================================
#          DOCFORGE - ONE-CLICK LAUNCHER (POWERSHELL)
# =======================================================================
$Root = $PSScriptRoot
Set-Location $Root

Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host "                    DOCFORGE APPLICATION LAUNCHER                      " -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[*] Checking environment..." -ForegroundColor Yellow

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvActivate = Join-Path $Root ".venv\Scripts\Activate.ps1"

if (Test-Path $VenvPython) {
    Write-Host "  [OK] Found virtual environment at .venv" -ForegroundColor Green
} else {
    Write-Host "  [!] .venv not found, falling back to system python" -ForegroundColor Yellow
    $VenvPython = "python"
}

Write-Host ""
Write-Host "[*] Launching DocForge Server in a dedicated terminal..." -ForegroundColor Yellow

# Terminal 1: DocForge Backend & Web Server (FastAPI on Port 8000)
$ServerScript = @"
`$Host.UI.RawUI.WindowTitle = 'DocForge - Server (:8000)'
cd '$Root'
if (Test-Path '$VenvActivate') { . '$VenvActivate' }
Write-Host '===================================================' -ForegroundColor Green
Write-Host '   DOCFORGE SERVER RUNNING ON http://127.0.0.1:8000' -ForegroundColor Green
Write-Host '   - Web Dashboard:  http://127.0.0.1:8000/' -ForegroundColor Green
Write-Host '   - REST API:       http://127.0.0.1:8000/api' -ForegroundColor Green
Write-Host '   - Swagger Docs:   http://127.0.0.1:8000/docs' -ForegroundColor Green
Write-Host '   - Login demo:     demo / demo123' -ForegroundColor Green
Write-Host '===================================================' -ForegroundColor Green
& '$VenvPython' -m uvicorn docforge.api.app:app --host 127.0.0.1 --port 8000 --reload
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $ServerScript

Write-Host "DocForge server terminal launched successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "  * Web Dashboard:  http://127.0.0.1:8000" -ForegroundColor White
Write-Host "  * REST API:       http://127.0.0.1:8000/api" -ForegroundColor White
Write-Host "  * API Docs:       http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "  * Demo Login:     demo / demo123" -ForegroundColor White
Write-Host ""
Write-Host "Opening http://127.0.0.1:8000 in your browser..." -ForegroundColor Yellow

Start-Sleep -Seconds 2
Start-Process "http://127.0.0.1:8000"
