@echo off
title Atrees Freelance Bot - Local Web Dashboard
cd /d "%~dp0"

echo ========================================================
echo        Atrees Freelance Bot - Local Dashboard
echo ========================================================
echo.

if not exist .venv\Scripts\python.exe goto :no_venv

echo [INFO] Starting Atrees Local Web Dashboard
echo [INFO] Dashboard URL: http://localhost:8000
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://localhost:8000'"

.venv\Scripts\python.exe -m uvicorn dashboard_api:app --host 0.0.0.0 --port 8000

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Dashboard server encountered an error.
    pause
)
exit /b 0

:no_venv
echo [ERROR] Virtual environment (.venv) not found!
echo Please make sure .venv exists.
pause
exit /b 1