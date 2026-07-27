#!/bin/bash
# See: docs/architecture/context.md
# English comments only

# Resolve project root directory regardless of invocation location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT" || exit 1

PORTAL_PID_FILE=".portal.pid"
DAQ_PID_FILE=".daq.pid"
MUSASHI_II_PID_FILE=".musashi_ii.pid"
MUSASHI_IV_PID_FILE=".musashi_iv.pid"
PLOTTER_PID_FILE=".plotter.pid"

echo "=========================================================="
echo "         MDDP Ingestion Control Suite Shutdown"
echo "=========================================================="

# 1. Stop Main Portal Gateway
if [ -f "$PORTAL_PID_FILE" ]; then
    PID=$(cat "$PORTAL_PID_FILE")
    if ps -p "$PID" >/dev/null 2>&1; then
        echo "[SYSTEM] Stopping Ingestion Portal (PID: $PID)..."
        kill "$PID" 2>/dev/null
    else
        echo "[SYSTEM] Ingestion Portal process not found."
    fi
    rm "$PORTAL_PID_FILE"
else
    echo "[SYSTEM] Ingestion Portal is already stopped."
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

# 4. Stop Telemetry Visualizer
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

echo "[SYSTEM] Shutdown sequence completed."
echo "=========================================================="
