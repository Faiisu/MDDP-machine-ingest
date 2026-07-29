import sqlite3
import datetime
import os
import logging

logger = logging.getLogger(__name__)

class DatabaseHandler:
    def __init__(self, db_config):
        """
        Initializes Database Connection based on configuration.
        Supports SQLite out of the box, with extensible support for PostgreSQL/MySQL.
        """
        self.config = db_config
        self.db_type = db_config.get("db_type", "sqlite").lower()
        self.db_name = db_config.get("db_name", "musashi_data.db")
        self.table_name = db_config.get("table_name", "musashi_telemetry")
        self.description = db_config.get("description", "MUSASHI Dispenser Telemetry DB")
        
        self.conn = None
        self.connect()
        self.init_db()

    def connect(self):
        """Establishes connection to the configured database. Auto-creates DB if missing."""
        if self.db_type == "sqlite":
            self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
            logger.info(f"Connected to SQLite database: {self.db_name}")
        elif self.db_type in ("postgres", "postgresql", "timescaledb"):
            try:
                import psycopg2
                try:
                    self.conn = psycopg2.connect(
                        dbname=self.db_name,
                        user=self.config.get("user", "postgres"),
                        password=self.config.get("password", ""),
                        host=self.config.get("host", "localhost"),
                        port=self.config.get("port", 5432)
                    )
                except psycopg2.OperationalError as oe:
                    logger.warning(f"Connecting to database '{self.db_name}' failed ({oe}). Attempting database creation...")
                    maint_conn = psycopg2.connect(
                        dbname="postgres",
                        user=self.config.get("user", "postgres"),
                        password=self.config.get("password", ""),
                        host=self.config.get("host", "localhost"),
                        port=self.config.get("port", 5432)
                    )
                    maint_conn.autocommit = True
                    with maint_conn.cursor() as cur:
                        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (self.db_name,))
                        if not cur.fetchone():
                            cur.execute(f'CREATE DATABASE "{self.db_name}"')
                            logger.info(f"Database '{self.db_name}' auto-created successfully.")
                    maint_conn.close()
                    self.conn = psycopg2.connect(
                        dbname=self.db_name,
                        user=self.config.get("user", "postgres"),
                        password=self.config.get("password", ""),
                        host=self.config.get("host", "localhost"),
                        port=self.config.get("port", 5432)
                    )
                logger.info(f"Connected to PostgreSQL database: {self.db_name} at {self.config.get('host')}")
            except ImportError:
                raise ImportError("psycopg2 package is required for PostgreSQL connections.")
        elif self.db_type == "mysql":
            try:
                import mysql.connector
                try:
                    self.conn = mysql.connector.connect(
                        database=self.db_name,
                        user=self.config.get("user", "root"),
                        password=self.config.get("password", ""),
                        host=self.config.get("host", "localhost"),
                        port=self.config.get("port", 3306)
                    )
                except Exception as me:
                    logger.warning(f"Connecting to MySQL database '{self.db_name}' failed ({me}). Attempting database creation...")
                    maint_conn = mysql.connector.connect(
                        user=self.config.get("user", "root"),
                        password=self.config.get("password", ""),
                        host=self.config.get("host", "localhost"),
                        port=self.config.get("port", 3306)
                    )
                    with maint_conn.cursor() as cur:
                        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{self.db_name}`")
                        logger.info(f"MySQL database '{self.db_name}' auto-created successfully.")
                    maint_conn.close()
                    self.conn = mysql.connector.connect(
                        database=self.db_name,
                        user=self.config.get("user", "root"),
                        password=self.config.get("password", ""),
                        host=self.config.get("host", "localhost"),
                        port=self.config.get("port", 3306)
                    )
                logger.info(f"Connected to MySQL database: {self.db_name} at {self.config.get('host')}")
            except ImportError:
                raise ImportError("mysql-connector-python package is required for MySQL connections.")
        elif self.db_type == "influxdb":
            logger.info("Configured InfluxDB destination.")
            self.conn = None
        else:
            raise ValueError(f"Unsupported database type: {self.db_type}")

    def init_db(self):
        """Creates the target table if it does not already exist."""
        if self.db_type == "influxdb":
            return
            
        cursor = self.conn.cursor()
        
        if self.db_type == "sqlite":
            query = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                channel INTEGER NOT NULL,
                pressure_kpa REAL NOT NULL,
                pressure_raw INTEGER NOT NULL,
                time_ms INTEGER NOT NULL,
                time_sec REAL NOT NULL,
                vacuum_kpa REAL NOT NULL,
                mode_code INTEGER NOT NULL,
                mode_name TEXT NOT NULL,
                product_name TEXT NOT NULL,
                raw_payload TEXT NOT NULL
            );
            """
        elif self.db_type in ("postgres", "postgresql", "timescaledb"):
            query = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                channel INT NOT NULL,
                pressure_kpa DOUBLE PRECISION NOT NULL,
                pressure_raw INT NOT NULL,
                time_ms INT NOT NULL,
                time_sec DOUBLE PRECISION NOT NULL,
                vacuum_kpa DOUBLE PRECISION NOT NULL,
                mode_code INT NOT NULL,
                mode_name VARCHAR(50) NOT NULL,
                product_name VARCHAR(100) NOT NULL,
                raw_payload TEXT NOT NULL
            );
            """
        elif self.db_type == "mysql":
            query = f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                channel INT NOT NULL,
                pressure_kpa DOUBLE NOT NULL,
                pressure_raw INT NOT NULL,
                time_ms INT NOT NULL,
                time_sec DOUBLE NOT NULL,
                vacuum_kpa DOUBLE NOT NULL,
                mode_code INT NOT NULL,
                mode_name VARCHAR(50) NOT NULL,
                product_name VARCHAR(100) NOT NULL,
                raw_payload TEXT NOT NULL
            );
            """
        
        cursor.execute(query)
        self.conn.commit()
        cursor.close()
        logger.info(f"Database table '{self.table_name}' verified/initialized.")

    def insert_telemetry(self, data):
        """
        Inserts a single telemetry record into the database.
        
        :param data: Dictionary containing telemetry parameters from MusashiDispenser
        :return: Inserted record ID or boolean success
        """
        if self.db_type == "influxdb":
            return self._insert_influx(data)

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        if self.db_type == "sqlite":
            db_timestamp = now_dt.isoformat(" ")
        else:
            db_timestamp = now_dt

        if self.db_type in ("sqlite", "postgres", "postgresql", "timescaledb"):
            placeholder = "%s" if self.db_type != "sqlite" else "?"
            query = f"""
            INSERT INTO {self.table_name} (
                timestamp, channel, pressure_kpa, pressure_raw,
                time_ms, time_sec, vacuum_kpa, mode_code,
                mode_name, product_name, raw_payload
            ) VALUES ({', '.join([placeholder]*11)});
            """
            params = (
                db_timestamp,
                data.get("channel", 1),
                data.get("pressure_kpa", 0.0),
                data.get("pressure_raw", 0),
                data.get("time_ms", 0),
                data.get("time_sec", 0.0),
                data.get("vacuum_kpa", 0.0),
                data.get("mode_code", 0),
                data.get("mode_name", ""),
                data.get("product_name", ""),
                data.get("raw_payload", "")
            )
        elif self.db_type == "mysql":
            query = f"""
            INSERT INTO {self.table_name} (
                timestamp, channel, pressure_kpa, pressure_raw,
                time_ms, time_sec, vacuum_kpa, mode_code,
                mode_name, product_name, raw_payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """
            params = (
                db_timestamp,
                data.get("channel", 1),
                data.get("pressure_kpa", 0.0),
                data.get("pressure_raw", 0),
                data.get("time_ms", 0),
                data.get("time_sec", 0.0),
                data.get("vacuum_kpa", 0.0),
                data.get("mode_code", 0),
                data.get("mode_name", ""),
                data.get("product_name", ""),
                data.get("raw_payload", "")
            )

        try:
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            last_row_id = getattr(cursor, "lastrowid", None)
            cursor.close()
            logger.info(f"Inserted record into '{self.table_name}' at {now_dt}")
            return last_row_id
        except Exception as e:
            logger.warning(f"Telemetry insert failed ({e}). Auto-creating database/table and retrying...")
            self.connect()
            self.init_db()
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            self.conn.commit()
            last_row_id = getattr(cursor, "lastrowid", None)
            cursor.close()
            logger.info(f"Inserted record into '{self.table_name}' after auto-creation at {now_dt}")
            return last_row_id

    def _insert_influx(self, data):
        import time
        import urllib.request
        import urllib.parse
        url = self.config.get("influx_url", "http://localhost:8086").rstrip('/')
        token = self.config.get("influx_token", "")
        org = self.config.get("influx_org", "mddp")
        bucket = self.config.get("influx_bucket", "musashi_telemetry")
        measurement = self.config.get("influx_measurement", self.table_name)

        write_url = f"{url}/api/v2/write?org={urllib.parse.quote(org)}&bucket={urllib.parse.quote(bucket)}&precision=s"
        fields = [
            f"pressure_kpa={float(data.get('pressure_kpa', 0.0))}",
            f"pressure_raw={int(data.get('pressure_raw', 0))}i",
            f"time_ms={int(data.get('time_ms', 0))}i",
            f"time_sec={float(data.get('time_sec', 0.0))}",
            f"vacuum_kpa={float(data.get('vacuum_kpa', 0.0))}",
            f"mode_code={int(data.get('mode_code', 0))}i"
        ]
        ts_sec = int(time.time())
        line_protocol = f"{measurement},channel={data.get('channel', 1)} {','.join(fields)} {ts_sec}"

        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Accept": "application/json"
        }
        if token:
            headers["Authorization"] = f"Token {token}"

        req = urllib.request.Request(write_url, data=line_protocol.encode('utf-8'), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status not in (200, 204):
                raise Exception(f"InfluxDB HTTP status {resp.status}")
        return True

    def close(self):
        """Closes the database connection cleanly."""
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("Database connection closed.")
