-- Track 5.1c — MemoryStore schema.
--
-- Owns two tables — the canonical key/value fact store and the
-- episodic memory-item ledger:
--
--   facts         — namespaced key/value facts (per-session or global)
--   memory_items  — long-form items with metadata + sensitivity tier
--
-- The Chroma vector index for semantic_recall lives alongside (see
-- MemoryStore._init_vector_store); it's not a SQL table.

CREATE TABLE IF NOT EXISTS facts (
    session_id TEXT NOT NULL DEFAULT '',
    namespace TEXT NOT NULL DEFAULT 'general',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, namespace, key)
);

CREATE TABLE IF NOT EXISTS memory_items (
    item_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    persona_id TEXT NOT NULL DEFAULT '',
    memory_type TEXT NOT NULL DEFAULT 'episodic',
    sensitivity TEXT NOT NULL DEFAULT 'safe_auto',
    content TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
