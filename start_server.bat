@echo off
echo ============================================
echo   Stock Prediction Lab - Starting Server
echo ============================================
echo.

REM Check if Python is available
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Python not found in PATH
    echo Please install Python or add it to your PATH
    pause
    exit /b 1
)

echo Starting Flask backend server...
echo Server will run at http://localhost:5000
echo.
echo Press Ctrl+C to stop the server
echo ============================================
echo.

python app.py

pause
