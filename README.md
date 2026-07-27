# MDDP Ingestion Control Suite

The Multi-Device Data Ingestion Control Suite (MDDP) is a modular, high-performance software system designed to orchestrate and visualize time-series telemetry from hardware data acquisition systems (such as the Advantech USB-4716 DAQ Card) and robot dispensers.

This repository features:
- **Portal Gateway (Port 8080)**: A centralized dashboard for auditing and launching active device control panels.
- **DAQ USB-4716 Control Console (Port 8081)**: A dedicated Flask-SocketIO dashboard to configure, start, stop, and audit telemetry stream ingestion in real time.
- **Database Plotter (Port 8084)**: A flexible multi-chart grid workspace powered by Plotly.js, displaying time-series telemetry retrieved dynamically from TimescaleDB hypertables.

---

## 1. System Architecture & Operation Principles

### A. User Operation Flow
Shows how a user configures and runs the data acquisition and plotting pipeline.

```mermaid
graph LR
    Start([User Starts System]) --> StartDB[Start TimescaleDB Service]
    StartDB --> RunScripts[Run Ingestion Control Suite run.sh / run.bat]
    RunScripts --> LaunchPortal[Access Portal Gateway :8080]
    
    LaunchPortal --> SelectDAQ[Select DAQ USB-4716 Panel :8081]
    SelectDAQ --> AdjustConfig[Modify & Save Configuration Parameters]
    AdjustConfig --> StartStream{Start Stream Ingestion}
    
    StartStream -->|Mock Mode| StartMock[Run mockup_stream_to_db.py]
    StartStream -->|Real Hardware Mode| StartReal[Run stream_to_db.py]
    
    StartMock --> IngestionLoop[Telemetry batch-inserted into TimescaleDB]
    StartReal --> IngestionLoop
    
    IngestionLoop --> OpenPlotter[Launch Database Plotter :8084]
    OpenPlotter --> QueryLive[Select Channel & view live Plotly charts]
    QueryLive --> Verify{Telemetry verified?}
    
    Verify -->|No| AdjustConfig
    Verify -->|Yes| EndIngestion[Stop Stream & shutdown via stop.sh]
    
    style Start fill:#e1f5e1,stroke:#4caf50,color:#000
    style LaunchPortal fill:#e3f2fd,stroke:#2196f3,color:#000
    style StartStream fill:#fff3e0,stroke:#ff9800,color:#000
    style Verify fill:#fce4ec,stroke:#e91e63,color:#000
```

### B. Technical Architecture Diagram
Depicts the layered structure of the tech stack and the data pathways across services.

```mermaid
graph LR
    subgraph "Presentation Layer"
        Portal[Portal Gateway<br/>Vanilla HTML / CSS / JS]
        DAQView[DAQ UI Panel<br/>Bootstrap + SocketIO]
        PlotView[Plotter UI<br/>Plotly.js dynamic grid]
    end

    subgraph "Application & Service Layer"
        WebServer[Python http.server<br/>Port 8080]
        DAQGUISvc["DAQ Control Server<br/>Flask + SocketIO (Port 8081)"]
        PlotSvc["Analytics & Plotter Service<br/>Flask Stateless Web API (Port 8084)"]
        DAQStream[Ingestion Process<br/>stream_to_db.py]
    end

    subgraph "Data & Messaging Layer"
        TimescaleDB[(TimescaleDB / PostgreSQL<br/>Port 5432)]
        MQTTBroker[MQTT Broker<br/>Port 1883]
    end

    Portal -.->|links| DAQView
    Portal -.->|links| PlotView

    DAQView -->|WebSockets| DAQGUISvc
    DAQGUISvc -->|Popen subprocess| DAQStream
    PlotView -->|REST queries| PlotSvc

    DAQStream -->|psycopg2 bulk INSERT| TimescaleDB
    DAQStream -.->|paho-mqtt publish| MQTTBroker
    PlotSvc -->|psycopg2 SELECT queries| TimescaleDB

    style Portal fill:#61dafb,stroke:#00d8ff,color:#000
    style DAQGUISvc fill:#ff6b6b,stroke:#ff0000,color:#000
    style TimescaleDB fill:#4caf50,stroke:#2e7d32,color:#000
    style MQTTBroker fill:#ff9800,stroke:#e65100,color:#000
```

### C. Data Flow Diagram
Maps internal threading, buffering, and output target flows of the streaming pipeline.

```mermaid
graph LR
    subgraph HW [USB-4716 Hardware]
        AI["Analog Input Channels (ch0-ch7)"]
    end

    subgraph Pipeline [stream_to_db.py]
        direction TB
        DAQThread["🧵 DAQ-Reader Thread"]
        Queue[("📥 In-memory queue.Queue (maxsize=200)")]
        WriterThread["🧵 Data Writer Thread"]
        Stats[("📊 Stats Lock & Dict")]
        MonitorThread["🧵 Monitor Thread"]

        DAQThread -->|1. Poll via getDataF64| AI
        DAQThread -->|2. Wall-clock timestamping & raw enqueue| Queue
        DAQThread -->|Update stats| Stats
        Queue -->|3. Dequeue batch| WriterThread
        WriterThread -->|4. Parse interleaved samples & compute periodic ts| WriterThread
        WriterThread -->|Update stats| Stats
        MonitorThread -->|Read stats & log stdout| Stats
    end

    subgraph Targets [Configurable Destinations]
        TimescaleDB[("🗄️ TimescaleDB (daq_samples)")]
        MQTTBroker[("📡 MQTT Broker (daq/telemetry)")]
    end

    WriterThread -->|"5a. execute_values (DESTINATION=database)"| TimescaleDB
    WriterThread -->|"5b. publish JSON batch (DESTINATION=mqtt)"| MQTTBroker
```

---

## 2. Tech Stack

- **Frontend**: Vanilla HTML5, CSS Grid/Flexbox matching the Unified Industrial Cockpit Design Tokens, Javascript (ES6), Socket.io Client, and Plotly.js.
- **Backend Services**: Python 3, Flask, Flask-SocketIO, Eventlet (for high-concurrency event loops).
- **Ingestion Pipeline**: Multi-threaded Python pipeline, `psycopg2` bulk inserts, Advantech DAQNavi driver interface.
- **Database**: TimescaleDB / PostgreSQL.

---

## 3. Quick Start & Deployment Options

The MDDP Ingestion Control Suite supports two deployment paths tailored to target operating systems and environment needs:

| Operating System | Recommended Deployment Method | Primary Setup Commands | Full Guide Link |
| :--- | :--- | :--- | :--- |
| **Linux (Ubuntu/Debian)** | **Native Script-Based Setup** (`.sh`) | `./deploy/linux/install_deps.sh`<br/>`./deploy/linux/run.sh` | [DEPLOY_LINUX.md](DEPLOY_LINUX.md) |
| **Windows 10/11** | **Native Script-Based Setup** (`.bat`) | `deploy\windows\install_deps.bat`<br/>`deploy\windows\run.bat`<br/>`powershell .\deploy\windows\setup_task_scheduler.ps1` | [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md) |

---

### Option A: Linux Deployment (Script-Based)

Deploy all web microservices using native Linux shell scripts:

```bash
# 1. Install dependencies into virtualenv
./deploy/linux/install_deps.sh

# 2. Launch background application services
./deploy/linux/run.sh

# 3. Stop background services
./deploy/linux/stop.sh
```

See [DEPLOY_LINUX.md](DEPLOY_LINUX.md) for full instructions and hardware connectivity configuration.

---

### Option B: Windows Deployment (Script-Based)

For 24/7 unattended Windows operation with native Advantech USB-4716 hardware drivers:

```cmd
:: 1. Install dependencies into virtualenv
deploy\windows\install_deps.bat

:: 2. Test manual execution
deploy\windows\run.bat

:: 3. Setup 24/7 background operation in Task Scheduler (Run as Admin in PowerShell)
powershell -ExecutionPolicy Bypass -File .\deploy\windows\setup_task_scheduler.ps1
```

See [DEPLOY_WINDOWS.md](DEPLOY_WINDOWS.md) for complete details on Windows Task Scheduler, automatic crash recovery via `watchdog.ps1`, and firewall rules.

---

## 4. Configuration Documentation

The hardware interface, database connection parameters, and calibration parameters are configured via [USB4716/config.json](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/USB4716/config.json).

### Output Destination & MQTT Parameters
| Parameter | Default Value | Description |
|:---|:---|:---|
| `DESTINATION` | `database` | Output target mode (`database` for direct TimescaleDB, `mqtt` for MQTT Broker publishing). |
| `MQTT_BROKER` | `localhost` | Hostname or IP address of the target MQTT broker. |
| `MQTT_PORT` | `1883` | Port number of the MQTT broker service. |
| `MQTT_TOPIC` | `daq/telemetry` | MQTT topic where serialized JSON sample batches are published. |
| `MQTT_QOS` | `0` | MQTT Quality of Service level (`0`: At most once, `1`: At least once, `2`: Exactly once). |
| `DB_DSN` | `postgresql://admin:admin@172.21.108.86:5432/daq_db` | Connection DSN string for production TimescaleDB service. |
| `MOCKUP_DB_DSN` | `postgresql://admin:admin@localhost:5432/daq_db` | Connection DSN string for localized database testing. |
| `DEVICE_DESCRIPTION` | `USB-4716,BID#0` | Unique hardware identifier matching the Advantech DAQ card name. |

### Ingestion Parameter Tuning
| Parameter | Default Value | Description |
|:---|:---|:---|
| `START_CHANNEL` | `0` | Starting index of analog input channel scan. |
| `CHANNEL_COUNT` | `1` | Number of analog channels to scan (max 8 channels on single-ended connections). |
| `CLOCK_RATE` | `2000` | Hardware scanning frequency (samples per second per channel). |
| `SECTION_LENGTH` | `500` | Ingestion batch buffer size. Determines chunk size transferred to queue. |
| `QUEUE_MAXSIZE` | `200` | Maximum limit of the in-memory threading queue to protect against memory leaks. |
| `DB_PAGE_SIZE` | `1000` | Number of telemetry rows packed into a single database transactional `INSERT`. |

### Calibration & Scale Configs
The `SCALE_CONFIGS` block maps raw analog voltages (1V to 5V or 0V to 10V) to physical instrument metrics (e.g., pressure, flow, temperature).
```json
"SCALE_CONFIGS": {
  "0": {
    "enabled": true,
    "low_voltage": 1.0,
    "high_voltage": 5.0,
    "low_value": -100.0,
    "high_value": 100.0
  }
}
```
*If `enabled` is `true`, raw voltages reading from the channel are mapped linearly from `[low_voltage, high_voltage]` range into the `[low_value, high_value]` unit spectrum prior to transmission/storage.*

---

## 5. MQTT Telemetry & Bridge

When `DESTINATION` is set to `mqtt`, the DAQ streaming pipeline publishes JSON telemetry batches directly to the configured MQTT broker.

### JSON Payload Format
```json
[
  {
    "time": "2026-07-20T11:40:00.000000+00:00",
    "channel": 0,
    "value": 2.45
  }
]
```

### Standalone MQTT-to-DB Subscriber
To consume telemetry from the MQTT broker and persist it into TimescaleDB:
```bash
uv run USB4716/mqtt_to_db.py
```

---

## 6. Project Structure

- `deploy/`: Dedicated platform deployment assets.
  - `linux/`: Linux shell scripts (`install_deps.sh`, `run.sh`, `stop.sh`), systemd installer (`setup_systemd.sh`), and unit file (`mddp.service`).
  - `windows/`: Windows batch scripts (`install_deps.bat`, `run.bat`, `stop.bat`), Task Scheduler installers (`setup_task_scheduler.ps1`), and `watchdog.ps1`.
- `portal/`: Portal Gateway static site files.
  - [index.html](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/portal/index.html): Central gateway cockpit web layout.
  - [app.js](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/portal/app.js): Port heartbeat and uptime trackers.
- `USB4716/`: DAQ Controller daemon files.
  - [web_gui.py](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/USB4716/web_gui.py): Controls python daemon cycles and streams stdout logs to client websockets.
  - [stream_to_db.py](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/USB4716/stream_to_db.py): High-throughput hardware thread loop accessing Advantech library calls.
  - [mockup_stream_to_db.py](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/USB4716/mockup_stream_to_db.py): Hardware-free mockup utility supporting DB and MQTT output.
  - [mqtt_to_db.py](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/USB4716/mqtt_to_db.py): Standalone MQTT subscriber daemon bridging MQTT broker messages into TimescaleDB.
- `plot_service/`: Telemetry Visualizer web application files.
  - [app.py](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/plot_service/app.py): REST API endpoints for connection testing and TimescaleDB querying.
  - `static/`: Frontend visual layout mapping Plotly grid resizing.
- `docs/`: Design systems documentation, diagrams, ERD, and context definitions.

---

## 6. Troubleshooting Tips

### ⚠️ Common Issue: Port Conflict
- **Symptom**: `[SYSTEM] Warning: PID files detected` or failed socket binding warnings during startup.
- **Solution**: Execute `./deploy/linux/stop.sh` to clear dangling processes. If ports remain blocked, check processes listening on ports:
  ```bash
  kill -9 $(lsof -t -i :8080 -i :8081 -i :8084)
  ```

### ⚠️ Common Issue: TimescaleDB Connection Timeout
- **Symptom**: Log reports `psycopg2.OperationalError: connection to server at ... failed: Connection timed out`.
- **Solution**: Make sure TimescaleDB service is running and accessible. If connecting to an external server DSN, verify host accessibility via pinging:
  ```bash
  ping 172.21.108.86
  ```

### 💡 Recommendation: Running Mockup Mode for Local Work
If you are developing locally without an active USB-4716 hardware card:
1. Initialize the mockup database:
   ```sql
   CREATE DATABASE mockup;
   ```
2. Enable mockup mode in the DAQ Control Console (Port 8081).
3. The server will stream synthetic sinusoidal telemetry to the mockup database, enabling offline pipeline testing.
