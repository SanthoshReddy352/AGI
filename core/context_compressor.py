"""P3.4 — Context compressor.

Trims a list of chat messages to fit within a token budget while keeping
the system message and most-recent turns.  When the LLM is provided,
older turns beyond the hard drop threshold are replaced with a one-shot
LLM summary instead of being discarded entirely.
"""
from __future__ import annotations

_CHARS_PER_TOKEN = 4  # rough approximation


def _token_estimate(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _messages_tokens(messages: list[dict]) -> int:
    return sum(_token_estimate(m.get("content") or "") for m in messages)


_SUMMARY_SYSTEM = (
    "Summarize the following conversation history in 2-3 sentences, "
    "preserving key facts, decisions, and context needed for follow-up."
)


def _summarize_turns(turns: list[dict], llm) -> str | None:
    if not turns or llm is None:
        return None
    body = "\n".join(f"{t['role']}: {t.get('content', '')}" for t in turns)
    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM},
        {"role": "user", "content": body},
    ]
    try:
        if hasattr(llm, "create_chat_completion"):
            result = llm.create_chat_completion(
                messages=messages, max_tokens=128, temperature=0.3, stream=False
            )
            return (result["choices"][0]["message"]["content"] or "").strip() or None
        text = llm(body, max_tokens=128, temperature=0.3)["choices"][0]["text"]
        return (text or "").strip() or None
    except Exception:
        return None


class ContextCompressor:
    """Trim a messages list to fit within `max_tokens`.

    Strategy (in order):
    1. If already within budget — return as-is.
    2. Drop oldest non-system messages until budget is met.
    3. If an LLM is provided and turns were dropped, insert a synthetic
       assistant summary message so context isn't completely lost.
    """

    def __init__(self, max_tokens: int = 2048, llm=None) -> None:
        self._max_tokens = max_tokens
        self._llm = llm

    def compress(self, messages: list[dict]) -> list[dict]:
        if not messages:
            return []
        if _messages_tokens(messages) <= self._max_tokens:
            return list(messages)

        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        kept, dropped = self._trim(system_msgs, non_system)

        if dropped and self._llm is not None:
            summary = _summarize_turns(dropped, self._llm)
            if summary:
                kept = system_msgs + [
                    {"role": "assistant", "content": f"[Summary of earlier context] {summary}"}
                ] + kept
                return kept

        return system_msgs + kept

    def _trim(
        self, system_msgs: list[dict], non_system: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """Drop from the front of non_system until within budget."""
        system_tokens = _messages_tokens(system_msgs)
        budget = self._max_tokens - system_tokens
        kept = list(non_system)
        dropped: list[dict] = []

        while kept and _messages_tokens(kept) > budget:
            dropped.append(kept.pop(0))

        return kept, dropped


def make_compressor(max_tokens: int = 2048, llm=None) -> ContextCompressor:
    return ContextCompressor(max_tokens=max_tokens, llm=llm)
