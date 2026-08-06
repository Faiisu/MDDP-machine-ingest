#!/bin/bash
# See: docs/architecture/context.md
# English comments only

# Resolve project root directory regardless of invocation location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT" || exit 1

DAQ_PID_FILE=".daq.pid"
PORTAL_PID_FILE=".portal.pid"
MUSASHI_II_PID_FILE=".musashi_ii.pid"
MUSASHI_IV_PID_FILE=".musashi_iv.pid"
PLOTTER_PID_FILE=".plotter.pid"
LLM_INTERPRET_PID_FILE=".llm_interpret.pid"

INFLUXDB_MGR_PID_FILE=".influxdb_mgr.pid"

# Safeguard check to prevent starting duplicate instances
if [ -f "$PORTAL_PID_FILE" ] || [ -f "$DAQ_PID_FILE" ] || [ -f "$MUSASHI_II_PID_FILE" ] || [ -f "$MUSASHI_IV_PID_FILE" ] || [ -f "$PLOTTER_PID_FILE" ] || [ -f "$LLM_INTERPRET_PID_FILE" ] || [ -f "$INFLUXDB_MGR_PID_FILE" ]; then
    echo "[SYSTEM] Warning: PID files detected. Services may already be running."
    echo "[SYSTEM] Please run ./deploy/linux/stop.sh before starting again."
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

# 1. Start Service Portal (Port 8080)
echo "[SYSTEM] Starting Service Portal on Port 8080 (all interfaces)..."
nohup $PYTHON_BIN services/portal/app.py >/dev/null 2>&1 &
echo $! > "$PORTAL_PID_FILE"

# 2. Start DAQ USB-4716 Control Panel (Port 8081)
echo "[SYSTEM] Starting DAQ Control Panel on Port 8081 (all interfaces)..."
nohup $PYTHON_BIN services/daq_usb4716/app.py >/dev/null 2>&1 &
echo $! > "$DAQ_PID_FILE"

# 3. Start Musashi II Control Panel (Port 8082)
echo "[SYSTEM] Starting Musashi II Control Panel on Port 8082 (all interfaces)..."
nohup $PYTHON_BIN services/musashi_ii/app.py >/dev/null 2>&1 &
echo $! > "$MUSASHI_II_PID_FILE"

# 4. Start Musashi IV Control Panel (Port 8083)
echo "[SYSTEM] Starting Musashi IV Control Panel on Port 8083 (all interfaces)..."
nohup $PYTHON_BIN services/musashi_iv/app.py >/dev/null 2>&1 &
echo $! > "$MUSASHI_IV_PID_FILE"

# 5. Start Database Plotter (Port 8084)
echo "[SYSTEM] Starting Database Plotter on Port 8084 (all interfaces)..."
nohup $PYTHON_BIN services/plotter/app.py >/dev/null 2>&1 &
echo $! > "$PLOTTER_PID_FILE"

# 6. Start LLM Interpretation Worker (Port 8085)
echo "[SYSTEM] Starting LLM Interpretation Worker on Port 8085 (all interfaces)..."
nohup $PYTHON_BIN services/llm-interpret/app.py >/dev/null 2>&1 &
echo $! > "$LLM_INTERPRET_PID_FILE"

# 7. Start InfluxDB Manager (Port 18085)
echo "[SYSTEM] Starting InfluxDB Manager on Port 18085 (all interfaces)..."
nohup $PYTHON_BIN services/influxdb/app.py >/dev/null 2>&1 &
echo $! > "$INFLUXDB_MGR_PID_FILE"

echo "[SYSTEM] Services launched in background."
echo "[SYSTEM] Portal:      http://localhost:8080"
echo "[SYSTEM] DAQ Control: http://localhost:8081"
echo "[SYSTEM] Musashi II:  http://localhost:8082"
echo "[SYSTEM] Musashi IV:  http://localhost:8083"
echo "[SYSTEM] Plotter:     http://localhost:8084"
echo "[SYSTEM] LLM Interpret: http://localhost:8085"
echo "[SYSTEM] InfluxDB:    http://localhost:18085"
echo "=========================================================="
