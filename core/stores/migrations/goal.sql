-- Track 5.1c — GoalStore schema.
--
-- Owns two tables — the goal tracking ledger:
--
--   goals          — rows with score, status, health, time_horizon
--   goal_progress  — append-only score-change log per goal

CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL DEFAULT 'task',
    parent_id TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'active',
    health TEXT NOT NULL DEFAULT 'on_track',
    time_horizon TEXT NOT NULL DEFAULT 'weekly',
    escalation_stage TEXT NOT NULL DEFAULT 'none',
    tags_json TEXT NOT NULL DEFAULT '[]',
    estimated_hours REAL NOT NULL DEFAULT 0.0,
    actual_hours REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS goal_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id TEXT NOT NULL,
    score_before REAL NOT NULL DEFAULT 0.0,
    score_after REAL NOT NULL DEFAULT 0.0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
