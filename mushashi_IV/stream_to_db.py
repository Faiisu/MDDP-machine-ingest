#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stream_to_db.py
───────────────
Musashi IV Data Ingestion Daemon.
Periodically fetches channel data from Musashi IV REST API, formats response,
and inserts into TimescaleDB / PostgreSQL database.
"""

import os
import sys
import time
import json
import signal
import threading
import logging
from datetime import datetime, timezone
import math
import random

import psycopg2
import psycopg2.extras

from api_client import fetch_channel_data, format_channel_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"Failed to load config.json: {e}")
    return {
        "API_URL": "http://172.16.48.198:1025/v1/info/channel/data/1",
        "CHANNEL_NO": 1,
        "TIME_INTERVAL": 1.0,
        "DB_DSN": "postgresql://admin:admin@localhost:5432/daq_db",
        "MOCKUP_MODE": True,
        "STATS_INTERVAL_SEC": 5
    }

def ensure_database_exists(dsn):
    """
    Checks if the database in DSN exists; if missing, auto-creates it using the 'postgres' maintenance DB.
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
                        log.info(f"Database '{target_dbname}' does not exist. Creating database...")
                        cur.execute(f'CREATE DATABASE "{target_dbname}"')
                        log.info(f"Database '{target_dbname}' auto-created successfully.")
                maint_conn.close()
            except Exception as me:
                log.warning(f"Maintenance DB check/creation warning: {me}")
    except Exception as e:
                log.warning(f"Failed to check/create database: {e}")

def get_db_connection(dsn, retries=3, delay=1.0):
    ensure_database_exists(dsn)
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(dsn, connect_timeout=5)
            conn.autocommit = True
            return conn
        except Exception as e:
            if attempt == retries:
                log.error(f"Database connection failed after {retries} attempts: {e}")
                raise
            time.sleep(delay)

def init_db_schema(conn):
    """
    Creates table musashi_iv_data and TimescaleDB hypertable if available.
    """
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS musashi_iv_data (
        time TIMESTAMPTZ NOT NULL,
        ch_no INT NOT NULL,
        shot_mode INT,
        dis_press DOUBLE PRECISION,
        dis_vacuum DOUBLE PRECISION,
        dis_time DOUBLE PRECISION,
        ch_name VARCHAR(255),
        syringe_size INT,
        tube_length DOUBLE PRECISION,
        use_plunger INT,
        air_eco INT,
        on_delay DOUBLE PRECISION,
        off_delay DOUBLE PRECISION,
        watch_permit DOUBLE PRECISION,
        watch_min_off_time DOUBLE PRECISION,
        watch_result INT,
        sigma_mode INT,
        dummy_shot INT,
        vol_red_corr INT,
        corr_alpha INT,
        corr_delta INT,
        drop_prevent INT,
        corr_vac DOUBLE PRECISION,
        rsm_detect INT,
        rsm_level INT,
        rsm_count INT,
        rsm_corr_on_off INT,
        rsm_corr INT,
        rsm_measure JSONB,
        rsm_user_set JSONB,
        d0 INT,
        d1 JSONB,
        d2 JSONB,
        d3 JSONB,
        bkup_corr_time DOUBLE PRECISION,
        bkup_corr_press DOUBLE PRECISION,
        bkup_corr_vac DOUBLE PRECISION,
        raw_json JSONB,
        PRIMARY KEY (time, ch_no)
    );
    """
    with conn.cursor() as cur:
        cur.execute(create_table_sql)
        # Attempt creating TimescaleDB hypertable
        try:
            cur.execute("SELECT create_hypertable('musashi_iv_data', 'time', if_not_exists => TRUE);")
            log.info("TimescaleDB hypertable 'musashi_iv_data' ensured.")
        except Exception:
            # PostgreSQL without TimescaleDB extension active
            pass

def generate_mock_payload(ch_no=1):
    t = time.time()
    dis_press = round(40.0 + 2.5 * math.sin(t / 5.0) + random.uniform(-0.2, 0.2), 2)
    dis_vac = round(max(0.0, 0.05 * math.cos(t / 10.0)), 2)
    dis_time = round(1.000 + 0.01 * math.sin(t / 3.0), 3)

    return {
        "ch": [
            {
                "no": ch_no,
                "shotMode": 0,
                "disPress": dis_press,
                "disVacuum": dis_vac,
                "disTime": dis_time,
                "chName": f"CH_{ch_no}_MOCK",
                "syringeSize": 0,
                "tubeLength": 1.0,
                "usePlunger": 0,
                "airEco": 0,
                "onDelay": 0.000,
                "offDelay": 0.000,
                "watchPermit": 100.0,
                "watchMinOffTime": 0.500,
                "watchResult": 0,
                "sigmaMode": 0,
                "dummyShot": 0,
                "volRedCorr": 1,
                "corrAlpha": 0,
                "corrDelta": 100,
                "dropPrevent": 1,
                "corrVac": 0.00,
                "rsmDetect": 1,
                "rsmLevel": 10,
                "rsmCount": 5,
                "rsmCorrOnOff": 0,
                "rsmCorr": 0,
                "rsmMeasure": [0,0,0,0,0,0,0,0,0,0],
                "rsmUserSet": [0,0,0,0,0,0,0,0,0,0],
                "d0": 100,
                "d1": [255,255,255,255,255,255,255,255],
                "d2": [255,255,255,255,255,255,255,255],
                "d3": [255,255,255,255],
                "bkupCorrTime": 0.000,
                "bkupCorrPress": 0.0,
                "bkupCorrVac": 0.00
            }
        ]
    }

def insert_record(conn, rec):
    sql = """
    INSERT INTO musashi_iv_data (
        time, ch_no, shot_mode, dis_press, dis_vacuum, dis_time, ch_name, syringe_size,
        tube_length, use_plunger, air_eco, on_delay, off_delay, watch_permit,
        watch_min_off_time, watch_result, sigma_mode, dummy_shot, vol_red_corr,
        corr_alpha, corr_delta, drop_prevent, corr_vac, rsm_detect, rsm_level,
        rsm_count, rsm_corr_on_off, rsm_corr, rsm_measure, rsm_user_set, d0,
        d1, d2, d3, bkup_corr_time, bkup_corr_press, bkup_corr_vac, raw_json
    ) VALUES (
        %(time)s, %(ch_no)s, %(shot_mode)s, %(dis_press)s, %(dis_vacuum)s, %(dis_time)s,
        %(ch_name)s, %(syringe_size)s, %(tube_length)s, %(use_plunger)s, %(air_eco)s,
        %(on_delay)s, %(off_delay)s, %(watch_permit)s, %(watch_min_off_time)s,
        %(watch_result)s, %(sigma_mode)s, %(dummy_shot)s, %(vol_red_corr)s,
        %(corr_alpha)s, %(corr_delta)s, %(drop_prevent)s, %(corr_vac)s, %(rsm_detect)s,
        %(rsm_level)s, %(rsm_count)s, %(rsm_corr_on_off)s, %(rsm_corr)s, %(rsm_measure)s,
        %(rsm_user_set)s, %(d0)s, %(d1)s, %(d2)s, %(d3)s, %(bkup_corr_time)s,
        %(bkup_corr_press)s, %(bkup_corr_vac)s, %(raw_json)s
    ) ON CONFLICT (time, ch_no) DO NOTHING;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, rec)
    except Exception as e:
        log.warning(f"Insert failed ({e}). Auto-initializing database/schema and retrying...")
        init_db_schema(conn)
        with conn.cursor() as cur:
            cur.execute(sql, rec)

def run_ingestion():
    cfg = load_config()
    api_url = cfg.get("API_URL", "http://172.16.48.198:1025/v1/info/channel/data/1")
    interval = float(cfg.get("TIME_INTERVAL", 1.0))
    mock_mode = cfg.get("MOCKUP_MODE", True)
    dsn = cfg.get("MOCKUP_DB_DSN") if mock_mode else cfg.get("DB_DSN")

    log.info(f"Starting Musashi IV Ingestion Pipeline | API_URL={api_url} | Interval={interval}s | Mockup={mock_mode}")

    db_conn = None
    try:
        db_conn = get_db_connection(dsn)
        init_db_schema(db_conn)
        log.info("Database initialized successfully.")
    except Exception as e:
        log.warning(f"Database connection warning: {e}. Pipeline will continue and log records.")

    polled = 0
    written = 0
    errors = 0
    running = True

    def sig_handler(sig, frame):
        nonlocal running
        log.info("Termination signal received. Shutting down Musashi IV Ingestion Pipeline...")
        running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    # Windows: SIGBREAK fires on console close / taskkill without /f
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, sig_handler)

    last_stats_time = time.time()

    while running:
        loop_start = time.time()
        now_ts = datetime.now(timezone.utc)
        polled += 1
        raw_payload = None

        # Fetch data from API or fall back to mock payload if mock mode is active
        res = fetch_channel_data(api_url, timeout=3.0)
        if res["success"]:
            raw_payload = res["data"]
        else:
            if mock_mode:
                raw_payload = generate_mock_payload(cfg.get("CHANNEL_NO", 1))
            else:
                log.error(f"API Fetch failed: {res['error']}")
                errors += 1

        if raw_payload:
            try:
                rec = format_channel_data(raw_payload, timestamp=now_ts)
                if db_conn:
                    try:
                        insert_record(db_conn, rec)
                        written += 1
                    except Exception as e:
                        log.error(f"DB Insert error: {e}")
                        errors += 1
                        try:
                            db_conn = get_db_connection(dsn)
                        except Exception:
                            pass
                else:
                    # Log write when DB is offline
                    written += 1

                last_press = rec["dis_press"]
                last_vac = rec["dis_vacuum"]
                last_time = rec["dis_time"]
            except Exception as e:
                log.error(f"Formatting error: {e}")
                errors += 1

        # Emit periodic stats line
        if time.time() - last_stats_time >= cfg.get("STATS_INTERVAL_SEC", 5):
            last_stats_time = time.time()
            log.info(
                f"[STATS] polled={polled:,} | written={written:,} | db_errors={errors} | "
                f"last_press={rec.get('dis_press', 0.0):.2f} | last_vac={rec.get('dis_vacuum', 0.0):.2f} | "
                f"last_time={rec.get('dis_time', 0.0):.3f}"
            )

        elapsed = time.time() - loop_start
        sleep_dur = max(0.01, interval - elapsed)
        time.sleep(sleep_dur)

    if db_conn:
        try: db_conn.close()
        except: pass
    log.info("Musashi IV Ingestion Pipeline stopped.")

if __name__ == "__main__":
    run_ingestion()
