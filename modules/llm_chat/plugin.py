import re

from core.plugin_manager import FridayPlugin
from core.logger import logger
from core.model_output import (
    strip_model_artifacts,
    strip_user_impersonation,
    with_no_think_user_message,
    math_to_speech,
)
from core.prompt_builder import build_default_messages

class LLMChatPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "LLMChat"
        self.on_load()

    def on_load(self):
        # This is the catch-all tool — Gemma routes here when no specific tool matches
        self.app.register_capability({
            "name": "llm_chat",
            "description": (
                "Answer a general question, have a conversation, or handle any request "
                "that doesn't fit a specific tool. Use this as the fallback for open-ended queries."
            ),
            "parameters": {
                "query": "string – the user's question or message"
            }
        }, self.handle_chat, metadata={
            "connectivity": "local",
            "latency_class": "generative",
            "permission_mode": "always_ok",
            "side_effect_level": "read",
            "streaming": True,
        })

        logger.info("LLMChatPlugin loaded.")

    def handle_chat(self, raw_text, args):
        query = args.get("query", raw_text).strip()
        if not query:
            return "I didn't catch that. Could you rephrase?"

        # ── Pre-flight reroute (2026-05-24 Step 4b) ───────────────────
        # If the query has a high-confidence cosine match against the
        # tool catalog, bail out of chat and dispatch the tool instead.
        # This catches phrasings that IntentRecognizer regex missed AND
        # the Qwen-4B planner mis-scored — small models often default to
        # chat when uncertain, but a 0.62+ cosine hit on a curated
        # `example_phrases` list is a stronger signal than the planner's
        # low-confidence output.
        #
        # Skip it entirely when a document is loaded in the session RAG:
        # IntentRecognizer deliberately routes doc questions here so the
        # injected excerpts can answer them, and a preflight reroute would
        # bounce e.g. "what is there in the document?" back to read_file
        # (the 2026-05-29 bug we are fixing).
        session_rag = getattr(self.app, "session_rag", None)
        if not (session_rag is not None and getattr(session_rag, "is_active", False)):
            rerouted = self._preflight_reroute(query, raw_text)
            if rerouted is not None:
                return rerouted

        llm = self.app.router.get_llm()
        if llm is None:
            return "My language model isn't loaded right now. Please check the models directory."

        messages = with_no_think_user_message(self._build_messages(query))
        # Batch 6 / Issue 5c: budget the prompt to the model's context
        # window so a long session can't trigger the "Requested tokens
        # (N) exceed context window of M" crash we hit in the wild.
        messages = self._fit_to_context(llm, messages)

        logger.debug(f"[LLMChat] Sending chat prompt for: '{query}'")
        try:
            # Hold the chat-inference lock so concurrent users of the chat
            # model (e.g. the research agent's background summarizer) don't
            # crash llama.cpp.
            with self.app.router.chat_inference_lock:
                answer = self._generate_reply(llm, messages)

            logger.info(f"[LLMChat] Response: {answer[:80]}...")
            return answer

        except Exception as e:
            logger.error(f"[LLMChat] Inference error: {e}")
            return "I ran into an issue generating a response. Please try again."

    def _chat_max_tokens(self) -> int:
        config = getattr(self.app, "config", None)
        if config and hasattr(config, "get"):
            return int(config.get("routing.chat_max_tokens", 512) or 512)
        return 512

    def _chat_n_ctx(self) -> int:
        """Read the chat model's configured context window (n_ctx)."""
        router = getattr(self.app, "router", None)
        model_manager = getattr(router, "model_manager", None) if router else None
        if model_manager and hasattr(model_manager, "profile"):
            try:
                profile = model_manager.profile("chat")
                if profile and getattr(profile, "n_ctx", 0):
                    return int(profile.n_ctx)
            except Exception:
                pass
        config = getattr(self.app, "config", None)
        if config and hasattr(config, "get"):
            return int(config.get("models.chat.n_ctx", 4096) or 4096)
        return 4096

    def _fit_to_context(self, llm, messages):
        """Drop oldest messages so the prompt + reserved response tokens
        stay under the model's context window. See ``core.context_window``.
        """
        try:
            from core.context_window import fit_messages  # noqa: PLC0415
        except Exception as exc:
            logger.debug("[LLMChat] context-window helper unavailable: %s", exc)
            return messages
        n_ctx = self._chat_n_ctx()
        response_budget = self._chat_max_tokens()
        return fit_messages(llm, messages, n_ctx, response_budget=response_budget)

    def _user_name(self) -> str:
        """The user's profile name, if known — used to scrub any reply where
        the model drifts into the user's identity (see strip_user_impersonation).
        """
        store = getattr(self.app, "context_store", None)
        if store is None or not hasattr(store, "get_facts_by_namespace"):
            return ""
        try:
            for fact in store.get_facts_by_namespace("user_profile"):
                if fact.get("key") == "name":
                    return (fact.get("value") or "").strip()
        except Exception:
            return ""
        return ""

    def _assistant_name(self) -> str:
        """The assistant's own display name, resolved live from the persona
        (defaults to FRIDAY) — the replacement target when scrubbing an
        impersonation. Resolved dynamically so renaming the persona needs no
        code change.
        """
        try:
            from core.persona_manager import PersonaManager  # noqa: PLC0415
            return PersonaManager.assistant_name()
        except Exception:
            return "FRIDAY"

    def _generate_reply(self, llm, messages):
        max_tokens = self._chat_max_tokens()
        user_name = self._user_name()
        bot_name = self._assistant_name()
        if not hasattr(llm, "create_chat_completion"):
            res = llm(messages[-1]["content"], max_tokens=max_tokens, temperature=0.7, top_p=0.9)
            return strip_user_impersonation(
                strip_model_artifacts(res["choices"][0]["text"]), user_name, bot_name
            )

        stream = llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
            top_p=0.9,
            stream=True,
        )
        if isinstance(stream, dict):
            return strip_user_impersonation(
                strip_model_artifacts(stream["choices"][0]["message"]["content"]),
                user_name, bot_name,
            )

        parts = []
        visible_text = ""
        sentence_buffer = ""
        first_token_seen = False
        turn = None
        cancel_ev = getattr(getattr(self, "app", None), "_current_cancel_event", None)
        for chunk in stream:
            if cancel_ev and cancel_ev.is_set():
                break
            delta = chunk["choices"][0].get("delta", {})
            content = delta.get("content")
            if not content:
                continue
            if not first_token_seen:
                first_token_seen = True
                feedback = getattr(self.app, "turn_feedback", None)
                turn = getattr(self.app, "_active_turn_record", None)
                if feedback and turn:
                    feedback.emit_llm_first_token(turn)
            parts.append(content)
            cleaned = strip_model_artifacts("".join(parts))
            if cleaned == visible_text:
                continue
            if cleaned.startswith(visible_text):
                new_visible = cleaned[len(visible_text):]
            else:
                new_visible = cleaned
                sentence_buffer = ""
            visible_text = cleaned
            # Publish chunk for live GUI streaming
            self.app.event_bus.publish("llm_chunk", {
                "text": cleaned,
                "turn_id": getattr(turn, "turn_id", "") if turn else "",
            })
            sentence_buffer += new_visible
            spoken_parts = re.split(r"(?<=[.!?])\s+", sentence_buffer)
            if len(spoken_parts) > 1:
                spoken_text = " ".join(part for part in spoken_parts[:-1] if part).strip()
                # Scrub impersonation before TTS so the user never *hears*
                # "named Luffy" — a post-hoc fix on the returned string would
                # arrive too late for the already-spoken sentence.
                spoken_text = strip_user_impersonation(spoken_text, user_name, bot_name)
                if spoken_text:
                    self.app.event_bus.publish("voice_response", math_to_speech(spoken_text))
                    self.app.routing_state.mark_voice_spoken()
                sentence_buffer = spoken_parts[-1]

        if sentence_buffer.strip():
            tail = strip_user_impersonation(sentence_buffer.strip(), user_name, bot_name)
            self.app.event_bus.publish("voice_response", math_to_speech(tail))
            self.app.routing_state.mark_voice_spoken()

        return strip_user_impersonation(
            self._deloop(strip_model_artifacts("".join(parts))), user_name, bot_name
        )

    def _deloop(self, text: str) -> str:
        """Truncate runaway repetition loops (P1.5).

        If any 200-char substring appears ≥3 times, cut after the 2nd
        occurrence and append a truncation notice.
        """
        if len(text) < 600:
            return text
        window = 200
        for start in range(0, len(text) - window):
            chunk = text[start:start + window]
            if text.count(chunk) >= 3:
                second_end = text.find(chunk, text.find(chunk) + window) + window
                return text[:second_end] + " [response truncated due to loop]"
        return text

    def _preflight_reroute(self, query: str, raw_text: str):
        """Return a tool's output if the embedding router finds a strong
        match; otherwise return None and let chat generation proceed.

        Threshold of 0.72 is deliberately tighter than the regular
        EmbeddingRouter's 0.62 dispatch threshold — we're already in the
        chat fallback, so the cost of a false reroute (calling the wrong
        tool) is higher than a false negative (a generic chat reply).
        Logs every preflight decision (route, score, ms) so we can tune.
        """
        router = getattr(self.app, "router", None)
        embed_router = getattr(router, "embedding_router", None) if router else None
        if embed_router is None or not hasattr(embed_router, "preflight_route"):
            return None
        try:
            decision = embed_router.preflight_route(query, threshold=0.72)
        except Exception as exc:
            logger.debug("[LLMChat] preflight skip: %s", exc)
            return None
        if not decision:
            return None
        tool_name = decision["tool"]
        score = decision["score"]
        executor = getattr(self.app, "capability_executor", None)
        if executor is None:
            logger.debug("[LLMChat] preflight skip: no capability_executor")
            return None
        logger.info(
            "[LLMChat] preflight reroute → %s (cosine=%.3f) for query=%r",
            tool_name, score, query[:80],
        )
        try:
            result = executor.execute(tool_name, raw_text, {})
        except Exception as exc:
            logger.warning("[LLMChat] preflight executor crashed: %s", exc)
            return None
        if not getattr(result, "ok", False):
            err = getattr(result, "error", "") or ""
            # Don't bury a tool failure — let the user see it.
            logger.info("[LLMChat] preflight tool %s failed: %s", tool_name, err[:120])
            return err or f"{tool_name} failed."
        # Adaptive Intent Phase 4 capture-at-source: this is the high-value
        # signal — a paraphrase that only the embedding router (not regex)
        # could route. Accrue a hit so repeated use promotes it to a cheap,
        # deterministic learned dispatch next time.
        self._note_learned_hit(query, tool_name)
        output = getattr(result, "output", "") or ""
        return str(output) if output else None

    def _note_learned_hit(self, query: str, tool_name: str) -> None:
        store = getattr(self.app, "intent_learning_store", None)
        if store is None or not hasattr(store, "note_hit") or not tool_name:
            return
        cfg = getattr(self.app, "config", None)
        if cfg is not None and hasattr(cfg, "get") and not cfg.get("routing.learning_enabled", True):
            return
        try:
            store.note_hit(query, tool_name)
        except Exception:
            logger.debug("[LLMChat] learned-hit capture skipped", exc_info=True)

    def _build_messages(self, new_query):
        assistant_context = getattr(self.app, "assistant_context", None)
        if assistant_context:
            messages = assistant_context.build_chat_messages(
                new_query,
                dialog_state=getattr(self.app, "dialog_state", None),
            )
            if messages:
                return messages
        return build_default_messages(new_query)


def setup(app):
    return LLMChatPlugin(app)
