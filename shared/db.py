import psycopg2
import psycopg2.extras

def get_connection(dsn):
    """
    Creates a psycopg2 database connection given a DSN.
    """
    return psycopg2.connect(dsn)

def ensure_tables(conn):
    """
    Ensures core tables exist in the database.
    """
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daq_samples (
                time TIMESTAMPTZ NOT NULL,
                channel INT NOT NULL,
                value DOUBLE PRECISION NOT NULL
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daq_sessions (
                session_id VARCHAR(64) PRIMARY KEY,
                start_time TIMESTAMPTZ NOT NULL,
                end_time TIMESTAMPTZ,
                clock_rate INT,
                channel_count INT,
                mode VARCHAR(32)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS musashi_ii_data (
                id SERIAL PRIMARY KEY,
                time TIMESTAMPTZ NOT NULL,
                dispense_time DOUBLE PRECISION,
                pressure DOUBLE PRECISION,
                vacuum DOUBLE PRECISION,
                status VARCHAR(32)
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS musashi_iv_data (
                id SERIAL PRIMARY KEY,
                time TIMESTAMPTZ NOT NULL,
                channel INT,
                pressure DOUBLE PRECISION,
                vacuum DOUBLE PRECISION,
                status VARCHAR(32)
            );
        """)
        try:
            cur.execute("SELECT create_hypertable('daq_samples', 'time', if_not_exists => TRUE);")
        except Exception:
            conn.rollback()
        else:
            conn.commit()
