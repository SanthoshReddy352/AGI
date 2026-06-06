-- Track 6.2 — FileIndexStore schema.
--
-- One table — the path index used by the background FileIndexer to
-- answer "where is the file called X" without walking the filesystem
-- per turn.
--
-- Search uses `LIKE` on `name` / `parent_dir` for now; if that proves
-- too coarse we can swap in an FTS5 virtual table without changing the
-- write path.

CREATE TABLE IF NOT EXISTS file_index (
    path TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_dir TEXT NOT NULL,
    ext TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    indexed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_file_index_name ON file_index(name);
CREATE INDEX IF NOT EXISTS idx_file_index_parent ON file_index(parent_dir);
CREATE INDEX IF NOT EXISTS idx_file_index_ext ON file_index(ext);
