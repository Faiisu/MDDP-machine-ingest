#!/bin/bash
# See: docs/architecture/context.md
# English comments only

PORTAL_PID_FILE=".portal.pid"
DAQ_PID_FILE=".daq.pid"
MUSASHI_IV_PID_FILE=".musashi_iv.pid"
PLOTTER_PID_FILE=".plotter.pid"

# Safeguard check to prevent starting duplicate instances
if [ -f "$PORTAL_PID_FILE" ] || [ -f "$DAQ_PID_FILE" ] || [ -f "$MUSASHI_IV_PID_FILE" ] || [ -f "$PLOTTER_PID_FILE" ]; then
    echo "[SYSTEM] Warning: PID files detected. Services may already be running."
    echo "[SYSTEM] Please run ./stop.sh before starting again."
    exit 1
fi

# Resolve Python binary dynamically (prefer virtualenv python over global python)
PYTHON_BIN=""
if [ -f ".venv/bin/python" ]; then
    # Unix .venv python path (uv standard)
    PYTHON_BIN=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    # Unix venv python path
    PYTHON_BIN="venv/bin/python"
elif [ -f ".venv/Scripts/python" ]; then
    # Windows Git Bash .venv python path
    PYTHON_BIN=".venv/Scripts/python"
elif [ -f "venv/Scripts/python" ]; then
    # Windows Git Bash venv python path
    PYTHON_BIN="venv/Scripts/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    PYTHON_BIN="python"
fi

echo "[SYSTEM] Using Python interpreter: $PYTHON_BIN"

echo "=========================================================="
echo "         MDDP Ingestion Control Suite Startup"
echo "=========================================================="

# 1. Start Main Portal Gateway (Port 8080)
echo "[SYSTEM] Starting Ingestion Portal on Port 8080 (all interfaces)..."
$PYTHON_BIN -m http.server 8080 --directory portal >/dev/null 2>&1 &
echo $! > "$PORTAL_PID_FILE"

# 2. Start DAQ USB-4716 Control Panel (Port 8081)
echo "[SYSTEM] Starting DAQ Control Panel on Port 8081 (all interfaces)..."
$PYTHON_BIN USB4716/web_gui.py >/dev/null 2>&1 &
echo $! > "$DAQ_PID_FILE"

# 3. Start Musashi IV Control Panel (Port 8083)
echo "[SYSTEM] Starting Musashi IV Control Panel on Port 8083 (all interfaces)..."
$PYTHON_BIN mushashi_IV/web_gui.py >/dev/null 2>&1 &
echo $! > "$MUSASHI_IV_PID_FILE"

# 4. Start Database Plotter (Port 8084)
echo "[SYSTEM] Starting Database Plotter on Port 8084 (all interfaces)..."
$PYTHON_BIN plot_service/app.py >/dev/null 2>&1 &
echo $! > "$PLOTTER_PID_FILE"

echo "[SYSTEM] Services launched in background."
echo "[SYSTEM] Accessible locally at http://localhost:8080"
echo "[SYSTEM] Accessible network-wide at http://<HOST_IP>:8080"
echo "=========================================================="
