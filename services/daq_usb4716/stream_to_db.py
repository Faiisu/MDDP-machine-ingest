#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# See: docs/architecture/context.md

"""
stream_to_db.py
───────────────
DAQ USB-4716 → TimescaleDB streaming pipeline

Architecture (2-thread + Queue):
  ┌──────────────────────────────────────────────────┐
  │ DAQ Thread  (minimal work — poll + raw enqueue)  │
  │  getDataF64() → wall-clock stamp → put(raw)      │
  └─────────────────────┬────────────────────────────┘
                        │ (batch_wall_ts, raw_data, returned_count)
                        ▼
                  Queue (in-memory)
                        │
  ┌─────────────────────▼────────────────────────────┐
  │ DB Writer Thread  (parse + batch INSERT)         │
  │  get(raw) → compute periodic forward ts → INSERT │
  └──────────────────────────────────────────────────┘

Key design decisions:
  - DAQ thread does NO parsing/looping — returns to poll ASAP
  - DB writer owns all CPU-heavy work (parsing interleaved data)
  - Queue.put_nowait() — DAQ NEVER blocks waiting for DB
  - DB writer is non-daemon → flushes queue before process exits

  Time-sync (Periodic Re-anchoring):
  - Base anchor timestamp is established when streaming starts or reset every RECALIBRATE_INTERVAL_HR.
  - Per-sample timestamp is forward-computed cumulatively:
      sample_ts = anchor_time_ns + (samples_since_anchor + s) * dt_ns
  - This eliminates per-batch jitter across buffer seams while periodically
    re-synchronizing with wall-clock time to prevent long-term hardware clock drift.
"""

import sys
import os
import time
import signal
import threading
import logging
import queue
import urllib.request
import urllib.parse
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
try:
    from Automation.BDaq import *
    from Automation.BDaq.WaveformAiCtrl import WaveformAiCtrl
    from Automation.BDaq.BDaqApi import AdxEnumToString, BioFailed
except Exception as _bdaq_err:
    WaveformAiCtrl = None
    AdxEnumToString = None
    BioFailed = Exception

try:
    from services.daq_usb4716.rate_control import ChannelRateLimiter, normalize_channel_sample_rates
except ImportError:
    from rate_control import ChannelRateLimiter, normalize_channel_sample_rates

import json
from types import SimpleNamespace

with open(os.path.join(os.path.dirname(__file__), "config.json"), "r") as f:
    _cfg = json.load(f)
_cfg["USER_BUFFER_SIZE"] = _cfg["SECTION_LENGTH"] * _cfg["CHANNEL_COUNT"]
_cfg["QUEUE_BATCH_SIZE"] = _cfg["USER_BUFFER_SIZE"]
config = SimpleNamespace(**_cfg)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-12s] %(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)

# ─── Shared state ─────────────────────────────────────────────────────────────
# Each item in queue: (batch_wall_ts_ns: int, raw_data: list[float], returned_count: int)
#   batch_wall_ts_ns = time.time_ns() captured right after getDataF64() returns
#   Per-sample ts is forward-computed in DB writer relative to periodic anchor:
#       sample_ts = anchor_time_ns + (samples_since_anchor + s) * dt_ns
data_queue = queue.Queue(maxsize=config.QUEUE_MAXSIZE)
stop_event = threading.Event()

stats_lock = threading.Lock()
stats = {
    "polled":   0,   # total interleaved samples polled from DAQ
    "enqueued": 0,   # total batches enqueued
    "written":  0,   # total rows written to DB
    "dropped":  0,   # batches dropped due to full queue
    "db_errors": 0,  # number of DB insert failures
}


def read_di_snapshot(di_ctrl, start_port, port_count):
    """Read DI bytes while respecting the ports exposed by the device.

    ``InstantDiCtrl.readAny`` returns one byte per port.  A stale config can
    request more ports than a USB-4716 exposes, so clamp the request instead
    of failing the whole acquisition loop.
    """
    start_port = int(start_port)
    port_count = int(port_count)
    if start_port < 0 or port_count < 1:
        raise ValueError('DI start port must be non-negative and port count must be positive.')

    available_ports = getattr(di_ctrl, 'portCount', None)
    if available_ports is not None:
        available_ports = int(available_ports)
        if start_port >= available_ports:
            raise ValueError(
                f'DI start port {start_port} is outside the device port range '
                f'(0-{max(available_ports - 1, 0)}).'
            )
        effective_count = min(port_count, available_ports - start_port)
        if effective_count != port_count:
            log.warning(
                f'DI request clipped from {port_count} to {effective_count} '
                f'port(s); device exposes {available_ports}.'
            )
    else:
        effective_count = port_count

    ret, data = di_ctrl.readAny(start_port, effective_count)
    if BioFailed(ret):
        raise RuntimeError(f'DAQ DI readAny() failed: {ret}')
    return [int(value) & 0xFF for value in data]


# ─── DAQ Reader Thread ────────────────────────────────────────────────────────
def daq_reader_thread():
    """
    Responsibility: poll hardware as fast as possible, enqueue raw AI and DI data.
    Does minimal work — copies returned AI data and reads DI port states, then enqueues.
    """
    enable_ai = getattr(config, 'ENABLE_AI', True)
    di_channels = getattr(config, 'DI_CHANNELS', None)
    enable_di = any(di_channels) if di_channels is not None else getattr(config, 'ENABLE_DI', True)
    di_start_port = int(getattr(config, 'DI_START_PORT', 0))
    di_port_count = int(getattr(config, 'DI_PORT_COUNT', 1))

    wf = None
    di_ctrl = None

    try:
        if enable_ai:
            wf = WaveformAiCtrl(config.DEVICE_DESCRIPTION)
            wf.loadProfile         = config.PROFILE_PATH
            wf.conversion.channelStart = config.START_CHANNEL
            wf.conversion.channelCount = config.CHANNEL_COUNT
            wf.conversion.clockRate    = config.CLOCK_RATE
            wf.record.sectionCount     = config.SECTION_COUNT
            wf.record.sectionLength    = config.SECTION_LENGTH

            for i in range(config.CHANNEL_COUNT):
                wf.channels[config.START_CHANNEL + i].signalType = AiSignalType.SingleEnded
                wf.channels[config.START_CHANNEL + i].valueRange = ValueRange.V_0To5

            ret = wf.prepare()
            if BioFailed(ret):
                log.error("DAQ AI prepare() failed — check device connection and profile.xml")
                stop_event.set()
                return

            ret = wf.start()
            if BioFailed(ret):
                log.error("DAQ AI start() failed")
                stop_event.set()
                return

            log.info(
                f"DAQ AI started | device={config.DEVICE_DESCRIPTION} | "
                f"channels={config.CHANNEL_COUNT} | clock={config.CLOCK_RATE} Hz | "
                f"sectionLength={config.SECTION_LENGTH} | userBuffer={config.USER_BUFFER_SIZE}"
            )

        if enable_di:
            try:
                from Automation.BDaq.InstantDiCtrl import InstantDiCtrl
                di_ctrl = InstantDiCtrl(config.DEVICE_DESCRIPTION)
                if hasattr(di_ctrl, 'loadProfile'):
                    di_ctrl.loadProfile = config.PROFILE_PATH
                available_di_ports = getattr(di_ctrl, 'portCount', None)
                if available_di_ports is not None:
                    available_di_ports = int(available_di_ports)
                    if di_start_port >= available_di_ports:
                        raise ValueError(
                            f"start port {di_start_port} is outside the device range "
                            f"(0-{max(available_di_ports - 1, 0)})"
                        )
                    effective_di_port_count = min(di_port_count, available_di_ports - di_start_port)
                    if effective_di_port_count != di_port_count:
                        log.warning(
                            f"Configured DI port count {di_port_count} exceeds the device's "
                            f"{available_di_ports} port(s); using {effective_di_port_count}."
                        )
                        di_port_count = effective_di_port_count
                log.info(
                    f"DAQ DI initialized | device={config.DEVICE_DESCRIPTION} | "
                    f"startPort={di_start_port} | portCount={di_port_count}"
                )
            except Exception as di_err:
                log.error(f"Failed to initialize InstantDiCtrl: {di_err}")
                di_ctrl = None

        log.info("DAQ loop started — periodic wall-clock re-anchoring active")

        while not stop_event.is_set():
            ai_raw_copy = []
            returned_count = 0

            if enable_ai and wf is not None:
                result = wf.getDataF64(config.USER_BUFFER_SIZE, -1)
                batch_wall_ts_ns = time.time_ns()
                ret, returned_count, raw_data = result[0], result[1], result[2]

                if BioFailed(ret):
                    log.error("getDataF64() error — stopping DAQ thread")
                    stop_event.set()
                    break

                if returned_count <= 0:
                    continue

                ai_raw_copy = list(raw_data[:returned_count])
            else:
                block_dur = float(config.SECTION_LENGTH) / float(config.CLOCK_RATE)
                time.sleep(block_dur)
                batch_wall_ts_ns = time.time_ns()

            di_bytes = []
            if enable_di and di_ctrl is not None:
                try:
                    di_bytes = read_di_snapshot(di_ctrl, di_start_port, di_port_count)
                except Exception as read_di_err:
                    log.warning(f"Error reading DI: {read_di_err}")

            try:
                data_queue.put_nowait((batch_wall_ts_ns, ai_raw_copy, returned_count, di_bytes))
                with stats_lock:
                    stats["polled"]   += returned_count + (len(di_bytes) * 8 if returned_count == 0 else 0)
                    stats["enqueued"] += 1
            except queue.Full:
                with stats_lock:
                    stats["dropped"] += 1
                log.warning(
                    f"Queue full! Dropped 1 batch ({returned_count} AI samples)."
                )

    except Exception as e:
        log.exception(f"Unhandled exception in DAQ Reader thread: {e}")
        stop_event.set()
    finally:
        if wf is not None:
            try:
                wf.stop()
                wf.release()
                wf.dispose()
                log.info("DAQ AI thread stopped and device released.")
            except Exception:
                pass
        if di_ctrl is not None:
            try:
                di_ctrl.cleanup()
                di_ctrl.dispose()
                log.info("DAQ DI controller released.")
            except Exception:
                pass



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
    def __init__(self, start_channel, channel_count, clock_rate, calibrator, di_channel_offset=100, enable_di=True, di_channels=None, channel_sample_rates=None, recalibrate_interval_hr=24.0):
        self.start_channel = start_channel
        self.channel_count = channel_count
        self.dt_ns = int(1_000_000_000 / clock_rate)
        self.calibrator = calibrator
        self.di_channel_offset = di_channel_offset
        self.enable_di = enable_di
        self.di_channels = None if di_channels is None else {
            int(bit) for bit, selected in enumerate(di_channels) if selected
        }
        self.channel_sample_rates = normalize_channel_sample_rates(
            channel_sample_rates or {},
            hardware_rate=clock_rate,
            section_length=getattr(config, 'SECTION_LENGTH', 500),
        )
        self.rate_limiter = ChannelRateLimiter(self.channel_sample_rates)
        
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
        batch_sample_ts_ns = self.anchor_time_ns + self.samples_since_anchor * self.dt_ns
        batch_sample_ts = datetime.fromtimestamp(batch_sample_ts_ns / 1_000_000_000, tz=timezone.utc)
        for s in range(samples_per_channel):
            # Calculate forward timestamp based on cumulative samples since the last anchor
            sample_ts_ns = self.anchor_time_ns + (self.samples_since_anchor + s) * self.dt_ns
            sample_ts = datetime.fromtimestamp(sample_ts_ns / 1_000_000_000, tz=timezone.utc)

            # Process Analog Input channels
            if returned_count > 0 and self.channel_count > 0:
                for ch in range(self.channel_count):
                    channel_key = f'AI{self.start_channel + ch}'
                    if not self.rate_limiter.should_emit(channel_key, sample_ts_ns):
                        continue
                    value = raw_data[s * self.channel_count + ch]
                    value = self.calibrator.calibrate(ch, value)
                    value = round(value, 3)
                    rows.append((sample_ts, self.start_channel + ch, value))

        # InstantDiCtrl gives one snapshot per poll, not one value for every
        # AI sample in the batch.  Persist that snapshot once at the batch
        # timestamp; expanding it across the AI block manufactures stale DI
        # samples and massively inflates storage.
        if self.enable_di and di_bytes:
            for port_idx, port_val in enumerate(di_bytes):
                for bit_idx in range(8):
                    logical_bit = (port_idx * 8) + bit_idx
                    if self.di_channels is not None and logical_bit not in self.di_channels:
                        continue
                    if not self.rate_limiter.should_emit(f'DI{logical_bit}', batch_sample_ts_ns):
                        continue
                    di_ch_index = self.di_channel_offset + logical_bit
                    bit_val = float((port_val >> bit_idx) & 1)
                    rows.append((batch_sample_ts, di_ch_index, bit_val))
                
        # Advance cumulative sample count for the next batch
        self.samples_since_anchor += samples_per_channel
        return rows


def ensure_db_and_tables(dsn):
    """
    Auto-creates database if missing and auto-creates required tables/hypertable/indexes if missing.
    """
    try:
        import psycopg2.extensions
        parsed = psycopg2.extensions.make_dsn(dsn)
        parts = psycopg2.extensions.parse_dsn(parsed)
        target_dbname = parts.get("dbname")

        if target_dbname:
            maint_parts = dict(parts)
            maint_parts["dbname"] = "postgres"
            maint_dsn = psycopg2.extensions.make_dsn(**maint_parts)
            try:
                maint_conn = psycopg2.connect(maint_dsn, connect_timeout=5)
                maint_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
                with maint_conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_dbname,))
                    if not cur.fetchone():
                        log.info(f"[DBSetup] Database '{target_dbname}' does not exist. Creating database...")
                        cur.execute(f'CREATE DATABASE "{target_dbname}"')
                        log.info(f"[DBSetup] Database '{target_dbname}' created successfully.")
                maint_conn.close()
            except Exception as me:
                log.warning(f"[DBSetup] Maintenance DB check/creation warning: {me}")

        target_conn = psycopg2.connect(dsn, connect_timeout=5)
        target_conn.autocommit = True
        with target_conn.cursor() as cur:
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
            except Exception:
                pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS daq_samples (
                    time        TIMESTAMPTZ      NOT NULL,
                    channel     SMALLINT         NOT NULL,
                    value       DOUBLE PRECISION NOT NULL
                );
            """)

            try:
                cur.execute("SELECT create_hypertable('daq_samples', 'time', if_not_exists => TRUE);")
            except Exception:
                pass

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_daq_channel_time
                    ON daq_samples (channel, time DESC);
            """)

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
        target_conn.close()
        log.info("[DBSetup] Database and table schema verified/auto-created.")
        return True
    except Exception as e:
        log.error(f"[DBSetup] Auto creation of database/tables failed: {e}")
        return False


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
                ensure_db_and_tables(self.dsn)
                self.conn = psycopg2.connect(self.dsn)
                self.conn.autocommit = False
                self.cur = self.conn.cursor()
                db_desc = f" '{self.dbname}'" if self.dbname else ""
                log.info(f"Connected to database{db_desc}")
                return True
            except Exception as e:
                log.error(f"DB connection failed: {e} — retrying in 5s")
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
            log.warning(f"Database insert failed ({e}). Auto-creating database/tables and retrying...")
            if ensure_db_and_tables(self.dsn):
                try:
                    self.conn = psycopg2.connect(self.dsn)
                    self.conn.autocommit = False
                    self.cur = self.conn.cursor()
                    psycopg2.extras.execute_values(
                        self.cur, INSERT_SQL, rows, page_size=page_size
                    )
                    self.conn.commit()
                    log.info("Insertion succeeded after auto-creating database/tables.")
                    return
                except Exception as retry_err:
                    log.error(f"Retry insertion after auto-creation failed: {retry_err}")
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
        log.info("Disconnected from database.")


class MQTTClient:
    """
    Responsibility: Manage MQTT connection lifecycle and publishing telemetry samples to an MQTT broker.
    """
    def __init__(self, broker, port, topic, qos=0, username=None, password=None, tls_enabled=False, ca_certs=None, certfile=None, keyfile=None, stop_event=None, client_id="daq_publisher"):
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
                        log.info(f"Connected to MQTT broker at {self.broker}:{self.port}")
                    else:
                        self.is_connected = False
                        log.error(f"MQTT connection failed with code {rc}")

                def on_disconnect(client, userdata, rc, properties=None):
                    self.is_connected = False
                    log.warning("Disconnected from MQTT broker")

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

                log.warning(f"MQTT connect timeout ({self.broker}:{self.port}) — retrying in 5s")
                self.disconnect()
            except Exception as e:
                log.error(f"MQTT connection error: {e} — retrying in 5s")

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
        log.info("Disconnected from MQTT broker.")


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
        self.is_connected = False
        self.write_url = f"{self.url}/api/v2/write?org={urllib.parse.quote(self.org)}&bucket={urllib.parse.quote(self.bucket)}&precision=ns"

    def connect(self):
        target_url = f"{self.url}/health"
        headers = {"User-Agent": "USB4716-Writer"}
        if self.token:
            headers["Authorization"] = f"Token {self.token}"
        try:
            req = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status in (200, 204):
                    self.is_connected = True
                    log.info(f"Connected to InfluxDB at {self.url} (Org: {self.org}, Bucket: {self.bucket})")
                    return True
                else:
                    self.is_connected = False
                    log.warning(f"InfluxDB health check returned HTTP status {resp.status}")
                    return True
        except Exception as e:
            log.warning(f"InfluxDB health check notice ({e}). Client will attempt line protocol writes.")
            self.is_connected = True
            return True

    def send_samples(self, rows, page_size=1000):
        if not rows:
            return
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "application/json"
        }
        if self.token:
            headers["Authorization"] = f"Token {self.token}"

        for i in range(0, len(rows), page_size):
            chunk = rows[i:i + page_size]
            lines = []
            for (sample_ts, ch_idx, val) in chunk:
                if isinstance(sample_ts, datetime):
                    ts_ns = int(sample_ts.timestamp() * 1_000_000_000)
                elif isinstance(sample_ts, (int, float)):
                    ts_ns = int(sample_ts * 1e9) if sample_ts < 1e11 else int(sample_ts)
                else:
                    ts_ns = int(time.time() * 1_000_000_000)
                lines.append(f"{self.measurement},ch={ch_idx} value={val} {ts_ns}")

            body = "\n".join(lines).encode('utf-8')
            req = urllib.request.Request(self.write_url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                if resp.status not in (200, 204):
                    raise Exception(f"InfluxDB HTTP status {resp.status}")
        self.is_connected = True

    def insert_batch(self, batch_tuples):
        self.send_samples(batch_tuples)

    def publish_batch(self, batch_tuples):
        self.send_samples(batch_tuples)

    def rollback(self):
        pass

    def disconnect(self):
        self.is_connected = False
        log.info("InfluxDB client disconnected.")


# ─── Data Writer Thread ───────────────────────────────────────────────────────
def db_writer_thread():
    """
    Responsibility: dequeue raw batches, delegate parsing, delegate writing/publishing.
    Supports TimescaleDB, InfluxDB, and MQTT publishing based on config.DESTINATION.
    Non-daemon thread — will flush remaining queue items before process exits.
    """
    di_channels = getattr(config, 'DI_CHANNELS', None)
    enable_di = any(di_channels) if di_channels is not None else getattr(config, 'ENABLE_DI', True)

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
        enable_di=enable_di,
        di_channels=di_channels,
        channel_sample_rates=getattr(config, 'CHANNEL_SAMPLE_RATES', {}),
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
        client = TimescaleDBClient(config.DB_DSN, stop_event)

    if not client.connect():
        log.info(f"Writer thread exiting ({destination} connection failed).")
        return

    log.info(f"Writer thread ready ({destination} mode)...")

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

        # 2. Write/Publish samples (SRP delegation)
        try:
            client.send_samples(rows, page_size=config.DB_PAGE_SIZE)
            with stats_lock:
                stats["written"] += len(rows)
        except Exception as e:
            with stats_lock:
                stats["db_errors"] += 1
            log.error(f"Writer output error ({destination}): {e} — attempting recovery...")

            # Attempt rollback
            try:
                client.rollback()
            except Exception as rb_err:
                log.error(f"Rollback failed: {rb_err} — connection is dead. Closing resources.")
                client.disconnect()

            # Re-enqueue so data is not lost (best-effort)
            try:
                data_queue.put_nowait(item)
            except queue.Full:
                with stats_lock:
                    stats["dropped"] += 1
                log.error("Queue full on re-queue — batch permanently lost!")

            # Reconnect if connection was lost
            conn_ok = getattr(client, 'is_connected', False) if destination in ('mqtt', 'influxdb') else getattr(client, 'conn', None)
            if not conn_ok:
                log.info(f"Reconnecting to {destination}...")
                if not client.connect():
                    log.error(f"Failed to reconnect to {destination}. Writer thread stopping.")
                    return

            # Apply rate limiting to prevent tight CPU looping when writer has persistent errors
            time.sleep(1.0)

    client.disconnect()



# ─── Monitor Thread ───────────────────────────────────────────────────────────
def monitor_thread():
    """Logs pipeline statistics every STATS_INTERVAL_SEC seconds."""
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
    log.info(f"DAQ Streaming Pipeline Starting [Destination: {dest.upper()}]")
    log.info(f"  Channels    : {config.CHANNEL_COUNT} (ch{config.START_CHANNEL}–ch{config.START_CHANNEL + config.CHANNEL_COUNT - 1})")
    log.info(f"  Clock rate  : {config.CLOCK_RATE} Hz")
    log.info(f"  sectionLength: {config.SECTION_LENGTH} samples/ch")
    log.info(f"  Batch size  : {config.USER_BUFFER_SIZE} interleaved samples (~{config.SECTION_LENGTH / config.CLOCK_RATE * 1000:.0f}ms)")
    if dest == 'mqtt':
        log.info(f"  MQTT Broker : {getattr(config, 'MQTT_BROKER', 'localhost')}:{getattr(config, 'MQTT_PORT', 1883)}")
        log.info(f"  MQTT Topic  : {getattr(config, 'MQTT_TOPIC', 'daq/telemetry')}")
    else:
        log.info(f"  DB DSN      : {config.DB_DSN}")
    log.info("=" * 60)

    daq_thread = threading.Thread(
        target=daq_reader_thread, name="DAQ-Reader", daemon=True
    )
    db_thread = threading.Thread(
        target=db_writer_thread, name="DB-Writer", daemon=False  # non-daemon: flushes on exit
    )
    mon_thread = threading.Thread(
        target=monitor_thread, name="Monitor", daemon=True
    )

    daq_thread.start()
    db_thread.start()
    mon_thread.start()

    # Wait until stop_event is set (Ctrl+C or DAQ error)
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
