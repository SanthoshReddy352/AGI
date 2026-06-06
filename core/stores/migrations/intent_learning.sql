-- Adaptive Intent Recognition — IntentLearningStore schema.
--
-- Owns three tables that back FRIDAY's day-by-day routing learning:
--
--   routing_observations — append-only log of every routing decision
--                          (Phase 1: measurement; the raw signal everything
--                          else is derived from).
--   learned_phrases      — per-user phrasing → tool memory with a hit/
--                          correction ledger and a promotion status
--                          (candidate → promoted → blocked). Drives
--                          auto-dispatch after N confirmed repeats (Phase 4).
--   intent_profile       — per-tool usage aggregates (frequency, time-of-day
--                          histogram, favourite args) used as a routing
--                          tie-breaker (Phase 5).

CREATE TABLE IF NOT EXISTS routing_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    normalized TEXT NOT NULL DEFAULT '',
    chosen_tool TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    plan_mode TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0.0,
    confirmed INTEGER NOT NULL DEFAULT 0,   -- -1 = corrected/no, 0 = unknown, 1 = yes
    corrected_to TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_routing_obs_tool ON routing_observations (chosen_tool);
CREATE INDEX IF NOT EXISTS idx_routing_obs_norm ON routing_observations (normalized);

CREATE TABLE IF NOT EXISTS learned_phrases (
    normalized TEXT NOT NULL,
    tool TEXT NOT NULL,
    raw TEXT NOT NULL DEFAULT '',
    hit_count INTEGER NOT NULL DEFAULT 0,
    corrected_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'candidate',   -- candidate | promoted | blocked
    first_seen TEXT NOT NULL,
    last_used TEXT NOT NULL,
    PRIMARY KEY (normalized, tool)
);

CREATE INDEX IF NOT EXISTS idx_learned_status ON learned_phrases (status);

CREATE TABLE IF NOT EXISTS intent_profile (
    tool TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    last_used TEXT NOT NULL DEFAULT '',
    hour_histogram TEXT NOT NULL DEFAULT '[]',   -- 24-int JSON array
    fav_args_json TEXT NOT NULL DEFAULT '{}'
);
