@echo off
echo ==================================================
echo       File Guessr - Launcher
echo ==================================================
echo.

:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please run fix_environment.bat first.
    pause
    exit /b 1
)

echo [INFO] Starting File Guessr...
echo.

:: Run the launcher directly using venv python
"venv\Scripts\python.exe" launcher.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application crashed with code %errorlevel%
)

pause
