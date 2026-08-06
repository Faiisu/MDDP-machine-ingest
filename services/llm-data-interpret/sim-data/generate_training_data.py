#!/usr/bin/env python3
"""Generate a historical Parquet dataset from the machine simulator."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from simulator import load_config, values_for_channels


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR.parent / "machine_training_samples.parquet"


def generate(duration_seconds: int, sample_period: float) -> pd.DataFrame:
    if duration_seconds <= 0 or sample_period <= 0:
        raise ValueError("duration and sample period must be greater than zero")
    config = load_config()
    channels = config.get("channels", [])
    sample_count = int(duration_seconds / sample_period) + 1
    start = datetime.now(timezone.utc) - timedelta(seconds=duration_seconds)
    rows = []
    for index in range(sample_count):
        elapsed = index * sample_period
        timestamp = start + timedelta(seconds=elapsed)
        values = values_for_channels(channels, elapsed, config.get("machine"))
        rows.extend((timestamp, channel, value) for channel, value in values.items())
    return pd.DataFrame(rows, columns=["time", "channel", "value"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=900)
    parser.add_argument("--sample-period", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    frame = generate(args.duration_seconds, args.sample_period)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    print(f"generated {len(frame):,} rows at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
