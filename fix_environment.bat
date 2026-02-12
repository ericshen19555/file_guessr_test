@echo off
echo ==================================================
echo       File Guessr - Environment Fixer
echo ==================================================

echo [1/5] Removing old virtual environment...
if exist "venv" (
    rmdir /s /q venv
    echo Deleted old venv.
)

echo [2/5] Creating new virtual environment...
python -m venv venv
if %errorlevel% neq 0 (
    echo [ERROR] Failed to create venv. Check Python installation.
    pause
    exit /b 1
)

echo [3/5] Activating environment...
call venv\Scripts\activate.bat

echo [4/5] Upgrading pip...
python -m pip install --upgrade pip

echo [5/5] Installing dependencies...
echo This might take a while, please wait...
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Dependency installation failed!
    echo Please check the error messages above.
    echo.
    echo Common solution: Install Python 3.12 instead of 3.14.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Environment fixed!
echo You can now run 'run.bat' normally.
pause
