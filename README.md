# MDDP Ingestion Control Suite

MDDP is a modular control and telemetry platform for Advantech USB-4716 data acquisition and Musashi dispenser systems. It provides operator consoles for configuring devices, starting ingestion processes, managing storage targets, and inspecting time-series data.

## Services

| Service | Port | Start file | Purpose |
| --- | ---: | --- | --- |
| DAQ USB-4716 console | `8081` | `services/daq_usb4716/app.py` | Configure and control DAQ ingestion. |
| Musashi II console | `8082` | `services/musashi_ii/app.py` | Configure and control serial dispenser ingestion. |
| Musashi IV console | `8083` | `services/musashi_iv/app.py` | Configure and control HTTP dispenser ingestion. |
| Database plotter | `8084` | `services/plotter/app.py` | Query PostgreSQL/TimescaleDB and draw Plotly charts. |
| InfluxDB manager | `8085` | `services/influxdb/app.py` | Manage the InfluxDB container, credentials, retention, and logs. |
| InfluxDB server | `8086` | Docker Compose | Stores InfluxDB time-series data. |

The Linux launcher starts the five Python services. The current Windows launcher does not start the InfluxDB manager; run `python services/influxdb/app.py` separately when it is needed on Windows.

## System operation

```mermaid
flowchart TD
    Start([Start suite]) --> Install[Install dependencies]
    Install --> Configure[Configure device and storage]
    Configure --> Launch[Launch service consoles]
    Launch --> DAQ[Open DAQ console :8081]
    DAQ --> Mode{Select mode}
    Mode -->|Mockup| Mock[Generate synthetic telemetry]
    Mode -->|Real| Hardware[Read USB-4716]
    Mock --> Destination{Choose destination}
    Hardware --> Destination
    Destination -->|PostgreSQL| SQL[(TimescaleDB)]
    Destination -->|InfluxDB| Influx[(InfluxDB :8086)]
    Destination -->|MQTT| Broker[(MQTT broker)]
    SQL --> Plot[Open plotter :8084]
    Influx --> Manage[Manage retention :8085]
    Plot --> Verify([Verify telemetry])
    Manage --> Verify

    style Start fill:#e1f5e1,stroke:#4caf50,color:#000
    style Launch fill:#e3f2fd,stroke:#2196f3,color:#000
    style Mode fill:#fff3e0,stroke:#ff9800,color:#000
    style Verify fill:#fce4ec,stroke:#e91e63,color:#000
```

The DAQ reader polls hardware or generates a mockup waveform, timestamps samples, queues them in memory, and writes batches to the configured destination. PostgreSQL/TimescaleDB uses the `daq_samples` table with `time`, `channel`, and `value` columns. The schema is in [`scripts/sql/db_setup.sql`](scripts/sql/db_setup.sql).

## Prerequisites

- Python `3.12` or newer.
- `uv` recommended, or Python `venv` and `pip`.
- PostgreSQL with TimescaleDB for SQL storage and plotting.
- Mosquitto or another MQTT broker when using `DESTINATION=mqtt`.
- Advantech DAQNavi SDK when using a physical USB-4716.
- Docker and Docker Compose when using InfluxDB.

## Linux quick start

Run from the project root:

```bash
./deploy/linux/install_deps.sh
psql "postgresql://admin:admin@localhost:5432/daq_db" -f scripts/sql/db_setup.sql
./deploy/linux/run.sh
```

Open the required console:

- DAQ: [http://localhost:8081](http://localhost:8081)
- Musashi II: [http://localhost:8082](http://localhost:8082)
- Musashi IV: [http://localhost:8083](http://localhost:8083)
- Plotter: [http://localhost:8084](http://localhost:8084)
- InfluxDB manager: [http://localhost:8085](http://localhost:8085)

Stop the suite with:

```bash
./deploy/linux/stop.sh
```

See [`DEPLOY_LINUX.md`](DEPLOY_LINUX.md) for systemd, hardware permissions, and diagnostics.

## Windows quick start

```cmd
deploy\windows\install_deps.bat
deploy\windows\run.bat
```

See [`DEPLOY_WINDOWS.md`](DEPLOY_WINDOWS.md) for Task Scheduler, watchdog, firewall, and hardware setup. Start the InfluxDB manager separately when needed:

```cmd
python services\influxdb\app.py
```

## InfluxDB setup

The server is defined in [`docker-compose.influxdb.yml`](docker-compose.influxdb.yml), exposes port `8086`, and persists data in Docker volumes `influxdb2_data` and `influxdb2_config`.

From the manager on port `8085`:

1. Open **Lifecycle overview** and start the container.
2. Open **Connection setup** and verify URL, organization, bucket, measurement, and token.
3. Use **Sync token → DAQ service** after changing DAQ-facing connection settings.
4. Use **Retention policy** to apply bucket expiry.
5. Use **Runtime logs** to inspect container output.

To run Docker Compose directly, create a local `.env.influxdb` file:

```dotenv
INFLUX_USERNAME=admin
INFLUX_PASSWORD=replace-with-a-strong-password
INFLUX_ORG=mddp
INFLUX_BUCKET=daq_telemetry
INFLUX_RETENTION=0
```

```bash
docker compose --env-file .env.influxdb -f docker-compose.influxdb.yml up -d
docker compose --env-file .env.influxdb -f docker-compose.influxdb.yml stop
```

The manager configuration is stored in [`services/influxdb/influxdb_config.json`](services/influxdb/influxdb_config.json). Do not commit production passwords or tokens.

## Configuration reference

The DAQ configuration is [`services/daq_usb4716/config.json`](services/daq_usb4716/config.json).

| Key | Purpose | Example |
| --- | --- | --- |
| `DEVICE_DESCRIPTION` | Advantech device identifier. | `USB-4716,BID#0` |
| `DESTINATION` | `postgresql`, `influxdb`, or `mqtt`. | `postgresql` |
| `DB_DSN` | PostgreSQL/TimescaleDB connection string. | `postgresql://user:password@host:5432/daq_db` |
| `INFLUX_URL` | InfluxDB HTTP endpoint. | `http://localhost:8086` |
| `INFLUX_ORG` | InfluxDB organization. | `mddp` |
| `INFLUX_BUCKET` | InfluxDB bucket. | `daq_telemetry` |
| `INFLUX_MEASUREMENT` | InfluxDB measurement. | `daq_telemetry` |
| `INFLUX_TOKEN` | Token used for InfluxDB writes. | Secret value |
| `START_CHANNEL` | First channel to scan. | `0` |
| `CHANNEL_COUNT` | Number of analog channels. | `1` to `8` |
| `CLOCK_RATE` | Samples per second per channel. | `2000` |
| `SECTION_LENGTH` | Samples per ingestion batch. | `500` |
| `QUEUE_MAXSIZE` | Maximum in-memory queue depth. | `200` |
| `MQTT_BROKER` | MQTT host when destination is MQTT. | `localhost` |
| `MQTT_PORT` | MQTT broker port. | `1883` |
| `MQTT_TOPIC` | Telemetry topic. | `daq/telemetry` |

The InfluxDB manager configuration is [`services/influxdb/influxdb_config.json`](services/influxdb/influxdb_config.json). It contains URL, organization, bucket, measurement, credentials, token, and retention fields. When retention is disabled, the manager sets the bucket rule to `0`, retaining data indefinitely.

## MQTT bridge

Set `DESTINATION` to `mqtt` in the DAQ config to publish JSON batches. To persist those batches into PostgreSQL/TimescaleDB, run:

```bash
python services/daq_usb4716/mqtt_to_db.py
```

```json
[
  {
    "time": "2026-07-20T11:40:00.000000+00:00",
    "channel": 0,
    "value": 2.45
  }
]
```

## API overview

DAQ (`8081`): `GET/POST /api/config`, `GET /api/status`, `POST /api/test_db`, `GET /api/scan_usb`, and Socket.IO control/status events.

InfluxDB manager (`8085`): `GET/POST /api/config`, `GET /api/status`, `POST /api/start`, `POST /api/stop`, `POST /api/retention`, `POST /api/sync_daq`, and `GET /api/logs`.

## UI pattern system

Future service consoles should reuse [`ui-tokens.css`](services/influxdb/static/ui-tokens.css) and [`ui-patterns.css`](services/influxdb/static/ui-patterns.css). See [`services/ui_patterns/README.md`](services/ui_patterns/README.md) and [`docs/UI_DESIGN_SYSTEM.md`](docs/UI_DESIGN_SYSTEM.md).

The default InfluxDB theme is **Arctic Light**. Available themes are `arctic-light`, `dark-ocean`, `emerald-matrix`, `amber-cockpit`, and `dracula`. The selected theme is stored under `influx_ui_theme` in browser local storage.

## Development and testing

```bash
PYTHONPATH=. python -m pytest -q tests/test_influxdb_service.py
python -m py_compile services/influxdb/app.py
node --check services/influxdb/static/app.js
```

Run an individual service during development:

```bash
python services/influxdb/app.py
```

Do not commit generated PID files, local logs, production credentials, API tokens, or Docker secrets.

## Project structure

```text
.
├── deploy/                    # Linux and Windows launch/deployment scripts
├── docs/                      # Architecture and UI design documentation
├── scripts/sql/db_setup.sql   # PostgreSQL/TimescaleDB schema
├── services/
│   ├── daq_usb4716/           # DAQ console and ingestion workers
│   ├── influxdb/              # InfluxDB manager and UI reference implementation
│   ├── musashi_ii/            # Serial dispenser console and reader
│   ├── musashi_iv/            # HTTP dispenser console and reader
│   ├── plotter/               # PostgreSQL/TimescaleDB Plotly dashboard
│   └── ui_patterns/           # Shared UI composition documentation
├── tests/                     # Service and integration tests
├── docker-compose.influxdb.yml
├── pyproject.toml
└── README.md
```

## Troubleshooting

Check port conflicts:

```bash
lsof -nP -iTCP:8081 -iTCP:8082 -iTCP:8083 -iTCP:8084 -iTCP:8085 -sTCP:LISTEN
```

If DAQ hardware is missing, verify DAQNavi, `DEVICE_DESCRIPTION`, and device permissions, or use mockup mode. If PostgreSQL fails, verify `DB_DSN` and run [`scripts/sql/db_setup.sql`](scripts/sql/db_setup.sql). If InfluxDB is offline, confirm Docker, port `8086`, and the manager's **Runtime logs** panel.

## Additional guides

- [Linux deployment](DEPLOY_LINUX.md)
- [Windows deployment](DEPLOY_WINDOWS.md)
- [Architecture guide](docs/ARCHITECTURE.md)
- [UI design system](docs/UI_DESIGN_SYSTEM.md)
- [Plotter development guide](services/plotter/DEVELOPMENT.md)
