-- MDDP Ingestion Control Suite - Database Initialization Script
-- Supports PostgreSQL with TimescaleDB Extension

-- 1. Create Database Extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- 2. Telemetry Samples Table & Hypertable
CREATE TABLE IF NOT EXISTS daq_samples (
    time TIMESTAMPTZ NOT NULL,
    channel INT NOT NULL,
    value DOUBLE PRECISION NOT NULL
);

SELECT create_hypertable('daq_samples', 'time', if_not_exists => TRUE);

-- 3. Telemetry Session Metadata Table
CREATE TABLE IF NOT EXISTS daq_sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    clock_rate INT,
    channel_count INT,
    mode VARCHAR(32)
);

-- 4. Musashi II Dispenser Telemetry Table
CREATE TABLE IF NOT EXISTS musashi_ii_data (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    dispense_time DOUBLE PRECISION,
    pressure DOUBLE PRECISION,
    vacuum DOUBLE PRECISION,
    status VARCHAR(32)
);

-- 5. Musashi IV Dispenser Telemetry Table
CREATE TABLE IF NOT EXISTS musashi_iv_data (
    id SERIAL PRIMARY KEY,
    time TIMESTAMPTZ NOT NULL,
    channel INT,
    pressure DOUBLE PRECISION,
    vacuum DOUBLE PRECISION,
    status VARCHAR(32)
);

-- 6. Performance Indexes
CREATE INDEX IF NOT EXISTS idx_daq_samples_channel_time ON daq_samples (channel, time DESC);

-- 7. Periodic LLM Interpretation Summaries
CREATE TABLE IF NOT EXISTS llm_interpret_summaries (
    id BIGSERIAL PRIMARY KEY,
    source_schema TEXT NOT NULL,
    source_table TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    analysis_interval TEXT NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    llm_model TEXT,
    llm_used BOOLEAN NOT NULL DEFAULT FALSE,
    llm_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_schema, source_table, window_start, window_end)
);

CREATE INDEX IF NOT EXISTS idx_llm_interpret_summaries_window
    ON llm_interpret_summaries (window_start DESC);
