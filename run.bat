@echo off
setlocal enabledelayedexpansion

echo ==================================================
echo       File Guessr - Launcher
echo ==================================================
echo.

:: --- Part 1: Ensure Elasticsearch is running ---
echo [INFO] Checking Elasticsearch service...
set "ES_SERVICE_NAME=elasticsearch-service-x64"

sc query "!ES_SERVICE_NAME!" >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Elasticsearch service not found. 
    echo Please run deploy.bat first to install the service.
    echo Searching will use SQLite fallback.
    goto :START_APP
)

:: Check if it's running
:CHECK_STATE
for /f "tokens=4" %%s in ('sc query "!ES_SERVICE_NAME!" ^| findstr STATE') do set "ES_STATE=%%s"
if "!ES_STATE!" neq "RUNNING" (
    echo [INFO] Elasticsearch service is !ES_STATE!. Attempting to start...
    
    :: Try to start without elevation first
    sc start "!ES_SERVICE_NAME!" >nul 2>&1
    
    :: Re-check
    timeout /t 2 /nobreak >nul
    for /f "tokens=4" %%s in ('sc query "!ES_SERVICE_NAME!" ^| findstr STATE') do set "ES_STATE=%%s"
    
    if "!ES_STATE!" neq "RUNNING" (
        echo [!] Could not start service normally. Attempting to elevate...
        powershell -Command "Start-Process cmd -ArgumentList '/c sc start !ES_SERVICE_NAME!' -Verb RunAs"
        
        echo [INFO] Waiting for service to initialize (up to 30 seconds)...
        set /a wait_retry=0
        :WAIT_SERVICE_START
        timeout /t 3 /nobreak >nul
        for /f "tokens=4" %%s in ('sc query "!ES_SERVICE_NAME!" ^| findstr STATE') do set "ES_STATE=%%s"
        if "!ES_STATE!" neq "RUNNING" (
            set /a wait_retry+=1
            if !wait_retry! lss 10 (
                <nul set /p=.
                goto :WAIT_SERVICE_START
            )
            echo.
            echo [!] Service failed to reach RUNNING state. Current: !ES_STATE!
        ) else (
            echo.
            echo [SUCCESS] Service is now !ES_STATE!.
        )
    )
)

:: Wait for ES to be responsive (HTTP level)
if "!ES_STATE!" == "RUNNING" (
    echo [INFO] Waiting for Elasticsearch HTTP to be ready...
    set /a retry_count=0
    :WAIT_ES
    powershell -Command "try { $resp = Invoke-WebRequest -Uri 'http://localhost:9200' -UseBasicParsing -TimeoutSec 1; exit 0 } catch { exit 1 }" >nul 2>&1
    if %errorlevel% equ 0 (
        echo [SUCCESS] Elasticsearch is ready.
    ) else (
        set /a retry_count+=1
        if !retry_count! lss 15 (
            <nul set /p=.
            timeout /t 3 /nobreak >nul
            goto :WAIT_ES
        )
        echo.
        echo [WARNING] Elasticsearch HTTP timed out. Configuration issue?
        echo Searching might use SQLite fallback.
    )
) else (
    echo [WARNING] Skipping HTTP check because service is not running.
)

:START_APP
:: --- Part 2: Launch Application ---
:: Check if venv exists
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo Please run deploy.bat first.
    pause
    exit /b 1
)

echo.
echo [INFO] Starting File Guessr...
echo.

:: Run the launcher directly using venv python
"venv\Scripts\python.exe" launcher_bg.py

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Application crashed with code %errorlevel%
)

pause
