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

echo ==========================================================
echo          MDDP Ingestion Control Suite Shutdown
echo ==========================================================

rem 1. Stop Main Portal Gateway
echo [SYSTEM] Stopping Ingestion Portal...
taskkill /fi "WINDOWTITLE eq MDDP_PORTAL_HUB*" /t /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":8080 .*LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
if exist "%PORTAL_PID_FILE%" del "%PORTAL_PID_FILE%"

rem 2. Stop DAQ Control Panel
echo [SYSTEM] Stopping DAQ Control Panel...
taskkill /fi "WINDOWTITLE eq MDDP_DAQ_PANEL*" /t /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":8081 .*LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
if exist "%DAQ_PID_FILE%" del "%DAQ_PID_FILE%"

rem 3. Stop Musashi II Control Panel
echo [SYSTEM] Stopping Musashi II Control Panel...
taskkill /fi "WINDOWTITLE eq MDDP_MUSASHI_II_PANEL*" /t /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":8082 .*LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
if exist "%MUSASHI_II_PID_FILE%" del "%MUSASHI_II_PID_FILE%"

rem 4. Stop Musashi IV Control Panel
echo [SYSTEM] Stopping Musashi IV Control Panel...
taskkill /fi "WINDOWTITLE eq MDDP_MUSASHI_IV_PANEL*" /t /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":8083 .*LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
if exist "%MUSASHI_IV_PID_FILE%" del "%MUSASHI_IV_PID_FILE%"

rem 4. Stop Telemetry Visualizer
echo [SYSTEM] Stopping Telemetry Visualizer...
taskkill /fi "WINDOWTITLE eq MDDP_PLOTTER_SERVICE*" /t /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":8084 .*LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
if exist "%PLOTTER_PID_FILE%" del "%PLOTTER_PID_FILE%"

rem 6. Stop InfluxDB Manager
echo [SYSTEM] Stopping InfluxDB Manager...
taskkill /fi "WINDOWTITLE eq MDDP_INFLUXDB_MANAGER*" /t /f >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr /r /c:":8085 .*LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
if exist "%INFLUXDB_MGR_PID_FILE%" del "%INFLUXDB_MGR_PID_FILE%"

echo [SYSTEM] Shutdown sequence completed.
echo ==========================================================
