@echo off
title Atrees - Freelance Job Hunting Bot
cd /d "%~dp0"

echo ========================================================
echo         Atrees Freelance Job Hunting System
echo ========================================================

if not exist .venv\Scripts\python.exe goto :no_venv

echo Starting Atrees Listener and Bot...
.venv\Scripts\python.exe listener.py
pause
exit /b 0

:no_venv
echo [ERROR] Virtual environment (.venv) not found!
echo Please install requirements first.
pause
exit /b 1
