# MDDP Ingestion Control Suite — Windows Deployment Guide

This document provides step-by-step instructions for deploying the MDDP Ingestion Control Suite on **Windows 10/11** with the **Advantech USB-4716 DAQ** hardware attached, running all services as **background tasks** for unattended 24-hour operation.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Database & Broker Setup](#2-database--broker-setup)
3. [Project Setup](#3-project-setup)
4. [Manual Startup (Testing)](#4-manual-startup-testing)
5. [24-Hour Background Operation (Task Scheduler)](#5-24-hour-background-operation-task-scheduler)
6. [Watchdog & Crash Recovery](#6-watchdog--crash-recovery)
7. [Windows Firewall Configuration](#7-windows-firewall-configuration)
8. [Configuration Reference](#8-configuration-reference)
9. [Log Management](#9-log-management)
10. [Troubleshooting](#10-troubleshooting)
11. [Uninstalling](#11-uninstalling)

---

## 1. Prerequisites

Before starting deployment, ensure the following are installed on the Windows machine:

### Required Software

| Software | Version | Purpose | Download |
|:---|:---|:---|:---|
| **Python** | 3.12 or higher | Runtime for all backend services | [python.org/downloads](https://www.python.org/downloads/) |
| **Advantech DAQNavi SDK** | Latest | USB-4716 hardware driver (Real Hardware Mode) | [Advantech Support](https://www.advantech.com/en/support/details/driver?id=1-RNKLZI) |
| **Git** *(optional)* | Latest | Clone project repository | [git-scm.com](https://git-scm.com/) |

### Required Infrastructure

- **PostgreSQL 16 with TimescaleDB** (Time-series database engine)
- **Mosquitto MQTT Broker** (Optional: only needed if using MQTT output mode)

### Python Installation Notes

> ⚠️ **Important**: During Python installation, **check "Add Python to PATH"** and **check "Install for all users"**. This ensures Python is accessible from batch scripts and Task Scheduler.

Verify installation:
```cmd
python --version
pip --version
```

### Advantech DAQNavi SDK Installation

1. Download and install the **DAQNavi SDK** from the Advantech Support website.
2. After installation, verify the USB-4716 device appears in **Advantech Navigator** (installed with the SDK).
3. Note the device description string (default: `USB-4716,BID#0`) — this must match `DEVICE_DESCRIPTION` in `services\daq_usb4716\config.json`.

---

## 2. Database & Broker Setup

The suite requires two infrastructure services:

- **TimescaleDB** (PostgreSQL with time-series extensions) — port `5432`
- **Mosquitto MQTT Broker** — port `1883` *(only if using MQTT destination mode)*

### PostgreSQL 16 with TimescaleDB Installation

1. Download PostgreSQL 16 from [postgresql.org/download/windows](https://www.postgresql.org/download/windows/).
2. Run the installer with default settings. Remember the password you set for the `postgres` superuser.
3. Add TimescaleDB extension:
   - Download TimescaleDB from [docs.timescale.com/install](https://docs.timescale.com/self-hosted/latest/install/installation-windows/).
   - Follow the "Self-hosted → Windows" installation guide.

4. Create the database and user:

Open **pgAdmin** or **psql** and run:
```sql
CREATE USER admin WITH PASSWORD 'admin';
CREATE DATABASE daq_db OWNER admin;
GRANT ALL PRIVILEGES ON DATABASE daq_db TO admin;

-- Connect to daq_db
\c daq_db

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create main data table
CREATE TABLE IF NOT EXISTS daq_samples (
    time        TIMESTAMPTZ      NOT NULL,
    channel     SMALLINT         NOT NULL,
    value       DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable('daq_samples', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_daq_channel_time
    ON daq_samples (channel, time DESC);

-- Session metadata table
CREATE TABLE IF NOT EXISTS daq_sessions (
    id            SERIAL PRIMARY KEY,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    stopped_at    TIMESTAMPTZ,
    channel_count SMALLINT    NOT NULL,
    clock_rate_hz INTEGER     NOT NULL,
    notes         TEXT
);
```

5. Configure PostgreSQL to accept local connections:
   - Edit `pg_hba.conf` (typically at `C:\Program Files\PostgreSQL\16\data\pg_hba.conf`)
   - Ensure this line exists: `host all all 127.0.0.1/32 md5`
   - Restart PostgreSQL service via `services.msc`.

#### Install Mosquitto MQTT Broker (Optional)

Only needed if `DESTINATION` in `config.json` is set to `mqtt`.

1. Download from [mosquitto.org/download](https://mosquitto.org/download/).
2. Install with default settings.
3. Edit `mosquitto.conf` (typically at `C:\Program Files\mosquitto\mosquitto.conf`):
   ```
   listener 1883
   allow_anonymous true
   ```
4. Start the Mosquitto service:
   ```cmd
   net start mosquitto
   ```

#### Configure PostgreSQL as a Windows Service

PostgreSQL installs as a Windows Service by default. Verify:
```cmd
sc query postgresql-x64-16
```

Ensure it's set to **Automatic** startup:
```cmd
sc config postgresql-x64-16 start= auto
```

---

## 3. Project Setup

### Clone or Copy the Project

```cmd
git clone <repository-url> C:\MDDP
cd C:\MDDP
```

Or copy the project folder to `C:\MDDP` (or any directory of your choice).

### Install Python Dependencies

```cmd
install_deps.bat
:: Or directly:
:: deploy\windows\install_deps.bat
```

This will:
1. Detect your `uv` or Python installation
2. Create a virtual environment (`.venv\`)
3. Install and sync all dependencies from `pyproject.toml` / `requirements.txt` using `uv`

**Expected output:**
```
[SYSTEM] Detected uv package manager: uv 0.7.x
[SYSTEM] Creating Python virtual environment using uv in .\.venv...
[SYSTEM] Syncing dependencies using uv...
[SUCCESS] All dependencies installed successfully.
```

### Update Configuration

Edit `services\daq_usb4716\config.json` to match your environment:

```json
{
  "DEVICE_DESCRIPTION": "USB-4716,BID#0",
  "DB_DSN": "postgresql://admin:admin@localhost:5432/daq_db",
  "MOCKUP_DB_DSN": "postgresql://admin:admin@localhost:5432/daq_db",
  "DESTINATION": "database"
}
```

> 💡 **Tip**: If the database is running on a different machine, replace `localhost` with the IP address of that machine.

---

## 4. Manual Startup (Testing)

Before configuring automatic background operation, verify everything works manually.

### Start Services

```cmd
deploy\windows\run.bat
```

> **Note:** The portal at port `8080` is the entry point for all service consoles. Its links use the current browser host, so a portal opened at `http://192.168.1.20:8080` targets `http://192.168.1.20:8081`, `:8082`, and so on.

**Expected output:**
```
[SYSTEM] Using Python interpreter: .venv\Scripts\python.exe
==========================================================
         MDDP Ingestion Control Suite Startup
==========================================================
[SYSTEM] Starting Ingestion Portal on Port 8080...
[SYSTEM] Starting DAQ Control Panel on Port 8081...
[SYSTEM] Starting Musashi II Control Panel on Port 8082...
[SYSTEM] Starting Musashi IV Control Panel on Port 8083...
[SYSTEM] Starting Database Plotter on Port 8084...
[SYSTEM] Starting InfluxDB Manager on Port 8085...
[SYSTEM] Services launched in background.
[SYSTEM] Logs directory: logs\
[SYSTEM] Accessible locally at http://localhost:8080
==========================================================
```

### Verify Services

1. Open browser → [http://localhost:8080](http://localhost:8080) (Portal Gateway)
2. Click **LAUNCH PANEL** on the DAQ USB-4716 row → should open [http://localhost:8081](http://localhost:8081)
3. Verify the Plotter at [http://localhost:8084](http://localhost:8084)

Check port status:
```cmd
netstat -an | findstr "LISTENING" | findstr "8080 8081 8082 8083 8084 8085"
```

### Check Logs

Service logs are stored in the `logs\` directory:
```
logs\portal.log
logs\daq_panel.log
logs\musashi_iv_panel.log
logs\plotter.log
```

### Stop Services

```cmd
deploy\windows\stop.bat
```

---

## 5. 24-Hour Background Operation (Task Scheduler)

For continuous unattended operation, we use **Windows Task Scheduler** to:
- Auto-start all services when the PC boots (before user login)
- Run a watchdog every 5 minutes to restart any crashed services

### Setup (One-Time — Requires Administrator)

1. Open **PowerShell as Administrator** (right-click PowerShell → "Run as administrator")
2. Navigate to the project directory:
   ```powershell
   cd C:\MDDP
   ```
3. Allow script execution (if not already enabled):
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```
4. Run the setup script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\deploy\windows\setup_task_scheduler.ps1
   ```

**Expected output:**
```
============================================================
  MDDP Task Scheduler Setup
============================================================
[OK] Created task: MDDP_StartServices (runs on system startup)
[OK] Created task: MDDP_Watchdog (runs every 5 minutes)
============================================================
  Setup complete! Services will auto-start on next reboot.
  To test immediately, run: run.bat
============================================================
```

### Verify Scheduled Tasks

Open **Task Scheduler** (search "Task Scheduler" in Start menu):
- Look for `MDDP_StartServices` and `MDDP_Watchdog` in the task list
- Right-click → **Run** to test manually

### How It Works

```
 ┌─────────────────────┐     ┌─────────────────────────┐
 │ Windows Boot        │     │ Every 5 Minutes         │
 │                     │     │                         │
 │ Task Scheduler      │     │ Task Scheduler          │
 │ runs run.bat        │     │ runs watchdog.ps1       │
 │                     │     │                         │
 │ ┌─ Portal :8080     │     │ ┌─ Check :8080 alive?   │
 │ ├─ DAQ    :8081     │     │ ├─ Check :8081 alive?   │
 │ ├─ Musashi:8083     │     │ ├─ Check :8083 alive?   │
 │ └─ Plotter:8084     │     │ └─ Check :8084 alive?   │
 └─────────────────────┘     │                         │
                              │ If DOWN → restart it    │
                              │ Log to watchdog.log     │
                              └─────────────────────────┘
```

---

## 6. Watchdog & Crash Recovery

The watchdog script (`watchdog.ps1`) runs every 5 minutes and:

1. **Checks** if each service port (8080, 8081, 8082, 8083, 8084, 8085) has an active TCP listener
2. **Restarts** any service that is down by spawning a new background process
3. **Logs** all actions to `logs\watchdog.log` with timestamps

### Manual Watchdog Check

Run the watchdog manually to verify it works:
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\watchdog.ps1
```

### View Watchdog Log

```cmd
type logs\watchdog.log
```

Example output:
```
2026-07-21 23:15:00 [HEARTBEAT] All services UP (8080, 8081, 8082, 8083, 8084, 8085)
2026-07-21 23:20:00 [HEARTBEAT] All services UP (8080, 8081, 8082, 8083, 8084, 8085)
2026-07-21 23:25:00 [RESTART] DAQ Panel (8081) was DOWN — restarted
2026-07-21 23:30:00 [HEARTBEAT] All services UP (8080, 8081, 8082, 8083, 8084, 8085)
```

---

## 7. Windows Firewall Configuration

If you need to access the services from other machines on the network, create inbound firewall rules:

### Using PowerShell (As Administrator)

```powershell
# Portal Gateway
New-NetFirewallRule -DisplayName "MDDP Portal (8080)" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow

# DAQ Control Panel
New-NetFirewallRule -DisplayName "MDDP DAQ Panel (8081)" -Direction Inbound -Protocol TCP -LocalPort 8081 -Action Allow

# Musashi II Control Panel
New-NetFirewallRule -DisplayName "MDDP Musashi II (8082)" -Direction Inbound -Protocol TCP -LocalPort 8082 -Action Allow

# Musashi IV Control Panel
New-NetFirewallRule -DisplayName "MDDP Musashi IV (8083)" -Direction Inbound -Protocol TCP -LocalPort 8083 -Action Allow

# Database Plotter
New-NetFirewallRule -DisplayName "MDDP Plotter (8084)" -Direction Inbound -Protocol TCP -LocalPort 8084 -Action Allow

# InfluxDB Manager
New-NetFirewallRule -DisplayName "MDDP InfluxDB Manager (8085)" -Direction Inbound -Protocol TCP -LocalPort 8085 -Action Allow
```

### Using Windows Defender Firewall GUI

1. Open **Windows Defender Firewall with Advanced Security** (search in Start menu)
2. Click **Inbound Rules** → **New Rule...**
3. Select **Port** → **TCP** → Enter port number (e.g., `8080`)
4. Select **Allow the connection**
5. Apply to all profiles (Domain, Private, Public)
6. Name the rule (e.g., "MDDP Portal 8080")
7. Repeat for ports 8081, 8083, 8084

---

## 8. Configuration Reference

### services\daq_usb4716\config.json — Key Parameters

| Parameter | Default | Description |
|:---|:---|:---|
| `DEVICE_DESCRIPTION` | `USB-4716,BID#0` | DAQ hardware identifier |
| `DESTINATION` | `database` | Output mode: `database` or `mqtt` |
| `DB_DSN` | `postgresql://admin:admin@172.21.108.86:5432/daq_db` | Production database DSN |
| `MOCKUP_DB_DSN` | `postgresql://admin:admin@localhost:5432/daq_db` | Local testing database DSN |
| `CLOCK_RATE` | `2000` | Samples per second per channel |
| `CHANNEL_COUNT` | `1` | Number of analog channels to scan |
| `SECTION_LENGTH` | `500` | Batch buffer size |

### Service Ports

| Service | Port | Script |
|:---|:---|:---|
| Portal Gateway | 8080 | `services\portal\app.py` |
| DAQ Control Panel | 8081 | `services\daq_usb4716\app.py` |
| Musashi II Panel | 8082 | `services\musashi_ii\app.py` |
| Musashi IV Panel | 8083 | `services\musashi_iv\app.py` |
| Plotter Visualizer | 8084 | `services\plotter\app.py` |
| InfluxDB Manager | 8085 | `services\influxdb\app.py` |

---

## 9. Log Management

### Log File Locations

| Log | Path | Contents |
|:---|:---|:---|
| Portal Log | `logs\portal.log` | Flask portal and service-probe log |
| DAQ Panel Log | `logs\daq_panel.log` | Flask-SocketIO server log |
| DAQ Pipeline | `services\daq_usb4716\daq_pipeline.log` | Ingestion pipeline stats & errors |
| Musashi II Panel | `logs\musashi_ii_panel.log` | Flask-SocketIO server log |
| Musashi II Pipeline | `services\musashi_ii\musashi_ii_pipeline.log` | Musashi II ingestion stats |
| Musashi IV Panel | `logs\musashi_iv_panel.log` | Flask-SocketIO server log |
| Musashi Pipeline | `services\musashi_iv\musashi_iv_pipeline.log` | Musashi IV ingestion stats |
| Plotter Log | `logs\plotter.log` | Flask API server log |
| InfluxDB Manager | `logs\influxdb_manager.log` | InfluxDB control service log |

### Log Rotation (Recommended)

For 24-hour continuous operation, logs can grow large. Implement manual log rotation by adding to `watchdog.ps1` or running periodically:

```powershell
# Rotate logs older than 7 days
Get-ChildItem -Path "logs" -Filter "*.log" | Where-Object {
    $_.Length -gt 50MB
} | ForEach-Object {
    $newName = $_.BaseName + "_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log"
    Rename-Item $_.FullName -NewName $newName
}
```

---

## 10. Troubleshooting

### ⚠️ Port Conflict

**Symptom**: `[SYSTEM] Warning: PID files detected` or `OSError: [WinError 10048] address already in use`

**Solution**:
```cmd
rem Stop all MDDP services
deploy\windows\stop.bat

rem Force-kill any remaining processes on MDDP ports
for /f "tokens=5" %a in ('netstat -aon ^| findstr ":8080.*LISTENING"') do taskkill /f /pid %a
for /f "tokens=5" %a in ('netstat -aon ^| findstr ":8081.*LISTENING"') do taskkill /f /pid %a
for /f "tokens=5" %a in ('netstat -aon ^| findstr ":8083.*LISTENING"') do taskkill /f /pid %a
for /f "tokens=5" %a in ('netstat -aon ^| findstr ":8084.*LISTENING"') do taskkill /f /pid %a

rem Delete stale PID files
del .portal.pid .daq.pid .musashi_iv.pid .plotter.pid 2>nul
```

### ⚠️ TimescaleDB Connection Timeout

**Symptom**: `psycopg2.OperationalError: connection to server failed: Connection timed out`

**Solution**:
- Verify PostgreSQL service status: `sc query postgresql-x64-16` — verify the service is running
- Verify the DSN in `services\daq_usb4716\config.json` points to the correct host/port
- Test connectivity: `psql -h localhost -U admin -d daq_db`

### ⚠️ Python Not Found

**Symptom**: `[ERROR] Python was not found on this system.`

**Solution**:
1. Verify Python is installed: `python --version` or `py --version`
2. If installed but not in PATH, add Python to the system PATH:
   - Open **System Properties** → **Advanced** → **Environment Variables**
   - Edit `Path` → Add `C:\Python311\` and `C:\Python311\Scripts\` (adjust version)
3. Restart Command Prompt after modifying PATH

### ⚠️ Advantech DAQ Device Not Found

**Symptom**: `DAQ prepare() failed — check device connection and profile.xml`

**Solution**:
1. Open **Advantech Navigator** and verify USB-4716 appears in the device list
2. Check `DEVICE_DESCRIPTION` in `services\daq_usb4716\config.json` matches exactly (e.g., `USB-4716,BID#0`)
3. Try resetting the USB connection (unplug/replug the USB cable)
4. Verify the DAQNavi Python package is installed: `uv pip show advantech-AutomationBDaq`

### ⚠️ Task Scheduler Task Fails to Start

**Symptom**: Task shows "Last Run Result: 0x1" in Task Scheduler

**Solution**:
1. Check the task's **"Start in"** field is set to the project directory (e.g., `C:\MDDP`)
2. Ensure the SYSTEM account has read/write permissions on the project directory
3. Run the task manually from an elevated Command Prompt to see error output:
   ```cmd
   cd C:\MDDP
   deploy\windows\run.bat
   ```

### ⚠️ Eventlet/SocketIO Warning

**Symptom**: `[WARNING] Eventlet initialization warning: ...`

**Solution**: This is usually non-fatal. If WebSocket features are broken:
```cmd
uv pip install --upgrade eventlet flask-socketio
```

---

## 11. Uninstalling

### Remove Task Scheduler Tasks

Open **PowerShell as Administrator** and run:
```powershell
cd C:\MDDP
powershell -ExecutionPolicy Bypass -File .\deploy\windows\remove_task_scheduler.ps1
```

### Stop All Services

```cmd
deploy\windows\stop.bat
```

### Remove Firewall Rules (If Created)

```powershell
Remove-NetFirewallRule -DisplayName "MDDP Portal (8080)"
Remove-NetFirewallRule -DisplayName "MDDP DAQ Panel (8081)"
Remove-NetFirewallRule -DisplayName "MDDP Musashi IV (8083)"
Remove-NetFirewallRule -DisplayName "MDDP Plotter (8084)"
```

### Delete Project Files

```cmd
rmdir /s /q C:\MDDP
```
