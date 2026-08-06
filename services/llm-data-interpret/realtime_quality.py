#!/usr/bin/env python3
"""Continuously score recent TimescaleDB samples with the trained model."""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg2 import sql

from machine_ml import DEFAULT_LATEST, DEFAULT_MODEL, atomic_write_json, infer_latest, read_json


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_CONFIG = BASE_DIR / "ml_config.json"
LOGGER = logging.getLogger("realtime_quality")
STOP = threading.Event()


def read_recent_rows(
    connection: Any, table: str, feature_channels: list[int], window_seconds: float
) -> pd.DataFrame:
    parts = table.split(".")
    if len(parts) == 1:
        parts.insert(0, "public")
    if len(parts) != 2 or not all(part and part.replace("_", "a").isalnum() for part in parts):
        raise ValueError("database table must be a table name or schema.table")
    window_start = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT time, channel, value FROM {} WHERE time >= %s AND channel = ANY(%s) ORDER BY time, channel").format(sql.Identifier(*parts)),
            (window_start, feature_channels),
        )
        rows = cursor.fetchall()
    return pd.DataFrame(rows, columns=["time", "channel", "value"])


def connect(database: dict[str, Any]) -> Any:
    import psycopg2

    return psycopg2.connect(
        host=database["host"],
        port=database["port"],
        dbname=database["name"],
        user=database["user"],
        password=database["password"],
        connect_timeout=10,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--config", type=Path, default=DEFAULT_DATABASE_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--window-seconds", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    return parser


def run(args: argparse.Namespace) -> None:
    if args.poll_seconds <= 0 or args.window_seconds <= 0:
        raise ValueError("poll and window seconds must be greater than zero")
    model = read_json(args.model)
    configuration = read_json(args.config)
    database = configuration.get("database_source", configuration.get("database"))
    if not isinstance(database, dict):
        raise ValueError("ML config must contain a database_source object")
    channels = [int(feature["channel"]) for feature in model["features"]]
    connection = connect(database)
    last_sample_time = None
    try:
        while not STOP.is_set():
            if connection.closed:
                connection = connect(database)
            try:
                frame = read_recent_rows(connection, database["table"], channels, args.window_seconds)
                if not frame.empty:
                    frame["time"] = pd.to_datetime(frame["time"], utc=True)
                    result = infer_latest(frame, model)
                    if result["sample_time"] != last_sample_time:
                        atomic_write_json(args.output, result)
                        last_sample_time = result["sample_time"]
                        LOGGER.info(
                            "sample=%s status=%s health=%.1f%%",
                            result["sample_time"],
                            result["machine_quality"]["status"],
                            result["machine_quality"]["health_percent"],
                        )
            except Exception:
                connection.rollback()
                raise
            if args.once:
                return
            STOP.wait(args.poll_seconds)
    finally:
        connection.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    run(build_parser().parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
