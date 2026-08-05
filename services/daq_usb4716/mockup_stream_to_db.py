#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# See: docs/architecture/context.md

"""
mockup_stream_to_db.py
──────────────────────
Mock-up version of stream_to_db.py — synthetic DAQ data, writes to a real
TimescaleDB database named "mockup" (auto-created if it does not exist).

Architecture (2-thread + Queue) — identical to real pipeline:
  ┌──────────────────────────────────────────────────┐
  │ Mock DAQ Thread  (generates synthetic data)      │
  │  sine/noise waveform → wall-clock stamp → put()  │
  └─────────────────────┬────────────────────────────┘
                        │ (batch_wall_ts, raw_data, returned_count)
                        ▼
                  Queue (in-memory)
                        │
  ┌─────────────────────▼────────────────────────────┐
  │ DB Writer Thread  (parse + real psycopg2 INSERT) │
  │  get(raw) → compute periodic forward ts → INSERT │
  │  → database: "mockup"  table: daq_samples        │
  └──────────────────────────────────────────────────┘

Mock DAQ behaviour:
  - Generates sine waves per channel (configurable amplitude & frequency)
  - Adds Gaussian noise to simulate real sensor noise
  - Respects CLOCK_RATE, CHANNEL_COUNT, SECTION_LENGTH exactly like real code
  - Sleeps to simulate hardware acquisition time (SECTION_LENGTH / CLOCK_RATE)

DB behaviour:
  - On startup: connects to the Postgres server and creates the "mockup"
    database if it does not exist, then creates the daq_samples table
    (+ TimescaleDB hypertable) if they do not exist.
  - Writes real rows via psycopg2 execute_values — identical INSERT path
    to stream_to_db.py, just targeting a different database.
  - Optionally also dumps rows to a CSV file (MOCKUP_CSV_PATH).
"""

import sys
import os
import time
import math
import random
import signal
import threading
import logging
import queue
import csv
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import psycopg2.extensions

import json
from types import SimpleNamespace

with open(os.path.join(os.path.dirname(__file__), "config.json"), "r") as f:
    _cfg = json.load(f)
_cfg["USER_BUFFER_SIZE"] = _cfg["SECTION_LENGTH"] * _cfg["CHANNEL_COUNT"]
_cfg["QUEUE_BATCH_SIZE"] = _cfg["USER_BUFFER_SIZE"]
config = SimpleNamespace(**_cfg)

# ─── Mock-up Tuning ──────────────────────────────────────────────────────────
# Waveform parameters for each channel (index = channel offset from START_CHANNEL)
# Each entry: (amplitude_V, frequency_Hz, dc_offset_V)
MOCKUP_CHANNEL_WAVEFORMS = [
    (2.0,  5.0,   2.5),   # ch0: 2 V amplitude,   5 Hz sine, centred at 2.5 V
    (1.0,  10.0,  2.5),   # ch1: 1 V amplitude,  10 Hz sine, centred at 2.5 V
    (0.5,  20.0,  1.5),   # ch2: 0.5 V amplitude, 20 Hz sine, centred at 1.5 V
    (1.5,  2.0,   3.0),   # ch3: 1.5 V amplitude,  2 Hz sine, centred at 3.0 V
    (0.8,  50.0,  2.0),   # ch4
    (1.2,  1.0,   2.5),   # ch5
    (0.3,  100.0, 1.0),   # ch6
    (2.0,  0.5,   2.5),   # ch7 (slow drift)
]
MOCKUP_NOISE_STD_V  = 0.02    # Gaussian noise standard deviation (volts)
MOCKUP_CSV_PATH     = None    # Set to a filepath string to also dump rows to CSV,
                              # e.g. "mockup_output.csv". None = no CSV output.
MOCKUP_PRINT_ROWS   = False   # Set True to print every parsed row (very verbose)
MOCKUP_SUMMARY_ROWS = 5       # How many sample rows to show per stats interval

# ─── Mockup DB settings ──────────────────────────────────────────────────────
# The mockup always writes to the "mockup" database on the same server as
# config.MOCKUP_DB_DSN.  We parse the DSN to swap out the database name.
MOCKUP_DB_NAME = "mockup"

def _build_mockup_dsn(original_dsn: str, dbname: str) -> str:
    """Replace the database name in a postgresql:// DSN."""
    # psycopg2 can parse DSNs for us
    parsed = psycopg2.extensions.make_dsn(original_dsn)
    parts  = psycopg2.extensions.parse_dsn(parsed)
    parts["dbname"] = dbname
    return psycopg2.extensions.make_dsn(**parts)

mockup_dsn = getattr(config, 'MOCKUP_DB_DSN', getattr(config, 'DB_DSN', 'postgresql://admin:admin@172.21.108.86:5432/daq_db'))
_POSTGRES_DSN = _build_mockup_dsn(mockup_dsn, "postgres")
MOCKUP_MOCKUP_DB_DSN = _build_mockup_dsn(mockup_dsn, MOCKUP_DB_NAME)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-12s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

# ─── Shared state ─────────────────────────────────────────────────────────────
# Identical queue contract to real stream_to_db.py:
#   item = (batch_wall_ts_ns: int, raw_data: list[float], returned_count: int)
data_queue = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
stop_event  = threading.Event()

stats_lock = threading.Lock()
stats = {
    "polled":    0,   # total interleaved samples generated
    "enqueued":  0,   # total batches enqueued
    "written":   0,   # total rows written to DB
    "dropped":   0,   # batches dropped due to full queue
    "db_errors": 0,   # number of DB insert failures
}

# Shared buffer for monitor thread to peek at recent rows
_recent_rows_lock = threading.Lock()
_recent_rows: list = []


# ─── DB bootstrap (run once before threads start) ────────────────────────────
def ensure_mockup_db():
    """
    1. Connect to the 'postgres' maintenance DB.
    2. CREATE DATABASE mockup  (if not exists — Postgres has no IF NOT EXISTS
       for CREATE DATABASE, so we check pg_database instead).
    3. Connect to 'mockup' and CREATE TABLE / hypertable if not exists.
    """
    # ── Step 1 & 2: create database ──────────────────────────────────────────
    log.info(f"[DBSetup] Checking if database '{MOCKUP_DB_NAME}' exists...")
    try:
        conn = psycopg2.connect(_POSTGRES_DSN)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (MOCKUP_DB_NAME,)
        )
        exists = cur.fetchone()

        if not exists:
            cur.execute(f'CREATE DATABASE "{MOCKUP_DB_NAME}"')
            log.info(f"[DBSetup] Database '{MOCKUP_DB_NAME}' created.")
        else:
            log.info(f"[DBSetup] Database '{MOCKUP_DB_NAME}' already exists.")

        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"[DBSetup] Failed to create database: {e}")
        raise

    # ── Step 3: create table + hypertable in mockup DB ───────────────────────
    log.info(f"[DBSetup] Ensuring schema in '{MOCKUP_DB_NAME}'...")
    try:
        conn = psycopg2.connect(MOCKUP_MOCKUP_DB_DSN)
        conn.autocommit = True
        cur = conn.cursor()

        # Enable TimescaleDB extension (may already exist)
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
            log.info("[DBSetup] TimescaleDB extension enabled.")
        except Exception as e:
            log.warning(f"[DBSetup] TimescaleDB extension not available ({e}). "
                        "Falling back to plain PostgreSQL table (no hypertable).")
            conn.autocommit = True   # reset after any implicit rollback

        # Main samples table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daq_samples (
                time        TIMESTAMPTZ      NOT NULL,
                channel     SMALLINT         NOT NULL,
                value       DOUBLE PRECISION NOT NULL
            );
        """)

        # Convert to hypertable (safe to call repeatedly thanks to if_not_exists)
        try:
            cur.execute(
                "SELECT create_hypertable('daq_samples', 'time', if_not_exists => TRUE);"
            )
            log.info("[DBSetup] Hypertable ready.")
        except Exception as e:
            log.warning(f"[DBSetup] create_hypertable() skipped ({e}). "
                        "Using plain table — data will still be written correctly.")

        # Index for fast channel + time queries
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_mockup_channel_time
                ON daq_samples (channel, time DESC);
        """)

        # Session metadata table (mirrors scripts/sql/db_setup.sql)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daq_sessions (
                id            SERIAL PRIMARY KEY,
                started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                stopped_at    TIMESTAMPTZ,
                channel_count SMALLINT    NOT NULL,
                clock_rate_hz INTEGER     NOT NULL,
                notes         TEXT
            );
        """)

        cur.close()
        conn.close()
        log.info(f"[DBSetup] Schema ready in '{MOCKUP_DB_NAME}'.")
    except Exception as e:
        log.error(f"[DBSetup] Schema setup failed: {e}")
        raise


# ─── Mock DAQ Generator Thread ───────────────────────────────────────────────
def mock_daq_reader_thread():
    """
    Simulates WaveformAiCtrl.getDataF64() and InstantDiCtrl without real hardware.

    Generates interleaved AI samples and synthetic DI port bytes.
    Timing: sleeps for the real acquisition window
        (SECTION_LENGTH / CLOCK_RATE) seconds per batch,
    so downstream throughput matches a real device.
    """
    try:
        enable_ai = getattr(config, 'ENABLE_AI', True)
        enable_di = getattr(config, 'ENABLE_DI', True)
        di_start_port = getattr(config, 'DI_START_PORT', 0)
        di_port_count = getattr(config, 'DI_PORT_COUNT', 1)

        n_ch    = config.CHANNEL_COUNT if enable_ai else 0
        sec_len = config.SECTION_LENGTH      # samples per channel per batch
        buf_sz  = config.USER_BUFFER_SIZE   # = sec_len × n_ch
        dt_s    = 1.0 / config.CLOCK_RATE  # seconds per sample

        # Guard: clamp waveform table to available entries (cycle if fewer entries than channels)
        waveforms = (MOCKUP_CHANNEL_WAVEFORMS * max(1, n_ch))[:n_ch] if n_ch > 0 else []

        # Monotonic sample counter — advances the sine phase continuously across batches
        sample_counter = 0

        log.info(
            f"[MockDAQ] Started | device=MOCK | enable_ai={enable_ai} | enable_di={enable_di} | "
            f"channels={n_ch} | diPorts={di_port_count} | clock={config.CLOCK_RATE} Hz | sectionLength={sec_len}"
        )
        if enable_ai and n_ch > 0:
            log.info("[MockDAQ] Waveforms per channel:")
            for i in range(n_ch):
                amp, freq, dc = waveforms[i]
                log.info(
                    f"  ch{config.START_CHANNEL + i}: "
                    f"{amp:.2f} V × sin(2π×{freq:.1f}Hz×t) + {dc:.2f} V  (noise σ={MOCKUP_NOISE_STD_V} V)"
                )

        try:
            while not stop_event.is_set():
                # ── Simulate hardware acquisition time ──
                time.sleep(sec_len / config.CLOCK_RATE)

                if stop_event.is_set():
                    break

                # ── Generate interleaved AI samples ──
                raw_data = []
                if enable_ai and n_ch > 0:
                    for s in range(sec_len):
                        t = (sample_counter + s) * dt_s
                        for ch_idx in range(n_ch):
                            amp, freq, dc = waveforms[ch_idx]
                            value = amp * math.sin(2 * math.pi * freq * t) + dc
                            value += random.gauss(0.0, MOCKUP_NOISE_STD_V)
                            value = max(0.0, min(5.0, value))   # clamp to V_0To5 range
                            raw_data.append(value)

                sample_counter += sec_len
                returned_count  = len(raw_data)

                # ── Generate synthetic DI port bytes ──
                di_bytes = []
                if enable_di:
                    t_sec = time.time()
                    for p in range(di_port_count):
                        b0 = 1 if int(t_sec) % 2 == 0 else 0
                        b1 = 1 if int(t_sec / 2) % 2 == 0 else 0
                        b2 = 1 if int(t_sec * 2) % 2 == 0 else 0
                        b3 = 1 if random.random() > 0.8 else 0
                        port_val = (b0) | (b1 << 1) | (b2 << 2) | (b3 << 3)
                        di_bytes.append(port_val)

                # ── Capture wall-clock timestamp immediately after "acquisition" ──
                batch_wall_ts_ns = time.time_ns()

                # ── Enqueue (identical logic to real code) ──
                try:
                    data_queue.put_nowait((batch_wall_ts_ns, raw_data, returned_count, di_bytes))
                    with stats_lock:
                        stats["polled"]   += returned_count + (len(di_bytes) * 8 if returned_count == 0 else 0)
                        stats["enqueued"] += 1
                except queue.Full:
                    with stats_lock:
                        stats["dropped"] += 1
                    log.warning(
                        f"[MockDAQ] Queue full! Dropped 1 batch ({returned_count} samples). "
                        "DB writer may be too slow."
                    )

        finally:
            log.info("[MockDAQ] Mock DAQ thread stopped.")
    except Exception as e:
        log.exception(f"Unhandled exception in Mock DAQ thread: {e}")
        stop_event.set()



# ─── DB Writer Thread ─────────────────────────────────────────────────────────
# ─── Data Extraction, Calibration, and Storage Components (SRP Design) ───────

class Calibrator:
    """
    Responsibility: Handle calibration configuration parsing and scaling calculations.
    """
    def __init__(self, start_channel, channel_count, scale_configs):
        self.calibrations = {}
        if isinstance(scale_configs, dict):
            for ch in range(channel_count):
                ch_num = start_channel + ch
                scale_cfg = scale_configs.get(str(ch_num))
                if scale_cfg and scale_cfg.get('enabled', False):
                    low_volt = scale_cfg.get('low_voltage', 0.0)
                    high_volt = scale_cfg.get('high_voltage', 10.0)
                    low_val = scale_cfg.get('low_value', 0.0)
                    high_val = scale_cfg.get('high_value', 100.0)
                    denom = high_volt - low_volt
                    if abs(denom) > 1e-9:
                        slope = (high_val - low_val) / denom
                        self.calibrations[ch] = (low_volt, low_val, slope)

    def calibrate(self, ch, value):
        if ch in self.calibrations:
            low_volt, low_val, slope = self.calibrations[ch]
            return low_val + (value - low_volt) * slope
        return value


class DaqSampleParser:
    """
    Responsibility: Parse interleaved raw DAQ data (AI and DI) and compute timestamps relative to a periodic anchor.
    """
    def __init__(self, start_channel, channel_count, clock_rate, calibrator, di_channel_offset=100, enable_di=True, recalibrate_interval_hr=24.0):
        self.start_channel = start_channel
        self.channel_count = channel_count
        self.dt_ns = int(1_000_000_000 / clock_rate)
        self.calibrator = calibrator
        self.di_channel_offset = di_channel_offset
        self.enable_di = enable_di
        
        # Periodic anchor state configuration
        self.recalibrate_interval_ns = int(recalibrate_interval_hr * 3600 * 1_000_000_000)
        self.anchor_time_ns = None
        self.samples_since_anchor = 0

    def parse_batch(self, batch_wall_ts_ns, raw_data, returned_count, di_bytes=None):
        if self.channel_count > 0 and returned_count > 0:
            samples_per_channel = returned_count // self.channel_count
        else:
            samples_per_channel = getattr(config, 'SECTION_LENGTH', 500)
        
        # Re-anchor the base timestamp if not yet set or if the configured interval has elapsed
        current_time_ns = time.time_ns()
        if self.anchor_time_ns is None or (current_time_ns - self.anchor_time_ns) >= self.recalibrate_interval_ns:
            self.anchor_time_ns = batch_wall_ts_ns
            self.samples_since_anchor = 0
            
        rows = []
        for s in range(samples_per_channel):
            # Calculate forward timestamp based on cumulative samples since the last anchor
            sample_ts_ns = self.anchor_time_ns + (self.samples_since_anchor + s) * self.dt_ns
            sample_ts = datetime.fromtimestamp(sample_ts_ns / 1_000_000_000, tz=timezone.utc)

            # Process Analog Input channels
            if returned_count > 0 and self.channel_count > 0:
                for ch in range(self.channel_count):
                    value = raw_data[s * self.channel_count + ch]
                    value = self.calibrator.calibrate(ch, value)
                    value = round(value, 3)
                    rows.append((sample_ts, self.start_channel + ch, value))

            # Process Digital Input channels
            if self.enable_di and di_bytes:
                for port_idx, port_val in enumerate(di_bytes):
                    for bit_idx in range(8):
                        di_ch_index = self.di_channel_offset + (port_idx * 8) + bit_idx
                        bit_val = float((port_val >> bit_idx) & 1)
                        rows.append((sample_ts, di_ch_index, bit_val))
                
        # Advance cumulative sample count for the next batch
        self.samples_since_anchor += samples_per_channel
        return rows


class TimescaleDBClient:
    """
    Responsibility: Manage TimescaleDB connection lifecycle, transactions, and execution.
    """
    def __init__(self, dsn, stop_event, dbname=None):
        self.dsn = dsn
        self.stop_event = stop_event
        self.dbname = dbname
        self.conn = None
        self.cur = None

    def connect(self):
        while not self.stop_event.is_set():
            try:
                try:
                    ensure_mockup_db()
                except Exception as ne:
                    log.warning(f"[MockDB] Auto DB check warning: {ne}")
                self.conn = psycopg2.connect(self.dsn)
                self.conn.autocommit = False
                self.cur = self.conn.cursor()
                db_desc = f" '{self.dbname}'" if self.dbname else ""
                log.info(f"[MockDB] Connected to database{db_desc}")
                return True
            except Exception as e:
                log.error(f"[MockDB] DB connection failed: {e} — retrying in 5s")
                for _ in range(50):
                    if self.stop_event.is_set():
                        return False
                    time.sleep(0.1)
        return False

    def insert_samples(self, rows, page_size):
        if not self.conn or not self.cur:
            raise RuntimeError("Not connected to database")
        INSERT_SQL = "INSERT INTO daq_samples (time, channel, value) VALUES %s"
        try:
            psycopg2.extras.execute_values(
                self.cur, INSERT_SQL, rows, page_size=page_size
            )
            self.conn.commit()
        except Exception as e:
            self.rollback()
            log.warning(f"[MockDB] Database insert failed ({e}). Auto-creating database/tables and retrying...")
            try:
                ensure_mockup_db()
                self.conn = psycopg2.connect(self.dsn)
                self.conn.autocommit = False
                self.cur = self.conn.cursor()
                psycopg2.extras.execute_values(
                    self.cur, INSERT_SQL, rows, page_size=page_size
                )
                self.conn.commit()
                log.info("[MockDB] Insertion succeeded after auto-creating database/tables.")
                return
            except Exception as retry_err:
                log.error(f"[MockDB] Retry insertion after auto-creation failed: {retry_err}")
            raise

    def send_samples(self, rows, page_size=1000):
        self.insert_samples(rows, page_size=page_size)

    def rollback(self):
        if self.conn:
            self.conn.rollback()

    def disconnect(self):
        if self.cur:
            try:
                self.cur.close()
            except:
                pass
            self.cur = None
        if self.conn:
            try:
                self.conn.close()
            except:
                pass
            self.conn = None
        log.info("[MockDB] Disconnected from database.")


class MQTTClient:
    """
    Responsibility: Manage MQTT connection lifecycle and publishing telemetry samples to an MQTT broker.
    """
    def __init__(self, broker, port, topic, qos=0, username=None, password=None, tls_enabled=False, ca_certs=None, certfile=None, keyfile=None, stop_event=None, client_id="daq_mockup_publisher"):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.qos = qos
        self.username = username
        self.password = password
        self.tls_enabled = tls_enabled
        self.ca_certs = ca_certs
        self.certfile = certfile
        self.keyfile = keyfile
        self.stop_event = stop_event or threading.Event()
        self.client_id = client_id
        self.client = None
        self.is_connected = False

    def connect(self):
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log.error("paho-mqtt package is not installed. Run 'uv pip install paho-mqtt' to enable MQTT mode.")
            return False

        while not self.stop_event.is_set():
            try:
                try:
                    self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
                except (AttributeError, TypeError):
                    self.client = mqtt.Client(client_id=self.client_id)

                if self.username:
                    self.client.username_pw_set(self.username, self.password or None)

                if self.tls_enabled:
                    ca = self.ca_certs if (self.ca_certs and os.path.exists(self.ca_certs)) else None
                    cert = self.certfile if (self.certfile and os.path.exists(self.certfile)) else None
                    key = self.keyfile if (self.keyfile and os.path.exists(self.keyfile)) else None
                    self.client.tls_set(ca_certs=ca, certfile=cert, keyfile=key)

                def on_connect(client, userdata, flags, rc, properties=None):
                    if rc == 0 or rc == mqtt.MQTT_ERR_SUCCESS:
                        self.is_connected = True
                        log.info(f"[MockMQTT] Connected to MQTT broker at {self.broker}:{self.port}")
                    else:
                        self.is_connected = False
                        log.error(f"[MockMQTT] MQTT connection failed with code {rc}")

                def on_disconnect(client, userdata, rc, properties=None):
                    self.is_connected = False
                    log.warning("[MockMQTT] Disconnected from MQTT broker")

                self.client.on_connect = on_connect
                self.client.on_disconnect = on_disconnect
                self.client.connect(self.broker, int(self.port), keepalive=60)
                self.client.loop_start()

                for _ in range(30):
                    if self.is_connected:
                        return True
                    if self.stop_event.is_set():
                        return False
                    time.sleep(0.1)

                log.warning(f"[MockMQTT] MQTT connect timeout ({self.broker}:{self.port}) — retrying in 5s")
                self.disconnect()
            except Exception as e:
                log.error(f"[MockMQTT] MQTT connection error: {e} — retrying in 5s")

            for _ in range(50):
                if self.stop_event.is_set():
                    return False
                time.sleep(0.1)
        return False

    def send_samples(self, rows, page_size=1000):
        if not self.client or not self.is_connected:
            raise RuntimeError("Not connected to MQTT broker")
        payload_data = [
            {
                "time": r[0].isoformat(),
                "channel": r[1],
                "value": r[2]
            }
            for r in rows
        ]
        payload_json = json.dumps(payload_data)
        info = self.client.publish(self.topic, payload_json, qos=int(self.qos))
        if info.rc != 0:
            raise RuntimeError(f"MQTT publish failed with error code {info.rc}")

    def rollback(self):
        pass

    def disconnect(self):
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.is_connected = False
        log.info("[MockMQTT] Disconnected from MQTT broker.")


class InfluxDBClient:
    """
    Responsibility: Manage InfluxDB HTTP Line Protocol telemetry writes.
    """
    def __init__(self, url, token, org, bucket, measurement="daq_telemetry", stop_event=None):
        self.url = (url or "http://localhost:8086").rstrip('/')
        self.token = token or ""
        self.org = org or "mddp"
        self.bucket = bucket or "daq_telemetry"
        self.measurement = measurement or "daq_telemetry"
        self.stop_event = stop_event or threading.Event()
        self.write_url = f"{self.url}/api/v2/write?org={urllib.parse.quote(self.org)}&bucket={urllib.parse.quote(self.bucket)}&precision=s"

    def connect(self):
        target_url = f"{self.url}/health"
        headers = {"User-Agent": "USB4716-MockWriter"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        try:
            req = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                log.info(f"Connected to InfluxDB at {self.url} (Org: {self.org}, Bucket: {self.bucket})")
                return True
        except Exception as e:
            log.warning(f"InfluxDB health check notice ({e}). Client will attempt line protocol writes.")
            return True

    def insert_batch(self, batch_tuples):
        if not batch_tuples:
            return
        lines = []
        for (wall_ts_ns, ch_idx, volt, scaled_val) in batch_tuples:
            ts_sec = int(wall_ts_ns / 1e9)
            fields = f"voltage={volt},scaled={scaled_val}"
            lines.append(f"{self.measurement},ch={ch_idx} {fields} {ts_sec}")

        body = "\n".join(lines).encode('utf-8')
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Token {self.token}"

        req = urllib.request.Request(self.write_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            if resp.status not in (200, 204):
                raise Exception(f"InfluxDB HTTP status {resp.status}")

    def publish_batch(self, batch_tuples):
        self.insert_batch(batch_tuples)

    def disconnect(self):
        log.info("InfluxDB client disconnected.")


# ─── Data Writer Thread ───────────────────────────────────────────────────────
def db_writer_thread():
    """
    Dequeues raw batches, parses interleaved data, and writes to TimescaleDB, InfluxDB
    or publishes to MQTT based on config.DESTINATION.

    Non-daemon thread — flushes remaining queue items before process exits.
    """
    calibrator = Calibrator(
        start_channel=config.START_CHANNEL,
        channel_count=config.CHANNEL_COUNT,
        scale_configs=getattr(config, 'SCALE_CONFIGS', {})
    )

    parser = DaqSampleParser(
        start_channel=config.START_CHANNEL,
        channel_count=config.CHANNEL_COUNT,
        clock_rate=config.CLOCK_RATE,
        calibrator=calibrator,
        di_channel_offset=getattr(config, 'DI_CHANNEL_OFFSET', 100),
        enable_di=getattr(config, 'ENABLE_DI', True),
        recalibrate_interval_hr=getattr(config, 'ANCHOR_RECALIBRATE_INTERVAL_HR', 24.0)
    )

    destination = getattr(config, 'DESTINATION', 'database').lower()

    if destination == 'mqtt':
        client = MQTTClient(
            broker=getattr(config, 'MQTT_BROKER', 'localhost'),
            port=getattr(config, 'MQTT_PORT', 1883),
            topic=getattr(config, 'MQTT_TOPIC', 'daq/telemetry'),
            qos=getattr(config, 'MQTT_QOS', 0),
            username=getattr(config, 'MQTT_USERNAME', ''),
            password=getattr(config, 'MQTT_PASSWORD', ''),
            tls_enabled=getattr(config, 'MQTT_TLS_ENABLED', False),
            ca_certs=getattr(config, 'MQTT_CA_CERTS', ''),
            certfile=getattr(config, 'MQTT_CLIENT_CERT', ''),
            keyfile=getattr(config, 'MQTT_CLIENT_KEY', ''),
            stop_event=stop_event
        )
    elif destination == 'influxdb':
        client = InfluxDBClient(
            url=getattr(config, 'INFLUX_URL', 'http://localhost:8086'),
            token=getattr(config, 'INFLUX_TOKEN', ''),
            org=getattr(config, 'INFLUX_ORG', 'mddp'),
            bucket=getattr(config, 'INFLUX_BUCKET', 'daq_telemetry'),
            measurement=getattr(config, 'INFLUX_MEASUREMENT', 'daq_telemetry'),
            stop_event=stop_event
        )
    else:
        client = TimescaleDBClient(MOCKUP_MOCKUP_DB_DSN, stop_event, MOCKUP_DB_NAME)

    if not client.connect():
        log.info(f"[MockWriter] Writer exiting (could not establish {destination} connection).")
        return

    # Optional CSV output
    csv_file   = None
    csv_writer = None
    if MOCKUP_CSV_PATH:
        try:
            csv_file   = open(MOCKUP_CSV_PATH, "w", newline="")
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(["time_utc", "channel", "value_V"])
            log.info(f"[MockWriter] CSV output enabled → {MOCKUP_CSV_PATH}")
        except Exception as e:
            log.error(f"[MockWriter] Failed to open CSV '{MOCKUP_CSV_PATH}': {e}")
            csv_writer = None

    try:
        while not stop_event.is_set() or not data_queue.empty():
            try:
                item = data_queue.get(timeout=1.0)
                if len(item) == 4:
                    batch_wall_ts_ns, raw_data, returned_count, di_bytes = item
                else:
                    batch_wall_ts_ns, raw_data, returned_count = item
                    di_bytes = None
            except queue.Empty:
                continue

            # 1. Parse raw data into sample rows
            rows = parser.parse_batch(batch_wall_ts_ns, raw_data, returned_count, di_bytes)

            # 2. Write rows to TimescaleDB or publish to MQTT
            try:
                client.send_samples(rows, page_size=config.DB_PAGE_SIZE)
                with stats_lock:
                    stats["written"] += len(rows)

                # Optional CSV mirror
                if csv_writer is not None:
                    for ts, ch, val in rows:
                        csv_writer.writerow([ts.isoformat(), ch, f"{val:.6f}"])
                    csv_file.flush()

                if MOCKUP_PRINT_ROWS:
                    for ts, ch, val in rows:
                        log.debug(f"  ROW  time={ts.isoformat()}  ch={ch}  val={val:.6f}")

                # Keep a snapshot for monitor display
                with _recent_rows_lock:
                    _recent_rows.clear()
                    _recent_rows.extend(rows[-MOCKUP_SUMMARY_ROWS:])

            except Exception as e:
                with stats_lock:
                    stats["db_errors"] += 1
                log.error(f"[MockWriter] Writer output error ({destination}): {e} — attempting recovery...")

                # Attempt rollback
                try:
                    client.rollback()
                except Exception as rb_err:
                    log.error(f"[MockWriter] Rollback failed: {rb_err} — connection is dead. Closing resources.")
                    client.disconnect()

                # Re-enqueue so data is not lost (best-effort)
                try:
                    data_queue.put_nowait((batch_wall_ts_ns, raw_data, returned_count))
                except queue.Full:
                    with stats_lock:
                        stats["dropped"] += 1
                    log.error("[MockWriter] Queue full on re-queue — batch permanently lost!")

                # Reconnect if connection was lost
                conn_ok = getattr(client, 'is_connected', False) if destination == 'mqtt' else getattr(client, 'conn', None)
                if not conn_ok:
                    log.info(f"[MockWriter] Reconnecting to {destination}...")
                    if not client.connect():
                        log.error(f"[MockWriter] Failed to reconnect to {destination}. Writer thread stopping.")
                        return

                # Apply rate limiting to prevent tight CPU looping when writer has persistent errors
                time.sleep(1.0)

    finally:
        client.disconnect()
        if csv_file is not None:
            try:
                csv_file.close()
                log.info(f"[MockWriter] CSV file closed: {MOCKUP_CSV_PATH}")
            except:
                pass
        log.info(f"[MockWriter] Writer flushed and disconnected from {destination}.")


# ─── Monitor Thread ───────────────────────────────────────────────────────────
def monitor_thread():
    """Logs pipeline statistics every STATS_INTERVAL_SEC seconds."""
    dest = getattr(config, 'DESTINATION', 'database').lower()
    while not stop_event.is_set():
        time.sleep(config.STATS_INTERVAL_SEC)

        with stats_lock:
            s = dict(stats)
        loss_pct = (s["dropped"] / s["enqueued"] * 100) if s["enqueued"] > 0 else 0.0

        log.info(
            f"[STATS] polled={s['polled']:,} | written={s['written']:,} | "
            f"dropped_batches={s['dropped']} ({loss_pct:.1f}%) | "
            f"db_errors={s['db_errors']} | queue={data_queue.qsize()}/{config.QUEUE_MAXSIZE}"
        )

        # Show a few recent sample values to confirm waveform shape
        with _recent_rows_lock:
            snap = list(_recent_rows)
        if snap:
            log.info(f"[STATS] Last {len(snap)} samples [{dest.upper()}]:")
            for ts, ch, val in snap:
                log.info(f"  {ts.strftime('%H:%M:%S.%f')[:-3]}  ch{ch}  {val:+.4f} V")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    def handle_signal(sig, frame):
        log.info(f"Signal {sig} received — initiating graceful shutdown...")
        stop_event.set()

    signal.signal(signal.SIGINT,  handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Windows: SIGBREAK fires on console close / taskkill without /f
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, handle_signal)

    dest = getattr(config, 'DESTINATION', 'database').lower()
    log.info("=" * 60)
    log.info(f"MOCK DAQ Streaming Pipeline Starting [Destination: {dest.upper()}]")
    log.info("  [No hardware required — synthetic sine wave data]")
    log.info(f"  Channels    : {config.CHANNEL_COUNT} (ch{config.START_CHANNEL}–ch{config.START_CHANNEL + config.CHANNEL_COUNT - 1})")
    log.info(f"  Clock rate  : {config.CLOCK_RATE} Hz")
    log.info(f"  sectionLength: {config.SECTION_LENGTH} samples/ch")
    log.info(f"  Batch size  : {config.USER_BUFFER_SIZE} interleaved samples (~{config.SECTION_LENGTH / config.CLOCK_RATE * 1000:.0f} ms)")
    log.info(f"  Noise std   : {MOCKUP_NOISE_STD_V:.4f} V")
    if dest == 'mqtt':
        log.info(f"  MQTT Broker : {getattr(config, 'MQTT_BROKER', 'localhost')}:{getattr(config, 'MQTT_PORT', 1883)}")
        log.info(f"  MQTT Topic  : {getattr(config, 'MQTT_TOPIC', 'daq/telemetry')}")
    else:
        log.info(f"  DB DSN      : {MOCKUP_MOCKUP_DB_DSN}")
    log.info(f"  CSV output  : {MOCKUP_CSV_PATH or 'disabled'}")
    log.info("=" * 60)

    # ── Bootstrap DB (create database + schema if needed when destination is database) ──
    if dest == 'database':
        try:
            ensure_mockup_db()
        except Exception:
            log.error("DB bootstrap failed — cannot continue. Check MOCKUP_DB_DSN in config.json.")
            sys.exit(1)

    daq_thread = threading.Thread(
        target=mock_daq_reader_thread, name="MockDAQ", daemon=True
    )
    db_thread = threading.Thread(
        target=db_writer_thread, name="MockWriter", daemon=False  # non-daemon: flushes on exit
    )
    mon_thread = threading.Thread(
        target=monitor_thread, name="Monitor", daemon=True
    )

    daq_thread.start()
    db_thread.start()
    mon_thread.start()

    # Wait until stop_event is set (Ctrl+C)
    stop_event.wait()

    log.info("Waiting for data writer to flush remaining queue...")
    db_thread.join(timeout=60)

    if db_thread.is_alive():
        log.warning("Data writer did not finish within 60s timeout.")

    with stats_lock:
        s = dict(stats)
    log.info("=" * 60)
    log.info("Pipeline stopped.")
    log.info(f"  Total polled   : {s['polled']:,} samples")
    log.info(f"  Total sent/wrote: {s['written']:,} rows")
    log.info(f"  Dropped        : {s['dropped']} batches")
    log.info(f"  Errors         : {s['db_errors']}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()

