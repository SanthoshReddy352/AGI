"""P3.5 — end-of-turn memory nudger.

After every assistant turn, scan the user's most recent message for a
durable personal fact ("I work at X", "my favourite Y is Z", "I live in
Q") that the existing intent paths did *not* already persist. When a
match looks promising, optionally confirm with the chat LLM and write
through the MemoryFacade so both ``memory_items`` and ``facts`` tables
are populated consistently (both read paths see the value).

The cheap regex pass is the gate. The LLM call is only made on matches
— most turns pay zero extra cost. Saves are silent unless the user
literally said "remember", in which case the caller can announce.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.logger import logger

if TYPE_CHECKING:
    from core.memory.facade import MemoryFacade


@dataclass
class NudgeHit:
    namespace: str
    key: str
    value: str

    def as_dict(self) -> dict:
        return {"namespace": self.namespace, "key": self.key, "value": self.value}


# Ordered patterns: more specific first so "I work at X" beats "I am Y".
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bi\s+work\s+at\s+(?P<v>[A-Za-z0-9 .,&'-]+)", re.IGNORECASE),
     "user_profile", "employer"),
    (re.compile(r"\bi\s+live\s+in\s+(?P<v>[A-Za-z .,'-]+)", re.IGNORECASE),
     "user_profile", "location"),
    (re.compile(r"\bcall\s+me\s+(?P<v>[A-Za-z .'-]+)", re.IGNORECASE),
     "user_profile", "name"),
    (re.compile(r"\bmy\s+name\s+is\s+(?P<v>[A-Za-z .'-]+)", re.IGNORECASE),
     "user_profile", "name"),
    (re.compile(r"\bi\s+am\s+a\s+(?P<v>[A-Za-z .,&'-]+)", re.IGNORECASE),
     "user_profile", "role"),
    (re.compile(r"\bi\s+love\s+(?P<v>[A-Za-z0-9 .,&'-]+)", re.IGNORECASE),
     "preferences", "loves"),
    (re.compile(r"\bi\s+like\s+(?P<v>[A-Za-z0-9 .,&'-]+)", re.IGNORECASE),
     "preferences", "likes"),
    (re.compile(r"\bi\s+hate\s+(?P<v>[A-Za-z0-9 .,&'-]+)", re.IGNORECASE),
     "preferences", "hates"),
    (re.compile(r"\bi\s+prefer\s+(?P<v>[A-Za-z0-9 .,&'-]+)", re.IGNORECASE),
     "preferences", "prefers"),
]


_LLM_SYSTEM = (
    "You decide whether the user just stated a durable personal fact "
    "worth remembering across sessions. Reply with a single JSON object "
    "{\"namespace\": \"user_profile|preferences|notes\", "
    "\"key\": \"snake_case_key\", \"value\": \"...\"} or null. "
    "No prose, no markdown."
)


def _cheap_match(text: str) -> NudgeHit | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    for pattern, namespace, key in _PATTERNS:
        m = pattern.search(cleaned)
        if not m:
            continue
        value = m.group("v").strip().rstrip(".!?,")
        # Trim to one short clause so "I work at Anthropic, which is a…"
        # doesn't pull the whole sentence as the value.
        value = re.split(r"[.,;]", value, maxsplit=1)[0].strip()
        if value:
            return NudgeHit(namespace=namespace, key=key, value=value)
    return None


def _llm_confirm(llm, text: str) -> NudgeHit | None:
    if llm is None:
        return None
    try:
        messages = [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": text},
        ]
        if hasattr(llm, "create_chat_completion"):
            result = llm.create_chat_completion(
                messages=messages, max_tokens=80, temperature=0.0, stream=False,
            )
            raw = (result["choices"][0]["message"]["content"] or "").strip()
        else:
            raw = (llm(text, max_tokens=80, temperature=0.0)
                   ["choices"][0]["text"] or "").strip()
    except Exception as exc:
        logger.debug("[nudger] llm confirm failed: %s", exc)
        return None
    if not raw or raw.lower() == "null":
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    namespace = str(parsed.get("namespace") or "notes").strip().lower()
    key = str(parsed.get("key") or "").strip().lower()
    value = str(parsed.get("value") or "").strip()
    if not key or not value:
        return None
    return NudgeHit(namespace=namespace, key=key, value=value)


class MemoryNudger:
    """End-of-turn nudger. Plug ``observe(user_text, ...)`` into the
    turn pipeline after the user's reply has been logged.

    Writes through ``MemoryFacade.remember`` so both the ``memory_items``
    table (used by ``recall_personal_fact``) and the ``facts`` table (used
    by the chat prompt's ``<USER_FACTS>`` block) are populated. Prior to
    this fix the nudger wrote to ``facts`` only, which made the value
    invisible to the ``recall_personal_fact`` capability.
    """

    def __init__(self, memory_facade: "MemoryFacade", llm=None) -> None:
        self._facade = memory_facade
        self._llm = llm

    def observe(self, user_text: str, session_id: str,
                already_saved_keys: set[str] | None = None) -> NudgeHit | None:
        """Return the saved hit, or None if nothing was saved."""
        if not user_text or not session_id:
            return None
        hit = _cheap_match(user_text)
        if hit is None:
            return None
        if already_saved_keys and hit.key in already_saved_keys:
            return None
        confirmed = _llm_confirm(self._llm, user_text) or hit
        try:
            self._facade.remember(
                session_id=session_id,
                key=confirmed.key,
                value=confirmed.value,
                source="user",
            )
        except Exception as exc:
            logger.warning("[nudger] facade.remember failed: %s", exc)
            return None
        logger.info("[nudger] saved %s/%s=%r",
                    confirmed.namespace, confirmed.key, confirmed.value)
        return confirmed


def make_nudger(memory_facade: "MemoryFacade", llm=None) -> MemoryNudger:
    return MemoryNudger(memory_facade, llm)
