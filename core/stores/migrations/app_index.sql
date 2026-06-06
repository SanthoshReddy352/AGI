-- Track 6.1 — AppIndexStore schema.
--
-- Persists the result of SystemCapabilities.probe()'s desktop-app
-- discovery so we don't re-scan /usr/share/applications (Linux) or the
-- Start Menu + Uninstall registry (Windows) on every boot.
--
-- Owns one table:
--
--   app_index  — one row per discovered application, keyed on canonical
--                lowercase name. `aliases_json` and `categories_json`
--                are JSON arrays. `source` records which scanner found
--                it (binary | desktop | lnk | registry) so a re-scan
--                from a different scanner can supersede a stale row.

CREATE TABLE IF NOT EXISTS app_index (
    canonical TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    command TEXT NOT NULL,
    exec_line TEXT NOT NULL DEFAULT '',
    desktop_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'desktop',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    categories_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_index_name ON app_index(name);
