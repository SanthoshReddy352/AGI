"""P3.13 — Mixture of Agents (MoA): parallel multi-model synthesis.

Runs the same prompt through the chat model and the tool model in parallel,
then calls a third synthesis pass to merge the two answers into one best
response. Default-off; triggered explicitly (e.g. "Friday, think hard about X").

Graceful degradation:
  - If only one model is available, returns its answer directly.
  - If both models are the same object (single-model deployments), runs
    two sequential passes at different temperatures instead.
  - If the two answers are identical, skip the synthesis pass.
"""
from __future__ import annotations

import threading
from typing import Optional

from core.logger import logger
from core.model_output import strip_model_artifacts

_SYNTH_SYSTEM = (
    "Two assistants answered the same question independently. "
    "Combine them into a single, accurate, concise answer. "
    "Do not reference 'Answer 1' or 'Answer 2' in your output."
)


def _call_llm(
    llm,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
) -> str:
    """Single LLM call; returns stripped text or empty string on failure."""
    try:
        if hasattr(llm, "create_chat_completion"):
            result = llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            text = result["choices"][0]["message"]["content"]
        else:
            text = llm(
                messages[-1]["content"],
                max_tokens=max_tokens,
                temperature=temperature,
            )["choices"][0]["text"]
        return strip_model_artifacts(text.strip())
    except Exception as exc:
        logger.error("[moa] inference error: %s", exc)
        return ""


class MixtureOfAgents:
    """Parallel multi-model synthesis.

    Typical usage:
        moa = MixtureOfAgents(app.router)
        answer = moa.run("If I have 47 apples and give 3.14 per person, how many people?")
    """

    def __init__(self, router) -> None:
        self._router = router

    def run(
        self,
        query: str,
        messages: Optional[list[dict]] = None,
        max_tokens: int = 512,
    ) -> str:
        """Run MoA on query. Falls back gracefully when tool model is unavailable."""
        chat_llm = self._router.get_llm()
        if chat_llm is None:
            return "My language model isn't available right now."

        tool_llm = self._router.get_tool_llm()
        if messages is None:
            messages = [{"role": "user", "content": query}]

        # Single-model fallback: tool model unavailable or same object
        if tool_llm is None or tool_llm is chat_llm:
            logger.debug("[moa] single-model mode — no distinct tool model")
            return self._two_temperature_pass(chat_llm, messages, max_tokens)

        # True two-model parallel pass
        return self._parallel_pass(chat_llm, tool_llm, messages, max_tokens)

    def _two_temperature_pass(
        self, llm, messages: list[dict], max_tokens: int
    ) -> str:
        """When only one model is available, run at two temperatures and merge."""
        results: dict[str, str] = {}

        def _low():
            results["low"] = _call_llm(llm, messages, max_tokens, temperature=0.3)

        def _high():
            results["high"] = _call_llm(llm, messages, max_tokens, temperature=0.8)

        chat_lock = getattr(self._router, "chat_inference_lock", None)

        if chat_lock is not None:
            # Sequential under the lock (llama.cpp is not re-entrant)
            with chat_lock:
                _low()
            with chat_lock:
                _high()
        else:
            _low()
            _high()

        a, b = results.get("low", ""), results.get("high", "")
        if not b:
            return a
        if not a:
            return b
        if a == b:
            return a
        return self._synthesise(llm, a, b, max_tokens)

    def _parallel_pass(
        self, chat_llm, tool_llm, messages: list[dict], max_tokens: int
    ) -> str:
        results: dict[str, str] = {}
        chat_lock = getattr(self._router, "chat_inference_lock", None)
        tool_lock = getattr(self._router, "model_manager", None)
        if tool_lock is not None:
            tool_lock = tool_lock.inference_lock("tool")

        def _chat_worker():
            if chat_lock:
                with chat_lock:
                    results["chat"] = _call_llm(chat_llm, messages, max_tokens, 0.7)
            else:
                results["chat"] = _call_llm(chat_llm, messages, max_tokens, 0.7)

        def _tool_worker():
            if tool_lock:
                with tool_lock:
                    results["tool"] = _call_llm(tool_llm, messages, max_tokens, 0.4)
            else:
                results["tool"] = _call_llm(tool_llm, messages, max_tokens, 0.4)

        t1 = threading.Thread(target=_chat_worker, daemon=True)
        t2 = threading.Thread(target=_tool_worker, daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=90)
        t2.join(timeout=90)

        chat_ans = results.get("chat", "")
        tool_ans = results.get("tool", "")

        if not chat_ans and not tool_ans:
            return "I couldn't generate a response."
        if not tool_ans:
            return chat_ans
        if not chat_ans:
            return tool_ans
        if chat_ans == tool_ans:
            return chat_ans
        return self._synthesise(chat_llm, chat_ans, tool_ans, max_tokens)

    def _synthesise(self, llm, answer_a: str, answer_b: str, max_tokens: int) -> str:
        synth_messages = [
            {"role": "system", "content": _SYNTH_SYSTEM},
            {
                "role": "user",
                "content": f"Answer 1:\n{answer_a}\n\nAnswer 2:\n{answer_b}",
            },
        ]
        chat_lock = getattr(self._router, "chat_inference_lock", None)
        if chat_lock:
            with chat_lock:
                result = _call_llm(llm, synth_messages, max_tokens, temperature=0.3)
        else:
            result = _call_llm(llm, synth_messages, max_tokens, temperature=0.3)
        return result or answer_a


def make_moa(router) -> MixtureOfAgents:
    """Factory: create a MixtureOfAgents bound to the given router."""
    return MixtureOfAgents(router)
