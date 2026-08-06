"""HTTP API for frontend control of the simulator configuration."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template, request

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
ML_CONFIG_PATH = BASE_DIR.parent / "ml_config.json"
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)


@app.after_request
def allow_frontend_requests(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, PUT, PATCH, OPTIONS"
    return response


def read_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, config: dict) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(config, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_config(config: dict) -> None:
    write_json(CONFIG_PATH, config)


def compatible_database_tables(database: dict) -> list[str]:
    """Return user tables that have the telemetry columns the simulator needs."""

    import psycopg2

    query = """
        SELECT table_schema || '.' || table_name AS table_name
        FROM information_schema.columns
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
          AND column_name IN ('time', 'channel', 'value')
        GROUP BY table_schema, table_name
        HAVING COUNT(DISTINCT column_name) = 3
        ORDER BY table_schema, table_name
    """
    with psycopg2.connect(
        host=database["host"],
        port=database["port"],
        dbname=database["name"],
        user=database["user"],
        password=database["password"],
        connect_timeout=5,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            return [str(row[0]) for row in cursor.fetchall()]


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def get_config():
    return jsonify(read_config())


@app.get("/api/database-tables")
def get_database_tables():
    """List selectable telemetry tables without exposing database credentials."""

    config = read_config()
    database = config.get("database", {})
    try:
        tables = compatible_database_tables(database)
    except Exception as exc:
        return jsonify({"error": f"Could not read database tables: {exc}"}), 503
    selected = str(database.get("table", ""))
    if selected and selected not in tables:
        tables.insert(0, selected)
    return jsonify({"tables": tables, "selected": selected})


@app.get("/api/ml-config")
def get_ml_config():
    with ML_CONFIG_PATH.open(encoding="utf-8") as file:
        return jsonify(json.load(file))


@app.put("/api/ml-config")
def replace_ml_config():
    config = request.get_json(silent=True)
    if not isinstance(config, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    write_json(ML_CONFIG_PATH, config)
    return jsonify(config)


@app.put("/api/config")
def replace_config():
    config = request.get_json(silent=True)
    if not isinstance(config, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    write_config(config)
    return jsonify(config)


@app.patch("/api/config")
def patch_config():
    changes = request.get_json(silent=True)
    if not isinstance(changes, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    config = read_config()
    config.update(changes)
    write_config(config)
    return jsonify(config)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("SIM_CONFIG_PORT", "8090")), debug=False)
