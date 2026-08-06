-- Optional standalone schema migration for the llm-interpret service.
-- The service also creates this table automatically on first startup.

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

