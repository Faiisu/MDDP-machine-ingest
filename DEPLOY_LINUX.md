# MDDP Ingestion Control Suite — Linux Docker Deployment Guide

This document provides step-by-step instructions for deploying the MDDP Ingestion Control Suite on **Linux (Ubuntu/Debian)** using **Docker** and **Docker Compose**, with support for physical **Advantech USB-4716 DAQ** hardware passthrough and serial devices.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Project Setup](#2-project-setup)
3. [Docker Deployment](#3-docker-deployment)
4. [Hardware Layer Connectivity (USB & Serial)](#4-hardware-layer-connectivity-usb--serial)
5. [Service Access & Verification](#5-service-access--verification)
6. [Viewing Logs & Diagnostics](#6-viewing-logs--diagnostics)
7. [Stopping & Restarting Services](#7-stopping--restarting-services)

---

## 1. Prerequisites

Before starting deployment on Linux, ensure the following are installed:

- **Docker Engine** (v20.10 or higher)
- **Docker Compose** (v2.0 or higher)

Verify installation:
```bash
docker --version
docker compose version
```

---

## 2. Project Setup

Clone or copy the project repository to your target Linux directory (e.g., `/opt/mddp` or `~/mddp`):

```bash
cd ~/mddp
```

Ensure `docker-entrypoint.sh` has execution permissions:
```bash
chmod +x docker-entrypoint.sh
```

---

## 3. Docker Deployment

Launch the MDDP application stack using Docker Compose:

```bash
docker compose up -d --build
```

**Expected Output:**
```
[+] Building 2.5s (10/10) FINISHED
[+] Running 1/1
 ✔ Container mddp_app  Started
```

---

## 4. Hardware Layer Connectivity (USB & Serial)

The Docker setup supports both **Mockup Mode** (driverless simulation) and **Real Hardware Mode** (Advantech USB-4716 DAQ and Serial Dispenser):

### A. Mockup Mode (Software Simulation)
No physical hardware or driver configuration is required. Simply start acquisition from the web UI ([http://localhost:8081](http://localhost:8081)).

### B. Real USB Hardware Mode (Advantech USB-4716 DAQ)
The container is configured with `privileged: true` and mounts `/dev/bus/usb:/dev/bus/usb` in `docker-compose.yml`:

```yaml
  mddp-app:
    build: .
    container_name: mddp_app
    privileged: true
    volumes:
      - /dev/bus/usb:/dev/bus/usb
```

This grants the container direct access to the host's USB controller for low-latency telemetry acquisition.

### C. Real Serial Port Mode (Musashi IV RS-232 Controller)
If connecting a physical serial controller (e.g., `/dev/ttyUSB0` or `/dev/ttyS0`), uncomment the device mapping in `docker-compose.yml`:

```yaml
    devices:
      - "/dev/ttyUSB0:/dev/ttyUSB0"
```

---

## 5. Service Access & Verification

Once deployed, access the web microservices via your browser:

| Service | Port | URL |
| :--- | :--- | :--- |
| **Portal Gateway** | `8080` | [http://localhost:8080](http://localhost:8080) |
| **DAQ USB-4716 Panel** | `8081` | [http://localhost:8081](http://localhost:8081) |
| **Musashi IV Panel** | `8083` | [http://localhost:8083](http://localhost:8083) |
| **Database Plotter** | `8084` | [http://localhost:8084](http://localhost:8084) |

To verify active listening ports on the host:
```bash
lsof -i :8080 -i :8081 -i :8083 -i :8084
```

---

## 6. Viewing Logs & Diagnostics

To view aggregated real-time container output:
```bash
docker logs -f mddp_app
```

To view individual service logs generated inside the container:
```bash
docker exec -it mddp_app tail -f /app/logs/daq_panel.log
docker exec -it mddp_app tail -f /app/logs/plotter.log
```

---

## 7. Stopping & Restarting Services

- **Stop Services**:
  ```bash
  docker compose down
  ```
- **Restart Services**:
  ```bash
  docker compose restart
  ```
