-- Baseline migration (T013). Business tables land in US1 (T023), which is out of
-- scope for this implementation run.
CREATE TABLE IF NOT EXISTS schema_baseline (
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
