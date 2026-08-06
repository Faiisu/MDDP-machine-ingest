#!/usr/bin/env python3
"""Train and run an explainable machine-quality model on DAQ telemetry.

The persisted model is JSON rather than pickle so it can be audited, consumed
by another service, and safely included in an LLM prompt. Training is
unsupervised: known-good rows establish a multivariate baseline, while PCA and
a regularized Mahalanobis distance capture relationships between sensors.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "daq_samples.parquet"
DEFAULT_TRAINING_INPUT = BASE_DIR / "machine_training_samples.parquet"
DEFAULT_CONFIG = BASE_DIR / "sim-data" / "config.json"
DEFAULT_ARTIFACT_DIR = BASE_DIR / "artifacts"
DEFAULT_MODEL = DEFAULT_ARTIFACT_DIR / "machine_quality_model.json"
DEFAULT_REPORT = DEFAULT_ARTIFACT_DIR / "ml_training_report.json"
DEFAULT_LATEST = DEFAULT_ARTIFACT_DIR / "latest_machine_quality.json"
MODEL_SCHEMA = "machine-quality-model/v1"
QUALITY_SCHEMA = "machine-quality-inference/v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically so real-time readers never observe a partial file."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as output:
            json.dump(payload, output, indent=2, allow_nan=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_samples(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {"time", "channel", "value"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    frame = frame.loc[:, ["time", "channel", "value"]].copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame["channel"] = pd.to_numeric(frame["channel"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame.dropna().sort_values(["time", "channel"])


def channel_metadata(config: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    features: list[dict[str, Any]] = []
    label_channel: int | None = None
    for channel in config.get("channels", []):
        number = int(channel["channel"])
        if channel.get("training_label") or channel.get("signal") == "health_state":
            label_channel = number
            continue
        if channel.get("type") == "machine":
            features.append(
                {
                    "channel": number,
                    "name": channel.get("name", channel.get("signal", f"Channel {number}")),
                    "signal": channel.get("signal", "unknown"),
                    "unit": channel.get("unit", ""),
                }
            )
    return features, label_channel


def aligned_samples(frame: pd.DataFrame, feature_channels: list[int]) -> pd.DataFrame:
    wide = frame.pivot_table(index="time", columns="channel", values="value", aggfunc="mean")
    missing = sorted(set(feature_channels) - set(wide.columns))
    if missing:
        raise ValueError(f"input has no samples for required channels: {missing}")
    return wide.loc[:, feature_channels].sort_index().dropna()


def relationship_strength(coefficient: float) -> str:
    absolute = abs(coefficient)
    if absolute >= 0.90:
        return "very_strong"
    if absolute >= 0.70:
        return "strong"
    if absolute >= 0.50:
        return "moderate"
    if absolute >= 0.30:
        return "weak"
    return "very_weak"


def find_relationships(samples: pd.DataFrame, features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    correlation = samples.corr(method="pearson")
    names = {item["channel"]: item["name"] for item in features}
    relationships: list[dict[str, Any]] = []
    for first_index, first in enumerate(samples.columns):
        for second in samples.columns[first_index + 1 :]:
            coefficient = float(correlation.loc[first, second])
            relationships.append(
                {
                    "channel_a": int(first),
                    "sensor_a": names[int(first)],
                    "channel_b": int(second),
                    "sensor_b": names[int(second)],
                    "pearson_r": round(coefficient, 6),
                    "direction": "same" if coefficient >= 0 else "inverse",
                    "strength": relationship_strength(coefficient),
                }
            )
    return sorted(relationships, key=lambda item: abs(item["pearson_r"]), reverse=True)


def _normal_training_rows(
    frame: pd.DataFrame, samples: pd.DataFrame, label_channel: int | None
) -> tuple[pd.DataFrame, str]:
    if label_channel is None:
        return samples, "all_rows_assumed_healthy"
    labels = (
        frame[frame["channel"] == label_channel]
        .drop_duplicates("time", keep="last")
        .set_index("time")["value"]
    )
    normal_times = labels[labels == 0].index
    normal = samples.loc[samples.index.intersection(normal_times)]
    if len(normal) < max(10, samples.shape[1] + 2):
        raise ValueError("not enough simulator healthy rows to train the model")
    return normal, f"channel_{label_channel}_equals_0"


def train_model(frame: pd.DataFrame, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    features, label_channel = channel_metadata(config)
    if len(features) < 2:
        raise ValueError("at least two machine feature channels are required")
    channels = [item["channel"] for item in features]
    samples = aligned_samples(frame, channels)
    if len(samples) < max(15, len(channels) + 3):
        raise ValueError("not enough aligned samples to train the model")
    normal, baseline_rule = _normal_training_rows(frame, samples, label_channel)

    mean = normal.mean()
    standard_deviation = normal.std(ddof=0).replace(0, 1.0)
    standardized = (normal - mean) / standard_deviation
    covariance = np.cov(standardized.to_numpy(), rowvar=False)
    regularization = 0.05
    regularized_covariance = covariance + np.eye(len(channels)) * regularization
    inverse_covariance = np.linalg.pinv(regularized_covariance)
    scores = np.sqrt(
        np.maximum(
            np.einsum("ij,jk,ik->i", standardized, inverse_covariance, standardized), 0
        )
    )
    warning_threshold = max(float(np.quantile(scores, 0.975)), math.sqrt(len(channels)) * 1.15)
    critical_threshold = max(float(np.quantile(scores, 0.997)), warning_threshold * 1.45)
    threshold_source = "healthy_baseline_quantiles"
    simulator_validation = None
    if label_channel is not None:
        labels = (
            frame[frame["channel"] == label_channel]
            .drop_duplicates("time", keep="last")
            .set_index("time")["value"]
            .reindex(samples.index)
        )
        all_standardized = (samples - mean) / standard_deviation
        all_scores = np.sqrt(
            np.maximum(
                np.einsum("ij,jk,ik->i", all_standardized, inverse_covariance, all_standardized),
                0,
            )
        )
        warning_scores = all_scores[labels.to_numpy() == 1]
        critical_scores = all_scores[labels.to_numpy() == 2]
        if len(warning_scores) >= 10 and len(critical_scores) >= 10:
            healthy_edge = float(np.quantile(scores, 0.99))
            warning_edge = float(np.quantile(warning_scores, 0.01))
            warning_threshold = (healthy_edge + warning_edge) / 2
            late_warning = float(np.quantile(warning_scores, 0.90))
            early_critical = float(np.quantile(critical_scores, 0.10))
            critical_threshold = max((late_warning + early_critical) / 2, warning_threshold * 1.45)
            threshold_source = f"simulator_ground_truth_channel_{label_channel}"
            predicted = np.where(
                all_scores >= critical_threshold,
                2,
                np.where(all_scores >= warning_threshold, 1, 0),
            )
            truth = labels.to_numpy(dtype=int)
            class_names = {0: "healthy", 1: "warning", 2: "critical"}
            confusion = {
                class_names[actual]: {
                    class_names[guess]: int(np.sum((truth == actual) & (predicted == guess)))
                    for guess in class_names
                }
                for actual in class_names
            }
            simulator_validation = {
                "method": "in_sample_simulator_check",
                "accuracy": float(np.mean(predicted == truth)),
                "confusion_matrix": confusion,
                "note": "This checks pipeline behavior on simulation, not expected real-machine accuracy.",
            }

    _, singular_values, components = np.linalg.svd(standardized, full_matrices=False)
    explained_variance = singular_values**2 / max(len(standardized) - 1, 1)
    explained_ratio = explained_variance / explained_variance.sum()
    cumulative = np.cumsum(explained_ratio)
    retained = min(int(np.searchsorted(cumulative, 0.95) + 1), len(channels))
    relationships = find_relationships(samples, features)

    model = {
        "schema": MODEL_SCHEMA,
        "created_at": utc_now(),
        "model_type": "regularized_mahalanobis_with_pca_explanation",
        "purpose": "Detect multivariate deviation from known-good machine operation",
        "features": features,
        "training_label_channel": label_channel,
        "baseline_rule": baseline_rule,
        "normalization": {
            "mean": [float(mean[channel]) for channel in channels],
            "standard_deviation": [float(standard_deviation[channel]) for channel in channels],
        },
        "inverse_covariance": inverse_covariance.tolist(),
        "thresholds": {
            "warning": warning_threshold,
            "critical": critical_threshold,
            "source": threshold_source,
        },
        "pca": {
            "retained_components": retained,
            "explained_variance_ratio": explained_ratio.tolist(),
            "components": components[:retained].tolist(),
        },
        "relationships": relationships,
        "training": {
            "input_rows": int(len(frame)),
            "aligned_rows": int(len(samples)),
            "healthy_baseline_rows": int(len(normal)),
            "time_start": samples.index.min().isoformat(),
            "time_end": samples.index.max().isoformat(),
        },
    }
    strongest = relationships[: min(8, len(relationships))]
    report = {
        "schema": "machine-quality-training-report/v1",
        "created_at": model["created_at"],
        "model_file": DEFAULT_MODEL.name,
        "result": "trained",
        "summary": (
            f"Learned a healthy baseline from {len(normal)} aligned samples across "
            f"{len(features)} sensors. The first {retained} PCA components explain "
            f"{cumulative[retained - 1]:.1%} of healthy variation."
        ),
        "thresholds": model["thresholds"],
        "simulator_validation": simulator_validation,
        "strongest_relationships": strongest,
        "llm_guidance": [
            "Relationships describe association, not causation.",
            "Treat warning or critical inference as an inspection trigger, not a diagnosis.",
            "Review the largest sensor deviations and the learned relationships together.",
            "Retrain on verified healthy real-machine data before production decisions.",
        ],
    }
    return model, report


def score_rows(samples: pd.DataFrame, model: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    channels = [int(item["channel"]) for item in model["features"]]
    ordered = samples.loc[:, channels].to_numpy(dtype=float)
    mean = np.asarray(model["normalization"]["mean"], dtype=float)
    std = np.asarray(model["normalization"]["standard_deviation"], dtype=float)
    standardized = (ordered - mean) / std
    inverse_covariance = np.asarray(model["inverse_covariance"], dtype=float)
    score_squared = np.einsum("ij,jk,ik->i", standardized, inverse_covariance, standardized)
    return np.sqrt(np.maximum(score_squared, 0)), standardized


def quality_status(score: float, model: dict[str, Any]) -> str:
    thresholds = model["thresholds"]
    if score >= float(thresholds["critical"]):
        return "critical"
    if score >= float(thresholds["warning"]):
        return "warning"
    return "healthy"


def infer_latest(frame: pd.DataFrame, model: dict[str, Any]) -> dict[str, Any]:
    if model.get("schema") != MODEL_SCHEMA:
        raise ValueError(f"unsupported model schema: {model.get('schema')}")
    channels = [int(item["channel"]) for item in model["features"]]
    samples = aligned_samples(frame, channels)
    if samples.empty:
        raise ValueError("no complete timestamp is available for inference")
    scores, standardized = score_rows(samples, model)
    latest = samples.iloc[-1]
    score = float(scores[-1])
    status = quality_status(score, model)
    critical = float(model["thresholds"]["critical"])
    warning = float(model["thresholds"]["warning"])
    if score <= warning:
        health_percent = 100 - 20 * score / warning
    elif score <= critical:
        health_percent = 80 - 40 * (score - warning) / (critical - warning)
    else:
        health_percent = max(0.0, 40 - 40 * (score - critical) / critical)
    deviations = []
    for index, feature in enumerate(model["features"]):
        channel = int(feature["channel"])
        deviations.append(
            {
                **feature,
                "value": float(latest[channel]),
                "deviation_sigma": float(standardized[-1, index]),
            }
        )
    deviations.sort(key=lambda item: abs(item["deviation_sigma"]), reverse=True)
    alerts = []
    if status != "healthy":
        alerts.append(
            f"Machine state is {status}; inspect {deviations[0]['name']} and related sensors."
        )
    label_channel = model.get("training_label_channel")
    ground_truth = None
    if label_channel is not None:
        label_rows = frame[(frame["channel"] == label_channel) & (frame["time"] == samples.index[-1])]
        if not label_rows.empty:
            ground_truth = {0: "healthy", 1: "warning", 2: "critical"}.get(
                int(label_rows.iloc[-1]["value"]), "unknown"
            )
    return {
        "schema": QUALITY_SCHEMA,
        "generated_at": utc_now(),
        "sample_time": samples.index[-1].isoformat(),
        "machine_quality": {
            "status": status,
            "health_percent": round(health_percent, 2),
            "anomaly_score": round(score, 6),
            "warning_threshold": warning,
            "critical_threshold": critical,
        },
        "top_contributors": deviations[:3],
        "sensor_readings": deviations,
        "alerts": alerts,
        "simulator_ground_truth": ground_truth,
        "learned_relationships": model.get("relationships", [])[:8],
        "llm_context": {
            "instruction": "Explain machine quality from the ML result and live sensor readings. Do not claim causation or invent a fault component.",
            "summary": f"ML status={status}, health={health_percent:.1f}%, anomaly_score={score:.2f}.",
        },
        "model": {"schema": model["schema"], "created_at": model["created_at"]},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    train = subparsers.add_parser("train", help="train and persist a model and LLM-readable report")
    train.add_argument("--input", type=Path, default=DEFAULT_TRAINING_INPUT)
    train.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    train.add_argument("--model-output", type=Path, default=DEFAULT_MODEL)
    train.add_argument("--report-output", type=Path, default=DEFAULT_REPORT)
    infer = subparsers.add_parser("infer", help="score the latest complete row in a Parquet file")
    infer.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    infer.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    infer.add_argument("--output", type=Path, default=DEFAULT_LATEST)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "train":
        model, report = train_model(read_samples(args.input), read_json(args.config))
        atomic_write_json(args.model_output, model)
        report["model_file"] = str(args.model_output.resolve())
        atomic_write_json(args.report_output, report)
        print(f"model: {args.model_output}")
        print(f"report: {args.report_output}")
        return 0
    model = read_json(args.model)
    result = infer_latest(read_samples(args.input), model)
    atomic_write_json(args.output, result)
    print(f"quality: {args.output} ({result['machine_quality']['status']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
