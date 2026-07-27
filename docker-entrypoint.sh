#!/bin/bash
set -e

echo "=========================================================="
echo "    MDDP Ingestion Control Suite - Docker Container"
echo "=========================================================="

# Ensure logs directory exists
mkdir -p /app/logs

# 1. Start Main Portal Gateway (Port 8080)
echo "[SYSTEM] Starting Ingestion Portal on Port 8080..."
python3 -m http.server 8080 --directory portal > /app/logs/portal.log 2>&1 &

# 2. Start DAQ USB-4716 Control Panel (Port 8081)
echo "[SYSTEM] Starting DAQ Control Panel on Port 8081..."
python3 USB4716/web_gui.py > /app/logs/daq_panel.log 2>&1 &

# 3. Start Musashi IV Control Panel (Port 8083)
echo "[SYSTEM] Starting Musashi IV Control Panel on Port 8083..."
python3 mushashi_IV/web_gui.py > /app/logs/musashi_iv.log 2>&1 &

# 4. Start Database Plotter (Port 8084)
echo "[SYSTEM] Starting Database Plotter on Port 8084..."
python3 plot_service/app.py > /app/logs/plotter.log 2>&1 &

echo "=========================================================="
echo "[SYSTEM] All services successfully launched inside container."
echo "[SYSTEM] Listening on ports: 8080, 8081, 8083, 8084"
echo "=========================================================="

# Tail all logs to stdout to keep container running and output observable via `docker logs`
exec tail -f /app/logs/*.log
