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

echo "=========================================================="
echo "         MDDP Ingestion Control Suite Shutdown"
echo "=========================================================="

# 1. Stop Service Portal
if [ -f "$PORTAL_PID_FILE" ]; then
    PID=$(cat "$PORTAL_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping Service Portal (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] Service Portal process not found."
    fi
    rm "$PORTAL_PID_FILE"
else
    echo "[SYSTEM] Service Portal is already stopped."
fi

# 2. Stop DAQ Control Panel
if [ -f "$DAQ_PID_FILE" ]; then
    PID=$(cat "$DAQ_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping DAQ Control Panel (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] DAQ Control Panel process not found."
    fi
    rm "$DAQ_PID_FILE"
else
    echo "[SYSTEM] DAQ Control Panel is already stopped."
fi

# 3. Stop Musashi II Control Panel
if [ -f "$MUSASHI_II_PID_FILE" ]; then
    PID=$(cat "$MUSASHI_II_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping Musashi II Control Panel (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] Musashi II Control Panel process not found."
    fi
    rm "$MUSASHI_II_PID_FILE"
else
    echo "[SYSTEM] Musashi II Control Panel is already stopped."
fi

# 4. Stop Musashi IV Control Panel
if [ -f "$MUSASHI_IV_PID_FILE" ]; then
    PID=$(cat "$MUSASHI_IV_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping Musashi IV Control Panel (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] Musashi IV Control Panel process not found."
    fi
    rm "$MUSASHI_IV_PID_FILE"
else
    echo "[SYSTEM] Musashi IV Control Panel is already stopped."
fi

# 5. Stop Telemetry Visualizer
if [ -f "$PLOTTER_PID_FILE" ]; then
    PID=$(cat "$PLOTTER_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping Telemetry Visualizer (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] Telemetry Visualizer process not found."
    fi
    rm "$PLOTTER_PID_FILE"
else
    echo "[SYSTEM] Telemetry Visualizer is already stopped."
fi

# 6. Stop LLM Interpretation Worker
if [ -f "$LLM_INTERPRET_PID_FILE" ]; then
    PID=$(cat "$LLM_INTERPRET_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping LLM Interpretation Worker (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] LLM Interpretation Worker process not found."
    fi
    rm "$LLM_INTERPRET_PID_FILE"
else
    echo "[SYSTEM] LLM Interpretation Worker is already stopped."
fi

# 7. Stop InfluxDB Manager
if [ -f "$INFLUXDB_MGR_PID_FILE" ]; then
    PID=$(cat "$INFLUXDB_MGR_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping InfluxDB Manager (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] InfluxDB Manager process not found."
    fi
    rm "$INFLUXDB_MGR_PID_FILE"
else
    echo "[SYSTEM] InfluxDB Manager is already stopped."
fi

echo "[SYSTEM] Shutdown sequence completed."
echo "=========================================================="
