@echo off
title Stock Prediction Lab v2.0 - Advanced Analysis Engine
echo.
echo ============================================================
echo   Stock Prediction Lab v2.0 - Starting Server...
echo ============================================================
echo.
cd /d "%~dp0"

REM Start the browser after a short delay (server needs time to start)
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

REM Start the Python server
python app_advanced.py
pause
