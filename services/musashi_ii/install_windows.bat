@echo off
REM ============================================================
REM  MUSASHI Super Sigma CMII - Windows Installation Script
REM  Run this script ONCE to set up the Python environment
REM ============================================================
title MUSASHI - Windows Setup
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo.
echo ============================================================
echo   MUSASHI Super Sigma CMII - Windows Environment Setup
echo ============================================================
echo.

REM --- Check Python is installed ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download Python from: https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] Found %PYVER%
echo.

REM --- Create virtual environment ---
if exist ".venv" (
    echo [OK] Virtual environment already exists.
) else (
    echo [>>] Creating virtual environment...
    where uv >nul 2>&1
    if errorlevel 0 (
        uv venv .venv
    ) else (
        python -m venv .venv
    )
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)
echo.

REM --- Activate virtual environment ---
call .venv\Scripts\activate.bat
echo [OK] Virtual environment activated.
echo.

REM --- Install dependencies ---
echo [>>] Installing dependencies...
where uv >nul 2>&1
if errorlevel 0 (
    echo [OK] Using uv package manager.
    uv pip install -r requirements.txt
) else (
    echo [>>] Upgrading pip...
    python -m pip install --upgrade pip >nul 2>&1
    echo [OK] pip upgraded.
    pip install -r requirements.txt
)
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)
echo.
echo [OK] All dependencies installed successfully.
echo.

REM --- Copy Windows config if not present ---
if not exist "config.windows.json" (
    echo [WARN] config.windows.json not found.
    echo        Please create one based on config.json with Windows COM port settings.
) else (
    echo [OK] config.windows.json found.
)
echo.

REM --- Verify installation ---
echo [>>] Running verification test (mock mode, single read)...
echo.
python read_musashi.py --mock --once
if errorlevel 1 (
    echo.
    echo [WARN] Verification test returned an error. Check the output above.
) else (
    echo.
    echo [OK] Verification test passed!
)

echo.
echo ============================================================
echo   Setup Complete!
echo.
echo   To start the service:
echo     - Double-click: run_musashi.bat
echo     - PowerShell:   .\run_musashi.ps1
echo     - Command line: python read_musashi.py --mock
echo.
echo   To find your COM port:
echo     1. Open Device Manager
echo     2. Expand "Ports (COM ^& LPT)"
echo     3. Look for "USB Serial Device (COMx)"
echo     4. Update config.windows.json with the correct port
echo ============================================================
echo.
pause
