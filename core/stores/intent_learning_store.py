"""Adaptive Intent Recognition — IntentLearningStore.

Owns three tables — `routing_observations`, `learned_phrases`,
`intent_profile` — that back FRIDAY's day-by-day routing learning.

Phase 1 (measurement) uses `record_observation` / `recent_observations`
only. The learned-phrase ledger and profile aggregates are implemented
here too so later phases (confirmation loop, auto-dispatch after repeats,
profile biasing) have a stable persistence API to build on.

Follows the Track 5.1 domain-store contract: this store creates and
writes ONLY its own three tables, and every method is ≤30 lines.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone


# Promote a candidate phrasing to auto-dispatch after this many confirmed
# hits with zero corrections (user decision: N=3).
PROMOTE_AFTER = 3

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _migrations_path() -> str:
    return os.path.join(os.path.dirname(__file__), "migrations", "intent_learning.sql")


def normalize_key(text: str) -> str:
    """Canonical dedup key for a phrasing: lowercase, de-punctuated, single-spaced.

    This is a *lexical* key, not the STT-typo correction in
    `core.text_normalize.normalize_for_routing` — callers should run that
    first if they want typo folding, then key the result through here.
    """
    if not text:
        return ""
    lowered = _PUNCT_RE.sub(" ", text.lower())
    return _WS_RE.sub(" ", lowered).strip()


class IntentLearningStore:
    """Routing observations + learned phrasings + per-tool usage profile."""

    def __init__(self, db_path: str, promote_after: int = PROMOTE_AFTER):
        self.db_path = db_path
        # Phase 6: promotion threshold N is config-tunable (routing.promote_after);
        # falls back to the module default when constructed without one.
        self.promote_after = int(promote_after) if promote_after else PROMOTE_AFTER
        self._ensure_storage()

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

    # ------------------------------------------------------------------
    # routing_observations  (Phase 1 — measurement)
    # ------------------------------------------------------------------

    def record_observation(self, text: str, chosen_tool: str, source: str,
                           *, turn_id: str = "", session_id: str = "",
                           plan_mode: str = "", score: float = 0.0,
                           confirmed: int = 0, corrected_to: str = "") -> int:
        """Append one routing decision. Returns the new row id."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO routing_observations
                   (turn_id, session_id, text, normalized, chosen_tool, source,
                    plan_mode, score, confirmed, corrected_to, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (turn_id, session_id, text, normalize_key(text), chosen_tool,
                 source, plan_mode, float(score), int(confirmed), corrected_to,
                 _utc_now()),
            )
            conn.commit()
            return int(cur.lastrowid)

    def recent_observations(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM routing_observations ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]

    def source_breakdown(self) -> dict[str, int]:
        """Count of observations per routing source — feeds the eval report."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source, COUNT(*) FROM routing_observations GROUP BY source"
            ).fetchall()
            return {src or "": int(n) for src, n in rows}

    # ------------------------------------------------------------------
    # learned_phrases  (Phase 4 — auto-dispatch after repeats)
    # ------------------------------------------------------------------

    def note_hit(self, text: str, tool: str) -> dict:
        """Record a confirmed phrasing→tool hit; auto-promote at PROMOTE_AFTER.

        Returns the resulting row (including its `status`).
        """
        key, now = normalize_key(text), _utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO learned_phrases
                       (normalized, tool, raw, hit_count, first_seen, last_used)
                   VALUES (?, ?, ?, 1, ?, ?)
                   ON CONFLICT(normalized, tool) DO UPDATE SET
                       hit_count = hit_count + 1,
                       last_used = excluded.last_used""",
                (key, tool, text, now, now),
            )
            conn.execute(
                """UPDATE learned_phrases SET status='promoted'
                   WHERE normalized=? AND tool=? AND status='candidate'
                     AND hit_count >= ? AND corrected_count = 0""",
                (key, tool, self.promote_after),
            )
            conn.commit()
        return self.get_phrase(text, tool) or {}

    def note_correction(self, text: str, tool: str) -> None:
        """Record that ``tool`` was the WRONG target for ``text``; block it."""
        key, now = normalize_key(text), _utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO learned_phrases
                       (normalized, tool, raw, corrected_count, status,
                        first_seen, last_used)
                   VALUES (?, ?, ?, 1, 'blocked', ?, ?)
                   ON CONFLICT(normalized, tool) DO UPDATE SET
                       corrected_count = corrected_count + 1,
                       status = 'blocked',
                       last_used = excluded.last_used""",
                (key, tool, text, now, now),
            )
            conn.commit()

    def get_phrase(self, text: str, tool: str) -> dict | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM learned_phrases WHERE normalized=? AND tool=?",
                (normalize_key(text), tool),
            ).fetchone()
            return dict(row) if row else None

    def promoted_phrases(self) -> list[dict]:
        """All phrasings cleared for auto-dispatch (status='promoted')."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM learned_phrases WHERE status='promoted' "
                "ORDER BY hit_count DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def active_phrases(self) -> list[dict]:
        """Non-blocked phrasings (candidate + promoted) — for boot embedding
        registration so learned phrasings boost their tool's cosine reach."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM learned_phrases WHERE status != 'blocked' "
                "ORDER BY hit_count DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def promoted_lookup(self, text: str) -> dict | None:
        """Return the promoted phrasing→tool row matching ``text`` exactly
        (by normalized key), highest hit_count first. None if not promoted.

        This is the auto-dispatch path: a phrasing the user confirmed
        PROMOTE_AFTER times routes deterministically with `source="learned"`.
        """
        key = normalize_key(text)
        if not key:
            return None
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM learned_phrases WHERE normalized=? AND "
                "status='promoted' ORDER BY hit_count DESC LIMIT 1",
                (key,),
            ).fetchone()
            return dict(row) if row else None

    def forget_all(self) -> int:
        """Wipe learned phrasings + profile (the user's 'forget how I talk').

        Leaves `routing_observations` intact as an audit trail. Returns the
        number of learned_phrases rows removed.
        """
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM learned_phrases")
            conn.execute("DELETE FROM intent_profile")
            conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # intent_profile  (Phase 5 — tie-breaker biasing)
    # ------------------------------------------------------------------

    def bump_profile(self, tool: str, *, hour: int | None = None) -> None:
        """Increment a tool's usage count and time-of-day histogram bucket."""
        now = _utc_now()
        hour = datetime.now().hour if hour is None else int(hour) % 24
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT count, hour_histogram FROM intent_profile WHERE tool=?",
                (tool,),
            ).fetchone()
            hist = json.loads(row["hour_histogram"]) if row else [0] * 24
            if len(hist) != 24:
                hist = [0] * 24
            hist[hour] += 1
            count = (row["count"] if row else 0) + 1
            conn.execute(
                """INSERT INTO intent_profile (tool, count, last_used, hour_histogram)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(tool) DO UPDATE SET
                       count=excluded.count, last_used=excluded.last_used,
                       hour_histogram=excluded.hour_histogram""",
                (tool, count, now, json.dumps(hist)),
            )
            conn.commit()

    def record_args(self, tool: str, args: dict) -> None:
        """Fold the args a tool was dispatched with into its favourite-args
        frequency map: ``{arg_name: {value: count}}``. Only short scalar values
        are tracked (the 'which app / which browser' preference signal)."""
        if not tool or not args:
            return
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT fav_args_json FROM intent_profile WHERE tool=?", (tool,)
            ).fetchone()
            fav = json.loads(row["fav_args_json"]) if row and row["fav_args_json"] else {}
            for key, value in args.items():
                if not isinstance(value, (str, int, float, bool)):
                    continue
                sval = str(value).strip()
                if not sval or len(sval) > 60:
                    continue
                counts = fav.setdefault(key, {})
                counts[sval] = int(counts.get(sval, 0)) + 1
            conn.execute(
                """INSERT INTO intent_profile (tool, count, last_used, fav_args_json)
                   VALUES (?, 0, ?, ?)
                   ON CONFLICT(tool) DO UPDATE SET fav_args_json=excluded.fav_args_json""",
                (tool, _utc_now(), json.dumps(fav)),
            )
            conn.commit()

    def favorite_args(self, tool: str) -> dict:
        """Return ``{arg_name: most_frequent_value}`` for ``tool``."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT fav_args_json FROM intent_profile WHERE tool=?", (tool,)
            ).fetchone()
        if not row or not row["fav_args_json"]:
            return {}
        fav = json.loads(row["fav_args_json"])
        out: dict = {}
        for key, counts in fav.items():
            if counts:
                out[key] = max(counts.items(), key=lambda kv: kv[1])[0]
        return out

    def profile_score(self, tool: str, hour: int | None = None) -> float:
        """Relative preference score for ``tool`` — usage frequency plus a
        bump for the current hour-of-day. Used only as a routing tie-breaker.
        Returns 0.0 for an unseen tool."""
        hour = datetime.now().hour if hour is None else int(hour) % 24
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT count, hour_histogram FROM intent_profile WHERE tool=?",
                (tool,),
            ).fetchone()
        if not row:
            return 0.0
        count = int(row["count"] or 0)
        try:
            hist = json.loads(row["hour_histogram"] or "[]")
        except Exception:
            hist = []
        hour_hits = int(hist[hour]) if len(hist) == 24 else 0
        return float(count) + 2.0 * float(hour_hits)

    def top_tools(self, limit: int = 10) -> list[dict]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM intent_profile ORDER BY count DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]
