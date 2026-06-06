-- Track 5.1a — AuditStore schema.
--
-- Owns four tables, all "things that happened or are pending":
--   audit_events             — tool invocations and their authority decisions
--   online_permission_events — user yes/no for connectivity gates
--   agent_messages           — inter-agent message queue
--   commitments              — promises/TODOs FRIDAY has accepted
--
-- Previously these CREATE TABLE statements lived inside
-- ContextStore._ensure_storage alongside 12 unrelated tables.

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL DEFAULT '',
    ok INTEGER NOT NULL DEFAULT 1,
    args_summary TEXT NOT NULL DEFAULT '',
    output_summary TEXT NOT NULL DEFAULT '',
    exec_ms INTEGER NOT NULL DEFAULT 0,
    session_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT 'friday',
    authority_decision TEXT NOT NULL DEFAULT 'allowed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS online_permission_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    from_agent TEXT NOT NULL DEFAULT 'friday',
    to_agent TEXT NOT NULL DEFAULT 'friday',
    msg_type TEXT NOT NULL DEFAULT 'task',
    content TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'normal',
    requires_response INTEGER NOT NULL DEFAULT 0,
    deadline TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commitments (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    what TEXT NOT NULL,
    when_due TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'pending',
    retry_policy TEXT NOT NULL DEFAULT 'none',
    assigned_to TEXT NOT NULL DEFAULT 'friday',
    result TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
