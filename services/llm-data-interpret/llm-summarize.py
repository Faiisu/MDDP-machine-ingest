#!/usr/bin/env python3
"""Write one LLM machine-health sentence for a selected database time range.

The worker combines ML artifacts (model, learned relationships, and the
range's latest ML inference) with aggregated telemetry.  It inserts each
result into the configured PostgreSQL ``ai-summarize`` table.  The API key is
read only from the environment variable named in ``ml_config.json``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import psycopg2
from psycopg2 import sql

from machine_ml import aligned_samples, quality_status, read_json, score_rows


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "ml_config.json"
DEFAULT_MODEL = BASE_DIR / "artifacts" / "machine_quality_model.json"
DEFAULT_REPORT = BASE_DIR / "artifacts" / "ml_training_report.json"
LOGGER = logging.getLogger("llm_summarize")
STOP = threading.Event()
IDENTIFIER_PART = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use an ISO-8601 timestamp, for example 2026-08-07T00:00:00Z") from exc
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)


def table_identifier(table: str) -> sql.Composed:
    parts = table.split(".")
    if len(parts) == 1:
        parts.insert(0, "public")
    if len(parts) != 2 or not all(IDENTIFIER_PART.fullmatch(part) for part in parts):
        raise ValueError("table must be a name or schema.name (letters, numbers, _, and - only)")
    return sql.Identifier(*parts)


def connect(database: dict[str, Any]) -> Any:
    return psycopg2.connect(
        host=database["host"], port=database["port"], dbname=database["name"],
        user=database["user"], password=database["password"], connect_timeout=10,
    )


def read_range(connection: Any, table: str, start: datetime, end: datetime) -> pd.DataFrame:
    query = sql.SQL("SELECT time, channel, value FROM {} WHERE time >= %s AND time <= %s ORDER BY time, channel").format(table_identifier(table))
    with connection.cursor() as cursor:
        cursor.execute(query, (start, end))
        rows = cursor.fetchall()
    frame = pd.DataFrame(rows, columns=["time", "channel", "value"])
    if not frame.empty:
        frame["time"] = pd.to_datetime(frame["time"], utc=True)
        frame["channel"] = pd.to_numeric(frame["channel"])
        frame["value"] = pd.to_numeric(frame["value"])
    return frame


def range_statistics(frame: pd.DataFrame, model: dict[str, Any] | None) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    metadata = {int(item["channel"]): item for item in (model or {}).get("features", [])}
    label_channel = (model or {}).get("training_label_channel")
    result: list[dict[str, Any]] = []
    for channel, rows in frame.groupby("channel", sort=True):
        if label_channel is not None and int(channel) == int(label_channel):
            continue
        info = metadata.get(int(channel), {})
        window = max(1, len(rows) // 5)
        start_average = float(rows["value"].iloc[:window].mean())
        end_average = float(rows["value"].iloc[-window:].mean())
        change_percent = 100 * (end_average - start_average) / max(abs(start_average), 1e-9)
        result.append({
            "channel": int(channel), "sensor": info.get("name", f"Channel {int(channel)}"),
            "unit": info.get("unit", ""), "mean": round(float(rows["value"].mean()), 4),
            "minimum": round(float(rows["value"].min()), 4), "maximum": round(float(rows["value"].max()), 4),
            "start_average": round(start_average, 4), "end_average": round(end_average, 4),
            "change_percent": round(change_percent, 2), "samples": int(len(rows)),
        })
    return result


def relationship_observations(frame: pd.DataFrame, model: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Compare learned sensor relationships with behavior inside this range."""

    if frame.empty or not model:
        return []
    wide = frame.pivot_table(index="time", columns="channel", values="value", aggfunc="mean")
    observations: list[dict[str, Any]] = []
    learned_relationships = sorted(
        model.get("relationships", []),
        key=lambda item: (
            {item.get("sensor_a"), item.get("sensor_b")} != {"Machine load", "Motor speed"},
            -abs(float(item.get("pearson_r", 0))),
        ),
    )
    for learned in learned_relationships:
        channel_a, channel_b = int(learned["channel_a"]), int(learned["channel_b"])
        if channel_a not in wide.columns or channel_b not in wide.columns:
            continue
        paired = wide[[channel_a, channel_b]].dropna()
        if len(paired) < 3 or paired[channel_a].nunique() < 2 or paired[channel_b].nunique() < 2:
            continue
        actual = float(paired[channel_a].corr(paired[channel_b]))
        expected = float(learned["pearson_r"])
        follows_expected = (actual >= 0) == (expected >= 0) and abs(actual) >= 0.30
        observations.append({
            "sensor_a": learned["sensor_a"], "sensor_b": learned["sensor_b"],
            "expected_behavior": "move together" if expected >= 0 else "move in opposite directions",
            "actual_correlation": round(actual, 3),
            "relationship_followed": follows_expected,
            "plain_observation": (
                f"{learned['sensor_a']} and {learned['sensor_b']} followed their usual pattern"
                if follows_expected else
                f"{learned['sensor_a']} and {learned['sensor_b']} did not follow their usual pattern"
            ),
        })
        if len(observations) >= 6:
            break
    return observations


def possible_inspection_points(ml: dict[str, Any], relationships: list[dict[str, Any]]) -> list[str]:
    """Provide cautious, operator-readable possibilities grounded in detected signals."""

    contributors = {item.get("signal") for item in ml.get("top_contributors", [])}
    checks: list[str] = []
    if contributors & {"vibration_mm_s", "displacement_mm", "acoustic_db"}:
        checks.append("Unusual vibration, movement, or noise may indicate looseness, imbalance, coupling trouble, or bearing wear; inspect these parts.")
    if contributors & {"bearing_temperature_c"}:
        checks.append("High bearing temperature may indicate friction, poor lubrication, or insufficient cooling; inspect before continued operation.")
    if contributors & {"motor_current_a"}:
        checks.append("Unusual motor current may indicate excess mechanical load or an electrical supply or motor issue; inspect the drive system.")
    load_speed_mismatch = any(
        not item["relationship_followed"]
        and {item["sensor_a"], item["sensor_b"]} == {"Machine load", "Motor speed"}
        for item in relationships
    )
    if load_speed_mismatch:
        checks.append("Load and motor speed are not responding together as usual; the motor, power supply, belt, or coupling may need inspection.")
    return checks[:3]


def abnormal_periods(
    frame: pd.DataFrame, model: dict[str, Any] | None, timezone_name: str
) -> list[dict[str, Any]]:
    """Group consecutive non-healthy ML decisions into their actual time ranges."""

    if frame.empty or not model:
        return []
    local_timezone = ZoneInfo(timezone_name)
    channels = [int(feature["channel"]) for feature in model["features"]]
    samples = aligned_samples(frame, channels)
    if samples.empty:
        return []
    scores, standardized = score_rows(samples, model)
    statuses = [quality_status(float(score), model) for score in scores]
    timestamps = list(samples.index)
    gaps = pd.Series(timestamps).diff().dropna().dt.total_seconds()
    expected_gap = float(gaps.median()) if not gaps.empty else 1.0
    maximum_contiguous_gap = max(5.0, expected_gap * 2.5)
    severity = {"healthy": 0, "warning": 1, "critical": 2}
    means = [float(value) for value in model["normalization"]["mean"]]
    periods: list[dict[str, Any]] = []

    def append_period(start_index: int, end_index: int) -> None:
        segment_statuses = statuses[start_index : end_index + 1]
        worst_status = max(segment_statuses, key=severity.get)
        segment_z = standardized[start_index : end_index + 1]
        sensor_strength = abs(segment_z).max(axis=0)
        strongest_indices = sensor_strength.argsort()[::-1][:3]
        abnormal_sensors = []
        for feature_index in strongest_indices:
            feature = model["features"][int(feature_index)]
            local_peak = int(abs(segment_z[:, feature_index]).argmax())
            row_index = start_index + local_peak
            measured = float(samples.iloc[row_index, int(feature_index)])
            usual = means[int(feature_index)]
            direction = "above" if measured > usual else "below"
            unit = feature.get("unit", "")
            abnormal_sensors.append({
                "sensor": feature["name"], "signal": feature.get("signal"),
                "measured_value": round(measured, 3), "unit": unit,
                "usual_value": round(usual, 3), "direction": direction,
                "plain_description": (
                    f"{feature['name']} reached {measured:.2f} {unit}, {direction} "
                    f"its usual level of about {usual:.2f} {unit}"
                ).replace("  ", " ").strip(),
            })
        start_text = timestamps[start_index].astimezone(local_timezone).strftime("%Y-%m-%d %H:%M:%S")
        end_text = timestamps[end_index].astimezone(local_timezone).strftime("%Y-%m-%d %H:%M:%S")
        periods.append({
            "status": worst_status,
            "start": start_text,
            "end": end_text,
            "timezone": timezone_name,
            "required_range_text": f"from {start_text} to {end_text} ({timezone_name})",
            "abnormal_sensors": abnormal_sensors,
        })

    period_start: int | None = None
    for index, status in enumerate(statuses):
        gap_break = index > 0 and (timestamps[index] - timestamps[index - 1]).total_seconds() > maximum_contiguous_gap
        if period_start is not None and (status == "healthy" or gap_break):
            append_period(period_start, index - 1)
            period_start = None
        if status != "healthy" and period_start is None:
            period_start = index
    if period_start is not None:
        append_period(period_start, len(statuses) - 1)
    return periods


def ml_context(frame: pd.DataFrame, model: dict[str, Any] | None, report: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "training_summary": (report or {}).get("summary"),
        "strongest_relationships": (report or {}).get("strongest_relationships", [])[:4],
    }


def one_sentence(value: str | None) -> str:
    if not isinstance(value, str):
        raise ValueError("LLM returned no final text")
    sentence = " ".join(value.strip().strip('"').split())
    if not sentence:
        raise ValueError("LLM returned an empty summary")
    # The prompt requests one sentence; retain only the first line if a provider adds formatting.
    return sentence.split("\n", 1)[0]


def display_time_range(start: datetime, end: datetime, timezone_name: str) -> dict[str, str]:
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown summarization timezone: {timezone_name}") from exc
    start_text = start.astimezone(local_timezone).strftime("%Y-%m-%d %H:%M:%S")
    end_text = end.astimezone(local_timezone).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": timezone_name,
        "analysis_window": f"{start_text} to {end_text}",
    }


def ensure_required_summary_details(summary: str, payload: dict[str, Any]) -> str:
    """Guarantee abnormal periods are named without treating the query window as abnormal."""

    result = one_sentence(summary)
    periods = payload["ml"].get("abnormal_periods", [])
    if not periods:
        return "The machine operated normally and no abnormal behavior was found."
    lowered = result.casefold()
    if "no abnormal" in lowered or "operated normally" in lowered or "working correctly" in lowered:
        result = "The machine showed abnormal behavior that should be inspected"
    missing_periods = [period for period in periods if period["required_range_text"].casefold() not in result.casefold()]
    if missing_periods:
        details = []
        for period in missing_periods:
            sensors = ", ".join(item["plain_description"] for item in period["abnormal_sensors"])
            details.append(f"abnormal behavior occurred {period['required_range_text']}, involving {sensors}")
        result = f"{result.rstrip('.;')}; {'; '.join(details)}."
    return result


def ask_llm(payload: dict[str, Any], settings: dict[str, Any]) -> str:
    api_key_env = settings.get("api_key_env", "OPENAI_API_KEY")
    if not isinstance(api_key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise ValueError(
            "llm.api_key_env must be an environment-variable name such as OPENAI_API_KEY; "
            "do not store an API key in ml_config.json"
        )
    api_key = os.getenv(api_key_env)
    if not api_key:
        raise ValueError(f"set the {api_key_env} environment variable before running the summary worker")
    model = settings.get("model", "").strip()
    if not model:
        raise ValueError("set llm.model in ml_config.json before running the summary worker")
    prompt = (
        "Write exactly one clear sentence for a factory operator with no technical or ML knowledge. "
        "The time_range is only the data-analysis window and must not be described as an abnormal period. "
        "ml.overall_result and ml.abnormal_periods are authoritative for the whole analysis window; do not infer overall health from the last reading. "
        "If ml.overall_result is healthy, simply say the machine operated normally and no abnormal behavior was found. "
        "If ml.overall_result is abnormal, never call the machine normal: state each abnormal_period.required_range_text exactly, name its abnormal sensors with measured and usual values, "
        "explain an important sensor relationship that is not behaving normally when supplied, and give one cautious possible issue and practical inspection action. "
        "Prefer wording such as 'may mean' or 'could indicate'; never say a component is definitely damaged. "
        "Do not mention correlation, sigma, anomaly score, PCA, channels, JSON, causation, diagnosis, or safety approval. "
        "Do not add headings, bullets, or quotes.\n\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    request_payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You summarize machine telemetry conservatively."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": int(settings.get("max_tokens", 400)),
    }
    if settings.get("enable_thinking", False) is False:
        request_payload["chat_template_kwargs"] = {"enable_thinking": False}
    request_body = json.dumps(request_payload).encode("utf-8")
    # Some OpenAI-compatible gateways sit behind Cloudflare and reject
    # urllib's default ``Python-urllib/x.y`` browser signature (error 1010).
    # Send ordinary API-client headers and allow the User-Agent to be adjusted
    # for gateways with an explicit allow-list.
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": settings.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36",
        ),
    }
    request = urllib.request.Request(
        settings.get("api_url", "https://api.openai.com/v1/chat/completions"),
        data=request_body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(settings.get("timeout_seconds", 30))) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
    try:
        choice = response_payload["choices"][0]
        return ensure_required_summary_details(choice["message"].get("content"), payload)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        choice = response_payload.get("choices", [{}])[0]
        finish_reason = choice.get("finish_reason")
        has_reasoning = bool(choice.get("message", {}).get("reasoning_content"))
        if has_reasoning:
            raise RuntimeError(
                f"LLM returned reasoning but no final sentence (finish_reason={finish_reason}); "
                "keep llm.enable_thinking=false or increase llm.max_tokens"
            ) from exc
        raise RuntimeError("LLM response did not contain choices[0].message.content") from exc


def dry_run_summary(payload: dict[str, Any]) -> str:
    periods = payload["ml"].get("abnormal_periods", [])
    summary = (
        "The machine operated normally and no abnormal behavior was found."
        if not periods else
        "The machine had abnormal behavior that may require inspection."
    )
    return ensure_required_summary_details(summary, payload)


def ensure_output_table(connection: Any, table: str) -> None:
    query = sql.SQL(
        'CREATE TABLE IF NOT EXISTS {} ('
        'time TIMESTAMPTZ NOT NULL, "time-start" TIMESTAMPTZ NOT NULL, '
        '"time-end" TIMESTAMPTZ NOT NULL, summarize TEXT NOT NULL)'
    ).format(table_identifier(table))
    with connection.cursor() as cursor:
        cursor.execute(query)
    connection.commit()


def insert_summary(connection: Any, table: str, start: datetime, end: datetime, summary: str) -> None:
    query = sql.SQL('INSERT INTO {} (time, "time-start", "time-end", summarize) VALUES (%s, %s, %s, %s)').format(table_identifier(table))
    with connection.cursor() as cursor:
        cursor.execute(query, (datetime.now(timezone.utc), start, end, summary))
    connection.commit()


def load_artifact(path: Path) -> dict[str, Any] | None:
    return read_json(path) if path.exists() else None


def resolve_range(args: argparse.Namespace, settings: dict[str, Any]) -> tuple[datetime, datetime]:
    end = args.time_end or datetime.now(timezone.utc)
    start = args.time_start or end - timedelta(seconds=float(settings.get("range_seconds", 300)))
    if start >= end:
        raise ValueError("time-start must be before time-end")
    return start, end


def summarize_once(args: argparse.Namespace) -> None:
    configuration = read_json(args.config)
    summary_settings = configuration.get("summarization", {})
    if not summary_settings.get("enabled", True):
        LOGGER.info("summary worker is disabled in %s", args.config)
        return
    database = configuration.get("database_source")
    if not isinstance(database, dict):
        raise ValueError("ml_config.json must contain database_source")
    start, end = resolve_range(args, summary_settings)
    model = load_artifact(args.model)
    report = load_artifact(args.report)
    with connect(database) as connection:
        frame = read_range(connection, database["table"], start, end)
        timezone_name = summary_settings.get("timezone", "Asia/Bangkok")
        ml = ml_context(frame, model, report)
        ml["abnormal_periods"] = abnormal_periods(frame, model, timezone_name)
        ml["overall_result"] = "abnormal" if ml["abnormal_periods"] else "healthy"
        relationships = relationship_observations(frame, model)
        period_sensors = [
            sensor
            for period in ml["abnormal_periods"]
            for sensor in period["abnormal_sensors"]
        ]
        payload = {
            "time_range": display_time_range(start, end, timezone_name),
            "telemetry": {"source_table": database["table"], "row_count": int(len(frame)), "sensor_statistics": range_statistics(frame, model)},
            "ml": ml,
            "operator_evidence": {
                "sensor_relationships": relationships,
                "possible_inspection_points": possible_inspection_points(
                    {"top_contributors": period_sensors}, relationships
                ),
            },
        }
        summary = dry_run_summary(payload) if args.dry_run else ask_llm(payload, configuration.get("llm", {}))
        output_table = summary_settings.get("output_table", "public.ai-summarize")
        ensure_output_table(connection, output_table)
        insert_summary(connection, output_table, start, end, summary)
    LOGGER.info("saved summary for %s to %s", end.isoformat(), output_table)
    print(summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--time-start", type=parse_timestamp, help="inclusive ISO-8601 start time")
    parser.add_argument("--time-end", type=parse_timestamp, help="inclusive ISO-8601 end time; defaults to now")
    parser.add_argument("--once", action="store_true", help="write one summary then exit")
    parser.add_argument("--dry-run", action="store_true", help="write a deterministic test sentence without calling an LLM")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, lambda *_: STOP.set())
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
    args = build_parser().parse_args()
    if args.once:
        summarize_once(args)
        return 0
    while not STOP.is_set():
        try:
            summarize_once(args)
        except Exception as exc:
            LOGGER.exception("could not create summary: %s", exc)
        configuration = read_json(args.config)
        interval = max(float(configuration.get("summarization", {}).get("interval_seconds", 60)), 1.0)
        STOP.wait(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
