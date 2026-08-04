@echo off
REM ============================================================
REM  MUSASHI Super Sigma CMII - Windows Launcher
REM  Double-click this file to start the telemetry service
REM ============================================================
title MUSASHI Telemetry Service
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo ============================================================
echo   MUSASHI Super Sigma CMII Telemetry Service - Windows
echo ============================================================
echo.

REM --- Activate virtual environment if it exists ---
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
    echo [OK] Virtual environment activated.
) else (
    echo [WARN] No .venv found. Using system Python.
    echo        Run install_windows.bat first to set up the environment.
    echo.
)

REM --- Select config file ---
if exist "config.windows.json" (
    set CONFIG_FILE=config.windows.json
    echo [OK] Using Windows config: config.windows.json
) else (
    set CONFIG_FILE=config.json
    echo [INFO] Using default config: config.json
)

echo.
echo  Select mode:
echo    1) REAL mode   - Connect to physical dispenser via RS-232
echo    2) MOCK mode   - Simulate dispenser (no hardware needed)
echo    3) REAL (once) - Single read, then exit
echo    4) MOCK (once) - Single simulated read, then exit
echo    5) Exit
echo.
set /p MODE="  Enter choice [1-5]: "

if "%MODE%"=="1" (
    echo.
    echo Starting REAL mode...
    python read_musashi.py --config %CONFIG_FILE%
) else if "%MODE%"=="2" (
    echo.
    echo Starting MOCK mode...
    python read_musashi.py --config %CONFIG_FILE% --mock
) else if "%MODE%"=="3" (
    echo.
    echo Starting REAL mode (single read)...
    python read_musashi.py --config %CONFIG_FILE% --once
) else if "%MODE%"=="4" (
    echo.
    echo Starting MOCK mode (single read)...
    python read_musashi.py --config %CONFIG_FILE% --mock --once
) else if "%MODE%"=="5" (
    echo Exiting...
    goto :end
) else (
    echo Invalid choice. Exiting.
)

:end
echo.
echo ============================================================
echo  Service stopped. Press any key to close this window.
echo ============================================================
pause >nul
