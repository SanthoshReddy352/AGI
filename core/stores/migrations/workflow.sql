-- Track 5.1b — WorkflowStore schema.
--
-- Owns one table — the multi-turn workflow state machine that survives
-- across turn boundaries and FRIDAY restarts (up to WORKFLOW_TTL_HOURS).
--
-- Previously this CREATE TABLE lived inside ContextStore._ensure_storage
-- alongside 15 unrelated tables.

CREATE TABLE IF NOT EXISTS workflows (
    session_id TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL,
    pending_slots_json TEXT NOT NULL DEFAULT '[]',
    last_action TEXT NOT NULL DEFAULT '',
    target_json TEXT NOT NULL DEFAULT '{}',
    result_summary TEXT NOT NULL DEFAULT '',
    state_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, workflow_name)
);
