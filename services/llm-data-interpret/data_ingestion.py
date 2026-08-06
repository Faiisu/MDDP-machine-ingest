#!/usr/bin/env python3
"""Export DAQ samples from TimescaleDB to a Parquet file.

The exporter reads ``public.daq_samples`` in batches, so it does not load the
whole hypertable into memory. Parquet files are kept inside this service
directory.

Examples:

    # Uses the defaults in this module and PostgreSQL credential environment
    # variables (PGUSER/PGPASSWORD or DB_USER/DB_PASSWORD).
    python services/llm-data-interpret/data_preprocessing.py

    # Export a bounded UTC time range.
    python services/llm-data-interpret/data_preprocessing.py --start 2026-08-01T00:00:00Z --end 2026-08-02T00:00:00Z --output data/daq_samples.parquet

Alternatively, set ``TIMESCALEDB_DSN`` (or ``DB_DSN``) to a PostgreSQL DSN.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence


DEFAULT_HOST = "100.112.210.64"
DEFAULT_PORT = 5432
DEFAULT_DATABASE = "postgres"
DEFAULT_SCHEMA = "public"
DEFAULT_TABLE = "mockup"
SERVICE_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_OUTPUT = SERVICE_DIRECTORY / "daq_samples.parquet"
DEFAULT_FETCH_SIZE = 10000
DEFAULT_CONNECT_TIMEOUT = 10

LOGGER = logging.getLogger("data_preprocessing")
RELATIVE_TIMESTAMP_PATTERN = re.compile(r"^-(?P<amount>[0-9]+)(?P<unit>[smhd])$", re.IGNORECASE)


class ExportStats(NamedTuple):
    """Summary returned after a successful export."""

    rows: int
    output: Path


def _environment_value(*names: str) -> str | None:
    """Return the first non-empty environment variable in *names*."""

    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 or relative timestamp and normalize it to UTC.

    Naive timestamps are treated as UTC, which keeps CLI usage predictable for
    a database column declared as ``TIMESTAMPTZ``.

    Relative values use the form ``-<amount><unit>`` and are measured back
    from the current UTC time. Supported units are seconds (``s``), minutes
    (``m``), hours (``h``), and days (``d``); for example, ``-10m``.
    """

    if value is None:
        return None

    normalized = value.strip()
    relative_match = RELATIVE_TIMESTAMP_PATTERN.fullmatch(normalized)
    if relative_match:
        amount = int(relative_match.group("amount"))
        unit = relative_match.group("unit").lower()
        seconds_per_unit = {"s": 1, "m": 60, "h": 3600, "d": 86400}
        return datetime.now(timezone.utc) - timedelta(
            seconds=amount * seconds_per_unit[unit]
        )

    if normalized.endswith(("Z", "z")):
        normalized = normalized[:-1] + "+00:00"

    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid timestamp {value!r}; use ISO-8601 or a relative value such as -10m"
        ) from exc

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _normalize_timestamp(value: datetime) -> datetime:
    """Return a database timestamp as a timezone-aware UTC datetime."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _positive_int(value: str) -> int:
    """argparse converter for positive integer options."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _normalize_relative_timestamp_args(argv: Iterable[str]) -> list[str]:
    """Make argparse accept values such as ``--start -10m``."""

    normalized: list[str] = []
    arguments = list(argv)
    timestamp_options = {"--start", "--end"}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if (
            argument in timestamp_options
            and index + 1 < len(arguments)
            and RELATIVE_TIMESTAMP_PATTERN.fullmatch(arguments[index + 1])
        ):
            normalized.append(f"{argument}={arguments[index + 1]}")
            index += 2
            continue
        normalized.append(argument)
        index += 1
    return normalized


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    env_host = _environment_value("TIMESCALEDB_HOST", "DB_HOST") or DEFAULT_HOST
    env_port = _environment_value("TIMESCALEDB_PORT", "DB_PORT")
    env_database = _environment_value("TIMESCALEDB_DATABASE", "DB_NAME") or DEFAULT_DATABASE
    env_schema = _environment_value("TIMESCALEDB_SCHEMA", "DB_SCHEMA") or DEFAULT_SCHEMA
    env_table = _environment_value("TIMESCALEDB_TABLE", "DB_TABLE") or DEFAULT_TABLE
    env_user = "admin"
    env_password = "admin"
    env_dsn = _environment_value("TIMESCALEDB_DSN", "DB_DSN")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=env_host, help=f"database host (default: {env_host})")
    parser.add_argument(
        "--port",
        type=_positive_int,
        default=int(env_port) if env_port else DEFAULT_PORT,
        help=f"database port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--database",
        "--dbname",
        dest="database",
        default=env_database,
        help=f"database name (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument("--schema", default=env_schema, help=f"table schema (default: {DEFAULT_SCHEMA})")
    parser.add_argument("--table", default=env_table, help=f"table name (default: {DEFAULT_TABLE})")
    parser.add_argument("--user", default=env_user, help="database user")
    parser.add_argument(
        "--password",
        default=env_password,
        help="database password; prefer TIMESCALEDB_PASSWORD/PGPASSWORD",
    )
    parser.add_argument(
        "--dsn",
        default=env_dsn,
        help="PostgreSQL DSN; overrides host, port, database, user, and password",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Parquet output path within this service directory (default: daq_samples.parquet)",
    )
    parser.add_argument(
        "--start",
        type=parse_timestamp,
        help="include rows at or after this ISO-8601 timestamp or relative value such as -10m",
    )
    parser.add_argument(
        "--end",
        type=parse_timestamp,
        help="include rows at or before this ISO-8601 timestamp or relative value such as -5m",
    )
    parser.add_argument(
        "--fetch-size",
        type=_positive_int,
        default=DEFAULT_FETCH_SIZE,
        help=f"rows fetched per database batch (default: {DEFAULT_FETCH_SIZE})",
    )
    parser.add_argument(
        "--connect-timeout",
        type=_positive_int,
        default=DEFAULT_CONNECT_TIMEOUT,
        help=f"database connection timeout in seconds (default: {DEFAULT_CONNECT_TIMEOUT})",
    )
    parser.add_argument(
        "--compression",
        choices=("snappy", "gzip", "brotli", "zstd", "lz4", "none"),
        default="snappy",
        help="Parquet compression codec (default: snappy)",
    )
    return parser


def _connection_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """Build psycopg2 connection arguments from parsed options."""

    if args.dsn:
        return {"dsn": args.dsn, "connect_timeout": args.connect_timeout}

    kwargs: dict[str, Any] = {
        "host": args.host,
        "port": args.port,
        "dbname": args.database,
        "connect_timeout": args.connect_timeout,
    }
    if args.user:
        kwargs["user"] = args.user
    if args.password:
        kwargs["password"] = args.password
    return kwargs


def _resolve_output_path(output_path: Path) -> Path:
    """Resolve an output path and keep it within this service directory."""

    candidate = output_path if output_path.is_absolute() else SERVICE_DIRECTORY / output_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(SERVICE_DIRECTORY)
    except ValueError as exc:
        raise ValueError(
            f"--output must be inside the service directory: {SERVICE_DIRECTORY}"
        ) from exc
    return resolved


def _select_query(schema: str, table: str, start: datetime | None, end: datetime | None) -> tuple[Any, list[Any]]:
    """Build a parameterized query with safely quoted identifiers."""

    from psycopg2 import sql

    conditions: list[Any] = []
    parameters: list[Any] = []
    if start is not None:
        conditions.append(sql.SQL("{} >= %s").format(sql.Identifier("time")))
        parameters.append(start)
    if end is not None:
        conditions.append(sql.SQL("{} <= %s").format(sql.Identifier("time")))
        parameters.append(end)

    query = sql.SQL("SELECT {time}, {channel}, {value} FROM {table}").format(
        time=sql.Identifier("time"),
        channel=sql.Identifier("channel"),
        value=sql.Identifier("value"),
        table=sql.Identifier(schema, table),
    )
    if conditions:
        query += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)
    query += sql.SQL(" ORDER BY {time} ASC, {channel} ASC").format(
        time=sql.Identifier("time"),
        channel=sql.Identifier("channel"),
    )
    return query, parameters


def _rows_to_arrow(rows: Sequence[Sequence[Any]], schema: Any) -> Any:
    """Convert one database batch to an Arrow table with a stable schema."""

    import pyarrow as pa

    timestamps = [_normalize_timestamp(row[0]) for row in rows]
    channels = [row[1] for row in rows]
    values = [row[2] for row in rows]
    return pa.Table.from_arrays(
        [
            pa.array(timestamps, type=pa.timestamp("us", tz="UTC")),
            pa.array(channels, type=pa.int64()),
            pa.array(values, type=pa.float64()),
        ],
        schema=schema,
    )


def export_samples(args: argparse.Namespace) -> ExportStats:
    """Read samples from TimescaleDB and atomically write a Parquet file."""

    if args.start is not None and args.end is not None and args.start > args.end:
        raise ValueError("--start must be earlier than or equal to --end")

    try:
        import psycopg2
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "This exporter requires psycopg2-binary and pyarrow. "
            "Install the project dependencies first."
        ) from exc

    output = _resolve_output_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    compression = None if args.compression == "none" else args.compression
    arrow_schema = pa.schema(
        [
            pa.field("time", pa.timestamp("us", tz="UTC")),
            pa.field("channel", pa.int64()),
            pa.field("value", pa.float64()),
        ]
    )

    query, parameters = _select_query(args.schema, args.table, args.start, args.end)
    temporary_path: Path | None = None
    writer: Any = None
    row_count = 0

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{output.stem}.",
            suffix=".tmp.parquet",
            dir=output.parent,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        writer = pq.ParquetWriter(str(temporary_path), arrow_schema, compression=compression)
        connection_options = _connection_kwargs(args)
        connection = psycopg2.connect(**connection_options)

        try:
            with connection:
                with connection.cursor(name="daq_samples_parquet_export") as cursor:
                    cursor.itersize = args.fetch_size
                    cursor.execute(query, parameters)
                    while True:
                        batch = cursor.fetchmany(args.fetch_size)
                        if not batch:
                            break
                        writer.write_table(_rows_to_arrow(batch, arrow_schema))
                        row_count += len(batch)
                        LOGGER.info("exported %d rows", row_count)
        finally:
            connection.close()

        writer.close()
        writer = None
        temporary_path.replace(output)
        return ExportStats(rows=row_count, output=output)
    except Exception:
        if writer is not None:
            writer.close()
            writer = None
        raise
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv: Iterable[str] | None = None) -> int:
    """Run the exporter CLI."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    command_line = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(_normalize_relative_timestamp_args(command_line))
    try:
        result = export_samples(args)
    except Exception as exc:
        LOGGER.error("export failed: %s", exc)
        return 1

    LOGGER.info("wrote %d rows to %s", result.rows, result.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
