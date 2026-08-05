@echo off
rem See: docs/architecture/context.md
rem English comments only

cd /d "%~dp0..\.."

set "PORTAL_PID_FILE=.portal.pid"
set "DAQ_PID_FILE=.daq.pid"
set "MUSASHI_II_PID_FILE=.musashi_ii.pid"
set "MUSASHI_IV_PID_FILE=.musashi_iv.pid"
set "PLOTTER_PID_FILE=.plotter.pid"
set "INFLUXDB_MGR_PID_FILE=.influxdb_mgr.pid"

rem Safeguard check to prevent starting duplicate instances
if exist "%PORTAL_PID_FILE%" goto :already_running
if exist "%DAQ_PID_FILE%" goto :already_running
if exist "%MUSASHI_II_PID_FILE%" goto :already_running
if exist "%MUSASHI_IV_PID_FILE%" goto :already_running
if exist "%PLOTTER_PID_FILE%" goto :already_running
if exist "%INFLUXDB_MGR_PID_FILE%" goto :already_running
goto :start_services

:already_running
echo [SYSTEM] Warning: PID files detected. Services may already be running.
echo [SYSTEM] Please run deploy\windows\stop.bat before starting again.
exit /b 1

:start_services
rem Resolve Python binary dynamically (prefer virtualenv python over global python)
set "PYTHON_BIN="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_BIN=.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "PYTHON_BIN=venv\Scripts\python.exe"
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_BIN=python"
    ) else (
        where py >nul 2>nul
        if %errorlevel% equ 0 (
            set "PYTHON_BIN=py"
        ) else (
            echo [ERROR] Python was not found on this system.
            exit /b 1
        )
    )
)

echo [SYSTEM] Using Python interpreter: %PYTHON_BIN%

rem Create logs directory
if not exist "logs" mkdir "logs"

echo ==========================================================
echo          MDDP Ingestion Control Suite Startup
echo ==========================================================

rem 1. Start Main Portal Gateway (Port 8080)
echo [SYSTEM] Starting Ingestion Portal on Port 8080 (all interfaces)...
start "MDDP_PORTAL_HUB" /min cmd /c "title MDDP_PORTAL_HUB && %PYTHON_BIN% services\portal\app.py >> logs\portal.log 2>&1"
echo 1 > "%PORTAL_PID_FILE%"

rem 2. Start DAQ USB-4716 Control Panel (Port 8081)
echo [SYSTEM] Starting DAQ Control Panel on Port 8081 (all interfaces)...
start "MDDP_DAQ_PANEL" /min cmd /c "title MDDP_DAQ_PANEL && %PYTHON_BIN% services\daq_usb4716\app.py >> logs\daq_panel.log 2>&1"
echo 1 > "%DAQ_PID_FILE%"

rem 3. Start Musashi II Control Panel (Port 8082)
echo [SYSTEM] Starting Musashi II Control Panel on Port 8082 (all interfaces)...
start "MDDP_MUSASHI_II_PANEL" /min cmd /c "title MDDP_MUSASHI_II_PANEL && %PYTHON_BIN% services\musashi_ii\app.py >> logs\musashi_ii_panel.log 2>&1"
echo 1 > "%MUSASHI_II_PID_FILE%"

rem 4. Start Musashi IV Control Panel (Port 8083)
echo [SYSTEM] Starting Musashi IV Control Panel on Port 8083 (all interfaces)...
start "MDDP_MUSASHI_IV_PANEL" /min cmd /c "title MDDP_MUSASHI_IV_PANEL && %PYTHON_BIN% services\musashi_iv\app.py >> logs\musashi_iv_panel.log 2>&1"
echo 1 > "%MUSASHI_IV_PID_FILE%"

rem 5. Start Database Plotter (Port 8084)
echo [SYSTEM] Starting Database Plotter on Port 8084 (all interfaces)...
start "MDDP_PLOTTER_SERVICE" /min cmd /c "title MDDP_PLOTTER_SERVICE && %PYTHON_BIN% services\plotter\app.py >> logs\plotter.log 2>&1"
echo 1 > "%PLOTTER_PID_FILE%"

rem 6. Start InfluxDB Manager (Port 8085)
echo [SYSTEM] Starting InfluxDB Manager on Port 8085 (all interfaces)...
start "MDDP_INFLUXDB_MANAGER" /min cmd /c "title MDDP_INFLUXDB_MANAGER && %PYTHON_BIN% services\influxdb\app.py >> logs\influxdb_manager.log 2>&1"
echo 1 > "%INFLUXDB_MGR_PID_FILE%"

echo [SYSTEM] Services launched in background.
echo [SYSTEM] Accessible locally at http://localhost:8080
echo [SYSTEM] Accessible network-wide at http://^<HOST_IP^>:8080
echo [SYSTEM] Logs directory: logs\
echo ==========================================================
