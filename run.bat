@echo off
title DocForge Launcher
color 0b

echo =======================================================================
echo                    DOCFORGE APPLICATION LAUNCHER
echo =======================================================================
echo.
echo [*] Checking environment and preparing DocForge server...

set "ROOT_DIR=%~dp0"
set "VENV_PY=%ROOT_DIR%.venv\Scripts\python.exe"
set "VENV_ACTIVATE=%ROOT_DIR%.venv\Scripts\activate.bat"

if exist "%VENV_PY%" (
    echo   [OK] Found virtual environment in .venv
    set "PY_CMD="%VENV_PY%""
) else (
    echo   [!] .venv not found, using system python
    set "PY_CMD=python"
)

echo.
echo [*] Starting DocForge Server in a dedicated terminal...

start "DocForge - Server (:8000)" cmd /k "title DocForge - Server (:8000) && color 0a && cd /d "%ROOT_DIR%" && if exist "%VENV_ACTIVATE%" (call "%VENV_ACTIVATE%") && echo =================================================== && echo   DOCFORGE RUNNING ON http://127.0.0.1:8000 && echo   - Web Dashboard:  http://127.0.0.1:8000/ && echo   - REST API:       http://127.0.0.1:8000/api && echo   - Swagger Docs:   http://127.0.0.1:8000/docs && echo   - Demo Login:     demo / demo123 && echo =================================================== && %PY_CMD% -m uvicorn docforge.api.app:app --host 127.0.0.1 --port 8000 --reload"

echo.
echo =======================================================================
echo  DocForge Server launched in dedicated terminal window!
echo.
echo    * Web Dashboard:  http://127.0.0.1:8000
echo    * REST API:       http://127.0.0.1:8000/api
echo    * Swagger Docs:   http://127.0.0.1:8000/docs
echo    * Demo Login:     demo / demo123
echo.
echo  Opening http://127.0.0.1:8000 in your browser...
echo =======================================================================

timeout /t 2 /nobreak >nul
start http://127.0.0.1:8000

echo.
echo Keep the server terminal window open while using DocForge.
echo Press any key to close this launcher window (server stays running).
pause >nul
