"""P3.3 — LLM-based session summarizer.

Produces a short bullet-point summary of recent turns using the chat LLM.
Falls back to a naive truncation when no LLM is available.

On session-switch (FridayApp.shutdown / new-session) the orchestrator
``on_session_switch()`` persists the summary as
``memory_items(memory_type='session_summary')`` and extracts durable
facts into ``facts(namespace='auto_extracted')`` so the next session can
recall them via show_memories.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from core.logger import logger

if TYPE_CHECKING:
    from core.stores.memory_store import MemoryStore
    from core.stores.session_store import SessionStore

_SYSTEM = (
    "You are a conversation summarizer. "
    "Summarize the key points of the following conversation turns in 3-5 bullet points. "
    "Be concise. Use plain text, no markdown headers."
)

_MAX_INPUT_CHARS = 6000
_SUMMARY_TOKENS = 256


def _call_llm(llm, messages: list[dict]) -> str:
    try:
        if hasattr(llm, "create_chat_completion"):
            result = llm.create_chat_completion(
                messages=messages,
                max_tokens=_SUMMARY_TOKENS,
                temperature=0.3,
                stream=False,
            )
            return (result["choices"][0]["message"]["content"] or "").strip()
        text = llm(
            messages[-1]["content"],
            max_tokens=_SUMMARY_TOKENS,
            temperature=0.3,
        )["choices"][0]["text"]
        return (text or "").strip()
    except Exception:
        return ""


def _turns_to_text(turns: list[dict]) -> str:
    lines = [f"{t['role']}: {t['text']}" for t in turns]
    return "\n".join(lines)[-_MAX_INPUT_CHARS:]


def _naive_summary(turns: list[dict]) -> str:
    if not turns:
        return "No turns to summarize."
    lines = [f"- {t['role']}: {t['text'][:120]}" for t in turns[-5:]]
    return "\n".join(lines)


_FACT_EXTRACTION_SYSTEM = (
    "From the conversation below, extract durable facts about the USER "
    "(name, role, preferences, places, employer, family). "
    "Reply with a JSON array of objects of shape "
    '{"key": "...", "value": "..."} and nothing else. '
    'If no durable facts are present, reply with [].'
)


def _parse_fact_json(raw: str) -> list[dict]:
    if not raw:
        return []
    text = raw.strip()
    # Strip a leading ```json … ``` fence if present.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    try:
        parsed = json.loads(text)
    except Exception:
        # Try to recover by isolating the first [...] block.
        m = re.search(r"\[.*\]", text, flags=re.DOTALL)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            return []
    if not isinstance(parsed, list):
        return []
    facts: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip().lower().replace(" ", "_")
        value = str(item.get("value") or "").strip()
        if key and value:
            facts.append({"key": key, "value": value})
    return facts


class SessionSummarizer:
    def __init__(self, session_store: "SessionStore", llm=None,
                 memory_store: "MemoryStore | None" = None) -> None:
        self._store = session_store
        self._llm = llm
        self._memory_store = memory_store

    def summarize(self, session_id: str, limit: int = 20) -> str:
        turns = self._get_turns(session_id, limit)
        if not turns:
            return "No conversation history found."
        if self._llm is None:
            return _naive_summary(turns)
        body = _turns_to_text(turns)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": body},
        ]
        result = _call_llm(self._llm, messages)
        return result or _naive_summary(turns)

    def extract_facts(self, session_id: str, limit: int = 40) -> list[dict]:
        """Use the LLM to pull a list of {key, value} dicts from the
        recent turns. Returns [] when there is no LLM or no signal.
        """
        if self._llm is None:
            return []
        turns = self._get_turns(session_id, limit)
        if not turns:
            return []
        body = _turns_to_text(turns)
        messages = [
            {"role": "system", "content": _FACT_EXTRACTION_SYSTEM},
            {"role": "user", "content": body},
        ]
        raw = _call_llm(self._llm, messages)
        return _parse_fact_json(raw)

    def persist_summary(self, session_id: str, summary: str) -> str | None:
        """Save a summary to memory_items(memory_type='session_summary').
        No-op when MemoryStore is not attached. Returns the item_id when
        written.
        """
        ms = self._memory_store
        if ms is None or not summary or not summary.strip():
            return None
        try:
            ms.store_memory_item(
                session_id=session_id,
                content=summary.strip(),
                memory_type="session_summary",
                metadata={"source": "session_summarizer"},
            )
        except Exception as exc:
            logger.warning("[session_summarizer] persist failed: %s", exc)
            return None
        return "ok"

    def persist_facts(self, session_id: str, facts: list[dict]) -> int:
        """Save extracted facts to facts(namespace='auto_extracted'). Returns
        count written. Uses the MemoryStore facts table directly.
        """
        ms = self._memory_store
        if ms is None or not facts:
            return 0
        saved = 0
        for fact in facts:
            try:
                ms.store_fact(
                    key=fact["key"],
                    value=fact["value"],
                    session_id=session_id,
                    namespace="auto_extracted",
                )
                saved += 1
            except Exception as exc:
                logger.warning("[session_summarizer] fact write failed: %s", exc)
        return saved

    def on_session_switch(self, session_id: str) -> dict:
        """Run summarize + fact extraction + persistence for the
        outgoing session. Safe to call without an LLM (still writes the
        naive summary). Returns a result dict for observability.
        """
        summary = self.summarize(session_id)
        wrote_summary = self.persist_summary(session_id, summary)
        facts = self.extract_facts(session_id)
        wrote_facts = self.persist_facts(session_id, facts)
        return {
            "summary": summary,
            "summary_saved": bool(wrote_summary),
            "facts": facts,
            "facts_saved": wrote_facts,
        }

    def _get_turns(self, session_id: str, limit: int) -> list[dict]:
        with self._store._connect() as conn:
            rows = conn.execute(
                "SELECT role, text FROM turns WHERE session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, max(1, int(limit))),
            ).fetchall()
        rows = list(reversed(rows))
        return [{"role": r[0], "text": r[1]} for r in rows]


def make_summarizer(session_store: "SessionStore", llm=None,
                    memory_store: "MemoryStore | None" = None) -> SessionSummarizer:
    return SessionSummarizer(session_store, llm, memory_store=memory_store)
