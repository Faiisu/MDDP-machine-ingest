#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
mqtt_to_db.py
─────────────
Standalone MQTT subscriber daemon for MDDP Ingestion Control Suite.

Subscribes to MQTT telemetry topic (configured in config.json), parses incoming
sample payloads, and writes them into TimescaleDB.
"""

import os
import sys
import time
import json
import signal
import logging
import threading
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import paho.mqtt.client as mqtt

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
except Exception as e:
    print(f"Error loading config.json: {e}")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-12s] %(levelname)s: %(message)s",
)
log = logging.getLogger("mqtt_to_db")

stop_event = threading.Event()
stats_lock = threading.Lock()
stats = {
    "messages_received": 0,
    "rows_inserted": 0,
    "db_errors": 0,
}

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
    def __init__(self, dsn, stop_event):
        self.dsn = dsn
        self.stop_event = stop_event
        self.conn = None
        self.cur = None

    def connect(self):
        while not self.stop_event.is_set():
            try:
                ensure_db_and_tables(self.dsn)
                self.conn = psycopg2.connect(self.dsn)
                self.conn.autocommit = False
                self.cur = self.conn.cursor()
                log.info("Connected to TimescaleDB.")
                return True
            except Exception as e:
                log.error(f"DB connection failed: {e} — retrying in 5s")
                for _ in range(50):
                    if self.stop_event.is_set():
                        return False
                    time.sleep(0.1)
        return False

    def insert_samples(self, rows):
        if not self.conn or not self.cur:
            raise RuntimeError("Not connected to database")
        INSERT_SQL = "INSERT INTO daq_samples (time, channel, value) VALUES %s"
        try:
            psycopg2.extras.execute_values(self.cur, INSERT_SQL, rows, page_size=1000)
            self.conn.commit()
        except Exception as e:
            self.rollback()
            log.warning(f"Database insert failed ({e}). Auto-creating database/tables and retrying...")
            if ensure_db_and_tables(self.dsn):
                try:
                    self.conn = psycopg2.connect(self.dsn)
                    self.conn.autocommit = False
                    self.cur = self.conn.cursor()
                    psycopg2.extras.execute_values(self.cur, INSERT_SQL, rows, page_size=1000)
                    self.conn.commit()
                    log.info("Insertion succeeded after auto-creating database/tables.")
                    return
                except Exception as retry_err:
                    log.error(f"Retry insertion after auto-creation failed: {retry_err}")
            raise

    def rollback(self):
        if self.conn:
            self.conn.rollback()

    def disconnect(self):
        if self.cur:
            try: self.cur.close()
            except: pass
        if self.conn:
            try: self.conn.close()
            except: pass
        log.info("Disconnected from database.")

def main():
    def handle_signal(sig, frame):
        log.info(f"Signal {sig} received — shutting down subscriber...")
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Windows: SIGBREAK fires on console close / taskkill without /f
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, handle_signal)

    username = config.get("MQTT_USERNAME", "")
    password = config.get("MQTT_PASSWORD", "")
    tls_enabled = config.get("MQTT_TLS_ENABLED", False)
    ca_certs = config.get("MQTT_CA_CERTS", "")
    client_cert = config.get("MQTT_CLIENT_CERT", "")
    client_key = config.get("MQTT_CLIENT_KEY", "")

    log.info("=" * 60)
    log.info("MQTT Telemetry Subscriber → TimescaleDB Starting")
    log.info(f"  Broker : {broker}:{port}")
    log.info(f"  Topic  : {topic} (QoS {qos})")
    log.info(f"  DB DSN : {dsn}")
    log.info(f"  Auth   : {'Enabled' if username else 'Anonymous'}")
    log.info(f"  TLS    : {'Enabled' if tls_enabled else 'Disabled'}")
    log.info("=" * 60)

    db_client = TimescaleDBClient(dsn, stop_event)
    if not db_client.connect():
        log.error("Could not connect to database. Exiting.")
        sys.exit(1)

    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="daq_mqtt_subscriber")
    except (AttributeError, TypeError):
        mqtt_client = mqtt.Client(client_id="daq_mqtt_subscriber")

    if username:
        mqtt_client.username_pw_set(username, password or None)

    if tls_enabled:
        ca = ca_certs if (ca_certs and os.path.exists(ca_certs)) else None
        cert = client_cert if (client_cert and os.path.exists(client_cert)) else None
        key = client_key if (client_key and os.path.exists(client_key)) else None
        mqtt_client.tls_set(ca_certs=ca, certfile=cert, keyfile=key)

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info(f"Subscribed to topic '{topic}' at broker {broker}:{port}")
            client.subscribe(topic, qos=qos)
        else:
            log.error(f"MQTT connect failed with code {rc}")

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(payload, list):
                payload = [payload]
            
            rows = []
            for item in payload:
                ts_str = item.get("time")
                ch = int(item.get("channel"))
                val = float(item.get("value"))
                ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now(timezone.utc)
                rows.append((ts, ch, val))

            if rows:
                db_client.insert_samples(rows)
                with stats_lock:
                    stats["messages_received"] += 1
                    stats["rows_inserted"] += len(rows)

        except Exception as e:
            log.error(f"Error processing MQTT message: {e}")
            with stats_lock:
                stats["db_errors"] += 1

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(broker, port, keepalive=60)
        mqtt_client.loop_start()
    except Exception as e:
        log.error(f"Failed to connect to MQTT broker: {e}")
        db_client.disconnect()
        sys.exit(1)

    while not stop_event.is_set():
        time.sleep(10)
        with stats_lock:
            s = dict(stats)
        log.info(f"[STATS] messages_received={s['messages_received']:,} | rows_inserted={s['rows_inserted']:,} | db_errors={s['db_errors']}")

    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    db_client.disconnect()
    log.info("Subscriber stopped.")

if __name__ == "__main__":
    main()
