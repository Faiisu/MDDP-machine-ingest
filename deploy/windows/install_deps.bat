@echo off
setlocal EnableDelayedExpansion
rem See: docs/architecture/context.md
rem English comments only

cd /d "%~dp0..\.."

echo ==========================================================
echo          MDDP Ingestion Suite - Installing Dependencies
echo ==========================================================

rem 1. Detect uv executable
set "UV_CMD="
where uv >nul 2>nul
if %errorlevel% equ 0 (
    set "UV_CMD=uv"
    for /f "delims=" %%i in ('uv --version 2^>^&1') do set "UV_VER=%%i"
    echo [SYSTEM] Detected uv package manager: !UV_VER!
) else (
    echo [SYSTEM] 'uv' not found in PATH. Checking Python fallback...
)

if not defined UV_CMD (
    set "PYTHON_CMD="
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        for /f "delims=" %%i in ('python --version 2^>^&1') do set "_PY_CHECK=%%i"
        echo !_PY_CHECK! | findstr /i "Python" >nul 2>nul
        if !errorlevel! equ 0 (
            set "PYTHON_CMD=python"
        )
    )
    if not defined PYTHON_CMD (
        where python3 >nul 2>nul
        if !errorlevel! equ 0 (
            for /f "delims=" %%i in ('python3 --version 2^>^&1') do set "_PY_CHECK=%%i"
            echo !_PY_CHECK! | findstr /i "Python" >nul 2>nul
            if !errorlevel! equ 0 (
                set "PYTHON_CMD=python3"
            )
        )
    )
    if not defined PYTHON_CMD (
        where py >nul 2>nul
        if !errorlevel! equ 0 (
            for /f "delims=" %%i in ('py --version 2^>^&1') do set "_PY_CHECK=%%i"
            echo !_PY_CHECK! | findstr /i "Python" >nul 2>nul
            if !errorlevel! equ 0 (
                set "PYTHON_CMD=py"
            )
        )
    )
    if not defined PYTHON_CMD (
        echo [ERROR] Neither 'uv' nor Python was found on this system.
        echo [ERROR] Please install uv (https://docs.astral.sh/uv/) or Python 3.12+.
        exit /b 1
    )
    for /f "delims=" %%i in ('%PYTHON_CMD% --version 2^>^&1') do set "PYTHON_VER=%%i"
    echo [SYSTEM] Detected Python executable: %PYTHON_CMD% (%PYTHON_VER%)
)

rem 2. Set up virtual environment and install dependencies
set "VENV_DIR=.venv"

if defined UV_CMD (
    echo [SYSTEM] Creating Python virtual environment using uv in .\%VENV_DIR%...
    uv venv %VENV_DIR%
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment with uv.
        exit /b 1
    )
    echo [SYSTEM] Syncing dependencies using uv...
    if exist "pyproject.toml" (
        uv sync
    ) else (
        uv pip install -r requirements.txt
    )
) else (
    if not exist "%VENV_DIR%" if not exist "venv" (
        echo [SYSTEM] Creating Python virtual environment in .\%VENV_DIR%...
        %PYTHON_CMD% -m venv %VENV_DIR%
        if !errorlevel! neq 0 (
            echo [ERROR] Failed to create virtual environment.
            exit /b 1
        )
    )
    set "ACT_SCRIPT=%VENV_DIR%\Scripts\activate.bat"
    if not exist "!ACT_SCRIPT!" set "ACT_SCRIPT=venv\Scripts\activate.bat"
    if exist "!ACT_SCRIPT!" (
        call "!ACT_SCRIPT!"
    ) else (
        echo [ERROR] Virtual environment activation script not found.
        exit /b 1
    )
    echo [SYSTEM] Installing dependencies using pip fallback...
    python -m pip install -r requirements.txt
)

if %errorlevel% equ 0 (
    echo ==========================================================
    echo [SUCCESS] All dependencies installed successfully.
    echo [SYSTEM] To start the background services, run: deploy\windows\run.bat
    echo ==========================================================
) else (
    echo ==========================================================
    echo [ERROR] Failed to install dependencies.
    echo ==========================================================
    exit /b 1
)
