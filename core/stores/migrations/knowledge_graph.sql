-- Track 5.1c — KnowledgeGraphStore schema.
--
-- Owns three tables — a typed entity graph:
--
--   entities              — nodes (people, places, concepts) with type + properties
--   entity_facts          — predicate triples (subject_id, predicate, object) with confidence
--   entity_relationships  — edges (from_id, to_id) with relation type

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'concept',
    name TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    session_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_facts (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.7,
    source TEXT NOT NULL DEFAULT '',
    verified_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_relationships (
    id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    rel_type TEXT NOT NULL DEFAULT 'related_to',
    properties_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
