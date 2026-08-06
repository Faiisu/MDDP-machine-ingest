"""Generate one sample per configured DAQ or machine telemetry channel."""
from __future__ import annotations

import json
import logging
import math
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
from psycopg2 import sql

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOGGER = logging.getLogger("simulator")
STOP = threading.Event()


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as file:
        config = json.load(file)
    if config.get("period_seconds", 1) <= 0:
        raise ValueError("period_seconds must be greater than zero")
    return config


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def machine_state(elapsed: float, machine: dict | None = None) -> dict[str, float]:
    """Return deterministic operating conditions shared by machine signals.

    The cycle deliberately contains known healthy, warning, and critical
    regions. Deterministic multi-frequency noise keeps simulations repeatable
    while still looking like sampled sensors.
    """

    settings = machine or {}
    cycle_seconds = max(float(settings.get("cycle_seconds", 300)), 1.0)
    normal_fraction = float(settings.get("normal_fraction", 0.60))
    warning_fraction = float(settings.get("warning_fraction", 0.25))
    if normal_fraction <= 0 or warning_fraction <= 0 or normal_fraction + warning_fraction >= 1:
        raise ValueError("machine fractions must be positive and sum to less than one")

    phase = (elapsed % cycle_seconds) / cycle_seconds
    if not settings.get("faults_enabled", True) or phase < normal_fraction:
        health_state = 0.0
        severity = 0.0
    elif phase < normal_fraction + warning_fraction:
        health_state = 1.0
        progress = (phase - normal_fraction) / warning_fraction
        severity = 0.15 + 0.40 * _smoothstep(progress)
    else:
        health_state = 2.0
        progress = (phase - normal_fraction - warning_fraction) / (1 - normal_fraction - warning_fraction)
        severity = 0.60 + 0.40 * _smoothstep(progress)

    load = 0.62 + 0.20 * math.sin(2 * math.pi * elapsed / 47) + 0.06 * math.sin(2 * math.pi * elapsed / 13)
    load = max(0.25, min(0.95, load))
    noise = (
        math.sin(elapsed * 1.731)
        + 0.55 * math.sin(elapsed * 3.117 + 0.8)
        + 0.25 * math.sin(elapsed * 7.913 + 1.7)
    ) / 1.8
    return {"load": load, "severity": severity, "health_state": health_state, "noise": noise}


def machine_signal_value(signal_name: str, elapsed: float, machine: dict | None = None) -> float:
    """Generate one realistic sensor value from the shared machine state."""

    state = machine_state(elapsed, machine)
    load, severity, noise = state["load"], state["severity"], state["noise"]
    bearing_wave = math.sin(2 * math.pi * elapsed * 0.43)
    fault_wave = math.sin(2 * math.pi * elapsed * 1.7) + 0.35 * math.sin(2 * math.pi * elapsed * 3.4)
    values = {
        "speed_rpm": 1480 + 65 * (load - 0.6) - 85 * severity + 5 * noise,
        "load_percent": 100 * load,
        "vibration_mm_s": 1.05 + 1.35 * load + 0.13 * noise + severity * (4.8 + 0.9 * fault_wave),
        "bearing_temperature_c": 37 + 22 * load + 20 * severity + 0.45 * noise + 0.6 * bearing_wave,
        "motor_current_a": 2.4 + 8.8 * load + 3.8 * severity + 0.18 * noise,
        "displacement_mm": 0.035 + 0.055 * load + 0.18 * severity + 0.008 * noise,
        "acoustic_db": 52 + 13 * load + 18 * severity + 0.8 * noise + 0.7 * bearing_wave,
        "health_state": state["health_state"],
    }
    try:
        return float(values[signal_name])
    except KeyError as exc:
        raise ValueError(f"unsupported machine signal: {signal_name}") from exc


def value_for_channel(channel: dict, elapsed: float, machine: dict | None = None) -> float:
    if channel["type"].lower() == "machine":
        return machine_signal_value(channel["signal"], elapsed, machine)
    if channel["type"].lower() == "digital":
        stages = channel.get("stages")
        if stages is not None:
            if not isinstance(stages, list) or not stages:
                raise ValueError("digital stages must be a non-empty list")
            if any(value not in (0, 1) for value in stages):
                raise ValueError("digital stages may contain only 0 or 1")
            period = float(channel.get("stage_period_seconds", 1))
            return float(stages[0] if period <= 0 else stages[int(elapsed / period) % len(stages)])

        # Backward-compatible two-stage toggle configuration.
        period = float(channel.get("toggle_period_seconds", 1))
        return float(channel.get("value", 0)) if period <= 0 else float(
            int(elapsed / period) % 2 if channel.get("toggle", True) else channel.get("value", 0)
        )
    if channel["type"].lower() != "equation":
        raise ValueError(f"unsupported channel type: {channel['type']}")
    allowed = {name: getattr(math, name) for name in dir(math) if not name.startswith("_")}
    allowed.update({"t": elapsed, "time": elapsed})
    return float(eval(channel["equation"], {"__builtins__": {}}, allowed))


def values_for_channels(
    channels: list[dict], elapsed: float, machine: dict | None = None
) -> dict[int, float]:
    """Calculate channel values, adding the current values of dependencies."""

    by_number = {channel["channel"]: channel for channel in channels}
    if len(by_number) != len(channels):
        raise ValueError("every configured channel must have a unique channel number")

    values: dict[int, float] = {}
    resolving: set[int] = set()

    def resolve(channel_number: int) -> float:
        if channel_number in values:
            return values[channel_number]
        if channel_number in resolving:
            raise ValueError(f"circular channel dependency involving channel {channel_number}")
        try:
            channel = by_number[channel_number]
        except KeyError as exc:
            raise ValueError(f"dependency channel {channel_number} is not configured") from exc

        resolving.add(channel_number)
        dependencies = channel.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"channel {channel_number} depends_on must be a list")

        dependency_value = 0.0
        for dependency in dependencies:
            if isinstance(dependency, int):
                dependency_channel, multiplier = dependency, 1.0
            elif isinstance(dependency, dict):
                dependency_channel = dependency.get("channel")
                multiplier = dependency.get("multiplier", 1)
            else:
                raise ValueError(f"channel {channel_number} has an invalid dependency")
            if not isinstance(dependency_channel, int) or not isinstance(multiplier, (int, float)):
                raise ValueError(f"channel {channel_number} has an invalid dependency channel or multiplier")
            dependency_value += float(multiplier) * resolve(dependency_channel)

        value = value_for_channel(channel, elapsed, machine) + dependency_value
        resolving.remove(channel_number)
        values[channel_number] = value
        return value

    for number in by_number:
        resolve(number)
    return values


def table_identifier(table: str) -> sql.Composed:
    """Return a safely quoted table identifier, supporting ``schema.table``."""

    parts = table.split(".")
    if len(parts) == 1:
        parts.insert(0, "public")
    if len(parts) != 2 or not all(part and part.replace("_", "a").isalnum() for part in parts):
        raise ValueError("database table must be a table name or schema.table")
    return sql.Identifier(*parts)


def ensure_table(connection, table: str) -> None:
    identifier = table_identifier(table)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} (time TIMESTAMPTZ NOT NULL, channel INT NOT NULL, value DOUBLE PRECISION NOT NULL)").format(identifier)
        )
        try:
            cursor.execute(sql.SQL("SELECT create_hypertable({}, 'time', if_not_exists => TRUE)").format(sql.Literal(table)))
        except psycopg2.Error:
            connection.rollback()
        connection.commit()


def run() -> None:
    started = time.monotonic()
    config = load_config()
    loaded_at = time.monotonic()
    connection = None
    try:
        while not STOP.is_set():
            now = time.monotonic()
            if now - loaded_at >= config.get("config_reload_seconds", 5):
                config = load_config()
                loaded_at = now
                LOGGER.info("reloaded config.json")
            if config.get("enabled", True):
                db = config["database"]
                if connection is None or connection.closed:
                    connection = psycopg2.connect(host=db["host"], port=db["port"], dbname=db["name"], user=db["user"], password=db["password"])
                    ensure_table(connection, db["table"])
                timestamp = datetime.now(timezone.utc)
                elapsed = now - started
                channel_values = values_for_channels(
                    config.get("channels", []), elapsed, config.get("machine")
                )
                rows = [(timestamp, number, value) for number, value in channel_values.items()]
                if rows:
                    with connection.cursor() as cursor:
                        psycopg2.extras.execute_values(
                            cursor,
                            sql.SQL("INSERT INTO {} (time, channel, value) VALUES %s").format(table_identifier(db["table"])).as_string(connection),
                            rows,
                        )
                    connection.commit()
                    LOGGER.info("inserted %d samples", len(rows))
            STOP.wait(float(config.get("period_seconds", 1)))
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    run()
