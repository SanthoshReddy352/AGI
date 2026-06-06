-- Track 5.1d — SessionStore schema.
--
-- Owns four tables — the session lifecycle + per-session state +
-- persona registry:
--
--   sessions               — the session row (one per FRIDAY conversation)
--   turns                  — append-only utterance log per session
--   conversation_sessions  — per-session JSON state (working_artifact, reference_registry, pending_online, active_persona_id)
--   personas               — persona definitions (display_name, system_identity, style traits, etc.)
--
-- This is the last of the four domain stores. After this commit
-- ContextStore owns ZERO tables; it survives only as a transitional
-- facade for ~30 existing callers and goes away in a 5.1e sweep.

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS personas (
    persona_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    system_identity TEXT NOT NULL DEFAULT '',
    tone_traits TEXT NOT NULL DEFAULT '',
    conversation_style TEXT NOT NULL DEFAULT '',
    speech_style TEXT NOT NULL DEFAULT '',
    humor_level TEXT NOT NULL DEFAULT '',
    verbosity_preference TEXT NOT NULL DEFAULT '',
    formality_level TEXT NOT NULL DEFAULT '',
    empathy_style TEXT NOT NULL DEFAULT '',
    tool_ack_style TEXT NOT NULL DEFAULT '',
    memory_scope TEXT NOT NULL DEFAULT 'shared',
    retrieval_filters TEXT NOT NULL DEFAULT '',
    example_dialogues TEXT NOT NULL DEFAULT '',
    enabled_skills TEXT NOT NULL DEFAULT '*',
    disallowed_behaviors TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id TEXT PRIMARY KEY,
    active_persona_id TEXT NOT NULL DEFAULT '',
    pending_online_json TEXT NOT NULL DEFAULT '{}',
    state_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

-- P3.2: FTS5 full-text search over turns (keyword search across past conversation).
-- content= links it to the turns table; trigger keeps them in sync.
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    text,
    content=turns,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS turns_fts_insert AFTER INSERT ON turns BEGIN
    INSERT INTO turns_fts(rowid, text) VALUES (NEW.id, NEW.text);
END;
