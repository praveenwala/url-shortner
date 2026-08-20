-- Declared inputs and outputs on task nodes (T038 correction, FR-021, FR-041).
--
-- The bounded agent runtime derives its write allow-list from declared_outputs,
-- so the set must survive persistence: dispatch reads the node from the store,
-- not from the planner's memory.

ALTER TABLE task_node ADD COLUMN IF NOT EXISTS declared_inputs  JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE task_node ADD COLUMN IF NOT EXISTS declared_outputs JSONB NOT NULL DEFAULT '[]'::jsonb;
