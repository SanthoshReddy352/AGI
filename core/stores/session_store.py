"""Track 5.1d — SessionStore.

Extracted from `core.context_store.ContextStore`. Final of the four
domain stores. Owns four tables (see `migrations/session.sql`):

    sessions, turns, conversation_sessions, personas

Also owns the `WorkingArtifact` dataclass + `ARTIFACT_SCOPE_RANK`
constant + `artifact_scope_rank` helper — these live in
`conversation_sessions.state_json`, so they're SessionStore territory.

The 62-line `save_persona` body was decomposed so every public method
is ≤30 lines (Direction §5.1 rule). The cross-domain orchestrators
(append_turn, save_persona) split into the SQL-only `append_turn_row`
and `upsert_persona_row` primitives here; ContextStore (the
transitional facade) calls those plus `memory_store.upsert_vector` to
keep the vector index in sync.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "session.sql")


# ----------------------------------------------------------------------
# WorkingArtifact (lives in session_state JSON — SessionStore territory)
# ----------------------------------------------------------------------

@dataclass
class WorkingArtifact:
    """Tracks the last meaningful capability output for the current session.

    Stored in `conversation_sessions.state_json["working_artifact"]` so
    it survives across the turn boundary. Enables pronoun resolution:
    "save that", "use this", "read it back".

    ``scope`` governs how aggressively the artifact bleeds across turns.
    Track 1.2 introduced strict precedence ranks so a fresh file write
    always supersedes a stale explicit target from earlier — the
    original bug was an "explicit" target from N turns back silently
    winning against a newer auto-scope save.

    * ``"inferred"``  (rank 1) — guessed from context; any concrete save wins
    * ``"auto"``      (rank 2) — set by side-effect; older auto-scope superseded
    * ``"explicit"``  (rank 3) — the user named the target; persists vs auto/inferred
    * ``"last_write"`` (rank 4) — file mutation just completed; wins over explicit
    * ``"session"``   (rank 5) — long-lived pin (not currently issued anywhere)
    """
    content: str
    output_type: str = "text"
    capability_name: str = ""
    artifact_type: str = "text"
    source_path: str = ""
    scope: str = "auto"
    created_at: str = ""


ARTIFACT_SCOPE_RANK = {
    "inferred": 1,
    "auto": 2,
    "explicit": 3,
    "last_write": 4,
    "session": 5,
}


def artifact_scope_rank(scope: str) -> int:
    """Return the precedence rank for an artifact scope, defaulting to `auto`."""
    return ARTIFACT_SCOPE_RANK.get(scope or "auto", ARTIFACT_SCOPE_RANK["auto"])


# ----------------------------------------------------------------------
# Persona row mapping helpers
# ----------------------------------------------------------------------

_PERSONA_COLUMNS = (
    "persona_id", "display_name", "system_identity", "tone_traits",
    "conversation_style", "speech_style", "humor_level",
    "verbosity_preference", "formality_level", "empathy_style",
    "tool_ack_style", "memory_scope", "retrieval_filters",
    "example_dialogues", "enabled_skills", "disallowed_behaviors",
    "updated_at",
)


def _persona_row_to_dict(row) -> dict:
    return dict(zip(_PERSONA_COLUMNS, row))


class SessionStore:
    """Sessions + turns + session-state JSON + personas."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_storage()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_storage(self) -> None:
        _db_dir = os.path.dirname(self.db_path)
        if _db_dir:
            os.makedirs(_db_dir, exist_ok=True)
        with open(_migrations_path(), "r", encoding="utf-8") as fh:
            schema_sql = fh.read()
        with self._connect() as conn:
            conn.executescript(schema_sql)
            conn.commit()
        self._backfill_fts_if_empty()

    def _backfill_fts_if_empty(self) -> None:
        # P3.2: the AFTER INSERT trigger only catches new turns. If turns
        # exist from before the FTS5 table was added, mirror them now.
        try:
            with self._connect() as conn:
                fts_count = conn.execute("SELECT count(*) FROM turns_fts").fetchone()[0]
                turn_count = conn.execute("SELECT count(*) FROM turns").fetchone()[0]
                if fts_count >= turn_count or turn_count == 0:
                    return
                conn.execute(
                    "INSERT INTO turns_fts(rowid, text) "
                    "SELECT id, text FROM turns WHERE id NOT IN (SELECT rowid FROM turns_fts)"
                )
                conn.commit()
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------------------------------
    # sessions
    # ------------------------------------------------------------------

    def start_session(self, metadata: dict | None = None) -> str:
        session_id = str(uuid.uuid4())
        now = _utc_now()
        payload = json.dumps(metadata or {}, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (id, started_at, updated_at, metadata_json) "
                "VALUES (?, ?, ?, ?)",
                (session_id, now, now, payload),
            )
            conn.commit()
        return session_id

    def bump_session(self, session_id: str, now: str | None = None) -> None:
        """Bump `sessions.updated_at`. Used by cross-domain writers
        (append_turn, save_workflow_state) so the parent session shows
        recent activity even when only a child table changed.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now or _utc_now(), session_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # turns
    # ------------------------------------------------------------------

    def append_turn_row(self, session_id: str, role: str, text: str,
                        source: str | None = None) -> str:
        """SQL-only turn append. Returns the timestamp used for the row.

        The companion vector-index write (memory:turn:...) is the
        orchestrator's responsibility — kept out of SessionStore so the
        store stays single-domain.
        """
        if not session_id:
            return ""
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO turns (session_id, role, text, source, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, role, str(text), source or role, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            conn.commit()
        return now

    def summarize_session(self, session_id: str, limit: int = 6) -> str:
        if not session_id:
            return ""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, text FROM turns WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, max(1, int(limit))),
            ).fetchall()
        if not rows:
            return ""
        rows = list(reversed(rows))
        return "\n".join(f"{role}: {text}" for role, text in rows)

    def prune_old_turns(self, session_id: str, older_than_days: int = 30) -> int:
        cutoff = (datetime.utcnow() - timedelta(days=older_than_days)).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM turns WHERE session_id = ? AND created_at < ?",
                (session_id, cutoff),
            )
            conn.commit()
        return cur.rowcount

    def fts_search(self, query: str, limit: int = 10) -> list[dict]:
        """FTS5 keyword search over turns text. Returns newest-first."""
        if not query or not query.strip():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT t.id, t.session_id, t.role, t.text, t.created_at "
                "FROM turns t JOIN turns_fts f ON t.id = f.rowid "
                "WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?",
                (query.strip(), max(1, int(limit))),
            ).fetchall()
        return [
            {"id": r[0], "session_id": r[1], "role": r[2], "text": r[3], "created_at": r[4]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # conversation_sessions (session-state JSON)
    # ------------------------------------------------------------------

    def save_session_state(self, session_id: str, state: dict) -> None:
        if not session_id:
            return
        payload = dict(state or {})
        active_persona_id = str(payload.get("active_persona_id") or "")
        pending_online_json = json.dumps(
            payload.get("pending_online") or {}, ensure_ascii=True
        )
        state_json = json.dumps(payload, ensure_ascii=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_sessions (
                    session_id, active_persona_id, pending_online_json, state_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id)
                DO UPDATE SET
                    active_persona_id = excluded.active_persona_id,
                    pending_online_json = excluded.pending_online_json,
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, active_persona_id, pending_online_json,
                 state_json, _utc_now()),
            )
            conn.commit()

    def get_session_state(self, session_id: str) -> dict:
        if not session_id:
            return {}
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active_persona_id, pending_online_json, state_json, updated_at "
                "FROM conversation_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return {}
        active_persona_id, pending_online_json, state_json, updated_at = row
        payload = json.loads(state_json or "{}")
        payload.setdefault("active_persona_id", active_persona_id or "")
        payload.setdefault("pending_online", json.loads(pending_online_json or "{}"))
        payload.setdefault("updated_at", updated_at)
        return payload

    # ------------------------------------------------------------------
    # Active persona helpers (read/write session_state.active_persona_id)
    # ------------------------------------------------------------------

    def set_active_persona(self, session_id: str, persona_id: str) -> None:
        state = self.get_session_state(session_id)
        state["active_persona_id"] = persona_id
        self.save_session_state(session_id, state)

    def get_active_persona_id(self, session_id: str) -> str:
        return (self.get_session_state(session_id) or {}).get("active_persona_id", "")

    # ------------------------------------------------------------------
    # pending_online (read/write session_state.pending_online)
    # ------------------------------------------------------------------

    def set_pending_online(self, session_id: str, payload: dict) -> None:
        state = self.get_session_state(session_id)
        state["pending_online"] = dict(payload or {})
        self.save_session_state(session_id, state)

    def clear_pending_online(self, session_id: str) -> None:
        state = self.get_session_state(session_id)
        if not state:
            return
        state["pending_online"] = {}
        self.save_session_state(session_id, state)

    # ------------------------------------------------------------------
    # pending_intent (Adaptive Intent Recognition Phase 2 — confirmation)
    # ------------------------------------------------------------------
    # Stored in the generic state_json (no dedicated column needed): the
    # mid-band embedding match awaiting a yes/no "did you mean …?" answer.

    def set_pending_intent(self, session_id: str, payload: dict) -> None:
        state = self.get_session_state(session_id)
        state["pending_intent"] = dict(payload or {})
        self.save_session_state(session_id, state)

    def clear_pending_intent(self, session_id: str) -> None:
        state = self.get_session_state(session_id)
        if not state:
            return
        state["pending_intent"] = {}
        self.save_session_state(session_id, state)

    # ------------------------------------------------------------------
    # Working artifact (typed view over session_state.working_artifact)
    # ------------------------------------------------------------------

    def save_artifact(self, session_id: str, artifact: WorkingArtifact) -> None:
        """Persist with strict scope-precedence: a new save wins iff its
        scope rank >= the existing scope's rank. Lower-rank saves are
        silently dropped so a stale `explicit` from N turns back can't
        displace a fresh `last_write`.
        """
        state = self.get_session_state(session_id) or {}
        existing = state.get("working_artifact") or {}
        new_scope = artifact.scope or "auto"
        if existing:
            new_rank = artifact_scope_rank(new_scope)
            existing_rank = artifact_scope_rank(existing.get("scope") or "auto")
            if new_rank < existing_rank:
                return
        state["working_artifact"] = {
            "content": artifact.content,
            "output_type": artifact.output_type,
            "capability_name": artifact.capability_name,
            "artifact_type": artifact.artifact_type,
            "source_path": artifact.source_path,
            "scope": new_scope,
            "created_at": artifact.created_at or datetime.now().isoformat(),
        }
        self.save_session_state(session_id, state)

    def get_artifact(self, session_id: str) -> WorkingArtifact | None:
        state = self.get_session_state(session_id) or {}
        data = state.get("working_artifact")
        if not data:
            return None
        return WorkingArtifact(
            content=data.get("content", ""),
            output_type=data.get("output_type", "text"),
            capability_name=data.get("capability_name", ""),
            artifact_type=data.get("artifact_type", "text"),
            source_path=data.get("source_path", ""),
            scope=data.get("scope", "auto"),
            created_at=data.get("created_at", ""),
        )

    def clear_artifact(self, session_id: str) -> None:
        state = self.get_session_state(session_id) or {}
        if "working_artifact" in state:
            del state["working_artifact"]
            self.save_session_state(session_id, state)

    # ------------------------------------------------------------------
    # Reference registry (typed view over session_state.reference_registry)
    # ------------------------------------------------------------------

    def save_reference(self, session_id: str, key: str, value: str) -> None:
        state = self.get_session_state(session_id) or {}
        refs = state.setdefault("reference_registry", {})
        refs[key] = value
        self.save_session_state(session_id, state)

    def get_reference(self, session_id: str, key: str) -> str | None:
        state = self.get_session_state(session_id) or {}
        return state.get("reference_registry", {}).get(key)

    def get_all_references(self, session_id: str) -> dict:
        state = self.get_session_state(session_id) or {}
        return dict(state.get("reference_registry", {}))

    # ------------------------------------------------------------------
    # personas
    # ------------------------------------------------------------------

    def upsert_persona_row(self, payload: dict) -> str:
        """SQL-only persona upsert. Returns the persona_id (empty string
        if the payload had no id and so the call was a no-op).

        The companion vector-index write of `example_dialogues` is the
        orchestrator's responsibility.
        """
        data = dict(payload or {})
        persona_id = str(data.get("persona_id") or "").strip()
        if not persona_id:
            return ""
        with self._connect() as conn:
            conn.execute(self._persona_upsert_sql(), self._persona_upsert_params(persona_id, data))
            conn.commit()
        return persona_id

    @staticmethod
    def _persona_upsert_sql() -> str:
        return """
            INSERT INTO personas (
                persona_id, display_name, system_identity, tone_traits, conversation_style,
                speech_style, humor_level, verbosity_preference, formality_level,
                empathy_style, tool_ack_style, memory_scope, retrieval_filters,
                example_dialogues, enabled_skills, disallowed_behaviors, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(persona_id)
            DO UPDATE SET
                display_name = excluded.display_name,
                system_identity = excluded.system_identity,
                tone_traits = excluded.tone_traits,
                conversation_style = excluded.conversation_style,
                speech_style = excluded.speech_style,
                humor_level = excluded.humor_level,
                verbosity_preference = excluded.verbosity_preference,
                formality_level = excluded.formality_level,
                empathy_style = excluded.empathy_style,
                tool_ack_style = excluded.tool_ack_style,
                memory_scope = excluded.memory_scope,
                retrieval_filters = excluded.retrieval_filters,
                example_dialogues = excluded.example_dialogues,
                enabled_skills = excluded.enabled_skills,
                disallowed_behaviors = excluded.disallowed_behaviors,
                updated_at = excluded.updated_at
        """

    @staticmethod
    def _persona_upsert_params(persona_id: str, data: dict) -> tuple:
        return (
            persona_id,
            data.get("display_name", persona_id),
            data.get("system_identity", ""),
            data.get("tone_traits", ""),
            data.get("conversation_style", ""),
            data.get("speech_style", ""),
            data.get("humor_level", ""),
            data.get("verbosity_preference", ""),
            data.get("formality_level", ""),
            data.get("empathy_style", ""),
            data.get("tool_ack_style", ""),
            data.get("memory_scope", "shared"),
            data.get("retrieval_filters", ""),
            data.get("example_dialogues", ""),
            data.get("enabled_skills", "*"),
            data.get("disallowed_behaviors", ""),
            _utc_now(),
        )

    def get_persona(self, persona_id: str) -> dict | None:
        if not persona_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT " + ", ".join(_PERSONA_COLUMNS) +
                " FROM personas WHERE persona_id = ?",
                (persona_id,),
            ).fetchone()
        return _persona_row_to_dict(row) if row else None

    def list_personas(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT " + ", ".join(_PERSONA_COLUMNS) +
                " FROM personas ORDER BY display_name ASC"
            ).fetchall()
        return [_persona_row_to_dict(r) for r in rows]
