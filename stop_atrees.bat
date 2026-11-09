@echo off
title Stop Atrees
echo Stopping Atrees background processes...
taskkill /F /FI "WINDOWTITLE eq Atrees - Freelance Job Hunting Bot*" >nul 2>&1
wmic process where "commandline like '%%listener.py%%' and name='python.exe'" call terminate >nul 2>&1
echo Atrees has been stopped cleanly.
ping 127.0.0.1 -n 2 >nul

