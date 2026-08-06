# MDDP Ingestion Control Suite — Linux Shell & Systemd Deployment Guide

This document provides step-by-step instructions for deploying the MDDP Ingestion Control Suite on **Linux (Ubuntu/Debian)** using native shell scripts (`deploy/linux/install_deps.sh`, `run.sh`, `stop.sh`), with support for physical **Advantech USB-4716 DAQ** hardware, serial devices, **systemd 24/7 autostart**, and **ingestion state persistence across reboots**.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Database & Broker Setup](#2-database--broker-setup)
3. [Project Setup & Dependencies](#3-project-setup--dependencies)
4. [Service Startup & Management](#4-service-startup--management)
5. [24/7 Linux Boot Autostart (Systemd)](#5-247-linux-boot-autostart-systemd)
6. [Ingestion State Persistence Across Reboots](#6-ingestion-state-persistence-across-reboots)
7. [Hardware Layer Connectivity (USB & Serial)](#7-hardware-layer-connectivity-usb--serial)
8. [Service Access & Verification](#8-service-access--verification)
9. [Viewing Logs & Diagnostics](#9-viewing-logs--diagnostics)
10. [Stopping Services](#10-stopping-services)

---

## 1. Prerequisites

Before starting deployment on Linux, ensure the following are installed:

- **Python** (v3.12 or higher)
- **uv** (Recommended package manager) or standard `python3-venv` + `pip`
- **Git** (to clone repository)
- **Advantech DAQNavi SDK for Linux** (for real USB-4716 hardware mode)

Verify Python / uv installation:
```bash
python3 --version
uv --version  # optional but recommended
```

---

## 2. Database & Broker Setup

The suite requires access to a **TimescaleDB / PostgreSQL** instance and optionally an **MQTT Broker** (e.g. Mosquitto):

1. **TimescaleDB**: Install native `postgresql` + `timescaledb` extension or connect to a remote PostgreSQL server.
2. **Mosquitto MQTT**: Install via `sudo apt install mosquitto mosquitto-clients` (if using MQTT destination mode).

Ensure database and tables are created (see `db_setup.sql` or configuration guide).

---

## 3. Project Setup & Dependencies

1. Clone or copy the project repository to your target directory:
   ```bash
   cd ~/DAQ-USB-4716
   ```

2. Install project dependencies:
   ```bash
   ./deploy/linux/install_deps.sh
   ```

This will automatically create a virtual environment (`.venv`) and install all required dependencies.

---

## 4. Service Startup & Management

Launch the MDDP application suite in background mode:

```bash
./deploy/linux/run.sh
```

**Expected Output:**
```
==========================================================
         MDDP Ingestion Control Suite Startup
==========================================================
[SYSTEM] Using Python interpreter: .venv/bin/python
[SYSTEM] Starting Service Portal on Port 8080 (all interfaces)...
[SYSTEM] Starting DAQ Control Panel on Port 8081 (all interfaces)...
[SYSTEM] Starting Musashi II Control Panel on Port 8082 (all interfaces)...
[SYSTEM] Starting Musashi IV Control Panel on Port 8083 (all interfaces)...
[SYSTEM] Starting Database Plotter on Port 8084 (all interfaces)...
[SYSTEM] Starting LLM Interpretation Worker on Port 8085 (all interfaces)...
[SYSTEM] Starting InfluxDB Manager on Port 18085 (all interfaces)...
[SYSTEM] Services launched in background.
[SYSTEM] Portal:      http://localhost:8080
[SYSTEM] InfluxDB manager at http://localhost:18085
==========================================================
```

---

## 5. 24/7 Linux Boot Autostart (Systemd)

To ensure MDDP services automatically launch when the Linux system boots up or reboots:

1. Run the systemd setup script (requires `sudo` privileges):
   ```bash
   ./deploy/linux/setup_systemd.sh
   ```

2. Manage the service via standard `systemctl` commands:
   ```bash
   # Check service status
   sudo systemctl status mddp

   # Start service manually
   sudo systemctl start mddp

   # Stop service manually
   sudo systemctl stop mddp

   # Restart service
   sudo systemctl restart mddp
   ```

---

## 6. Ingestion State Persistence Across Reboots

The MDDP suite features **automatic ingestion state recovery**:

- When DAQ or Musashi IV stream ingestion is started via the Web UI (in either `REAL` or `MOCKUP` mode), the desired state is written to a persistent file.
- When the Linux machine restarts (or power-cycles), the systemd service starts `deploy/linux/run.sh` and boots up the Web GUIs.
- The Web GUIs check the persistent state and **automatically resume telemetry ingestion** in the exact same mode (`REAL` or `MOCKUP`) as before the reboot!

If ingestion was stopped by the user prior to reboot, it remains in the idle/ready state after boot.

---

## 7. Hardware Layer Connectivity (USB & Serial)

The shell-based deployment supports both **Mockup Mode** (driverless simulation) and **Real Hardware Mode**:

### A. Mockup Mode (Software Simulation)
No physical hardware or driver configuration is required. Select Mockup mode from the web UI ([http://localhost:8081](http://localhost:8081)).

### B. Real USB Hardware Mode (Advantech USB-4716 DAQ)
Ensure Advantech DAQNavi drivers (`libbiodaq.so`) are installed on your Linux system (`/usr/lib` or `/usr/local/lib`) and user has permissions for `/dev/bdaq*` or USB devices:
```bash
sudo usermod -aG dialout,plugdev $USER
```

### C. Real Serial Port Mode (Musashi IV RS-232 Controller)
Ensure serial device permissions (`/dev/ttyUSB0` or `/dev/ttyACM0`):
```bash
sudo chmod 666 /dev/ttyUSB0
```

---

## 8. Service Access & Verification

Once launched, access the web microservices via your browser:

| Service | Port | URL |
| :--- | :--- | :--- |
| **Service Portal** | `8080` | [http://localhost:8080](http://localhost:8080) |
| **DAQ USB-4716 Panel** | `8081` | [http://localhost:8081](http://localhost:8081) |
| **Musashi II Panel** | `8082` | [http://localhost:8082](http://localhost:8082) |
| **Musashi IV Panel** | `8083` | [http://localhost:8083](http://localhost:8083) |
| **Database Plotter** | `8084` | [http://localhost:8084](http://localhost:8084) |
| **LLM Interpret** | `8085` | [http://localhost:8085](http://localhost:8085) |
| **InfluxDB Manager** | `18085` | [http://localhost:18085](http://localhost:18085) |
| **InfluxDB Server** | `8086` | Docker container health endpoint |

Verify active listening ports:
```bash
lsof -i :8080 -i :8081 -i :8082 -i :8083 -i :8084 -i :8085 -i :18085 -i :8086
```

---

## 9. Viewing Logs & Diagnostics

Service processes write background logs or output to stdout/stderr. To monitor individual process log files:
```bash
tail -f services/daq_usb4716/daq_pipeline.log
```

---

## 10. Stopping Services

To safely terminate all running background services:

```bash
./deploy/linux/stop.sh
```
