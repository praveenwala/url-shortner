-- Clarifications belong to a requirement, not only to a run (US3, FR-028).
--
-- A run is one attempt; the requirement is the thing being clarified. Recording
-- the requirement reference is what lets a later run see that a question was
-- already asked and answered, and what makes the lineage traceable to FR-028.

ALTER TABLE clarification_request ADD COLUMN IF NOT EXISTS requirement_id TEXT;
ALTER TABLE clarification_request ADD COLUMN IF NOT EXISTS round INTEGER NOT NULL DEFAULT 1;
ALTER TABLE clarification_request ADD COLUMN IF NOT EXISTS rule TEXT;

CREATE INDEX IF NOT EXISTS clarification_requirement_idx
    ON clarification_request (requirement_id);
