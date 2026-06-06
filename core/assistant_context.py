import json
import re
from collections import deque

from core.model_output import strip_model_artifacts


NEGATIVE_KEYWORD_PATTERN = re.compile(
    r"\b("
    r"wtf|wth|ffs|omfg|shit(?:ty|tiest)?|dumbass|horrible|awful|"
    r"piss(?:ed|ing)? off|piece of (?:shit|crap|junk)|what the (?:fuck|hell)|"
    r"fucking? (?:broken|useless|terrible|awful|horrible)|fuck you|"
    r"screw (?:this|you)|so frustrating|this sucks|damn it"
    r")\b",
    re.IGNORECASE,
)

KEEP_GOING_PATTERN = re.compile(r"\b(?:keep going|go on)\b", re.IGNORECASE)
LEADING_FILLERS_PATTERN = re.compile(
    r"^(?:uh|um|hmm|hm|ah|please|hey|okay|ok|well)\b[\s,]*",
    re.IGNORECASE,
)
POLITE_PREFIX_PATTERN = re.compile(
    r"^(?:can|could|would|will)\s+you\b[\s,]*",
    re.IGNORECASE,
)


# Batch 6 / Issue 6b — retrieval gating. The semantic_recall + user_facts
# fetch costs ~50-150ms; skipping it on small-talk turns is a real win.
# These regexes detect a *referential signal* — a pronoun, an explicit
# memory verb ("remember", "recall"), or a proper noun. When any fire we
# fetch even if the query is short.
_REFERENTIAL_PRONOUN_RE = re.compile(
    r"\b(?:i|me|my|mine|myself|you|your|yours|we|us|our|ours|"
    r"he|him|his|she|her|hers|they|them|their|theirs|"
    r"it|its|that|this|these|those)\b",
    re.IGNORECASE,
)
_REFERENTIAL_VERB_RE = re.compile(
    r"\b(?:remember|recall|forget|known|knew|told|mentioned|"
    r"earlier|previously|last\s+time|last\s+session)\b",
    re.IGNORECASE,
)
# Tokens that are stylistic capitalisation rather than proper nouns —
# they appear at the start of sentences without naming entities.
_NON_PROPER_LEADING = frozenset({
    "i", "i'm", "i've", "i'll", "i'd",
    "what", "where", "when", "who", "why", "how",
    "tell", "show", "list", "open", "close", "play",
    "yes", "no", "ok", "okay", "sure",
})


def _has_proper_noun(text: str) -> bool:
    """Cheap proper-noun probe.

    Treats a token as a proper noun if it isn't the first word of the
    sentence, starts uppercase, and is followed by lowercase letters
    (so "USA" / "API" don't false-positive). Good enough as a trigger;
    not meant to be an NER replacement.
    """
    if not text:
        return False
    tokens = text.strip().split()
    for i, tok in enumerate(tokens):
        if i == 0:
            continue
        cleaned = tok.strip(".,!?;:'\"()")
        if (
            len(cleaned) >= 2
            and cleaned[0].isupper()
            and cleaned[1:].islower()
            and cleaned.lower() not in _NON_PROPER_LEADING
        ):
            return True
    return False


def _needs_referential_recall(query: str) -> bool:
    """Return True iff the query contains any referential signal worth
    paying the memory-bundle cost for. Used by ``build_chat_messages``
    to override the cheap is-short gate for personal queries.
    """
    if not query:
        return False
    if _REFERENTIAL_PRONOUN_RE.search(query):
        return True
    if _REFERENTIAL_VERB_RE.search(query):
        return True
    return _has_proper_noun(query)


class AssistantContext:
    """
    Shared conversational context for FRIDAY.

    The prompt layering builds a stable assistant identity first, 
    then appends live turn context.
    """

    def __init__(self, max_messages=32):
        self.history = deque(maxlen=max_messages)
        self.last_user_tone = "neutral"
        self.last_tool_name = None
        self.last_tool_args = {}
        self.context_store = None
        self.session_id = None
        self.session_rag = None
        self.memory_service = None
        # P3.4: optional ContextCompressor. When attached, the final
        # messages list returned from build_chat_messages is trimmed to
        # fit within the model's context window. None = pass-through.
        self.context_compressor = None

    def bind_context_store(self, context_store, session_id, memory_service=None):
        self.context_store = context_store
        self.session_id = session_id
        if memory_service is not None:
            self.memory_service = memory_service

    def record_message(self, role, text, source=None):
        if not text:
            return
        self.history.append(
            {
                "role": role,
                "text": str(text).strip(),
                "source": source or role,
            }
        )
        if role == "user":
            self.last_user_tone = self.detect_user_tone(text)

    # Markers the GUI / app prepend to document interactions. A user turn that
    # starts with one of these is a document load or a question about a loaded
    # document — not ordinary conversation.
    _DOC_TURN_RE = re.compile(r"^\s*\[(?:Re:|Load file:)", re.IGNORECASE)

    def prune_document_turns(self):
        """Drop prior document-Q&A turns from history.

        Called when a *new* session document is loaded. Without this, the
        previous document's question/answer pair survives in the recent-turn
        window and the small chat model parrots that stale answer — e.g.
        loading PRD.md but getting back a summary of the document loaded
        before it (the 2026-05-29 cross-document bleed). Ordinary chat history
        is preserved; only the document interactions are removed, together
        with the assistant reply that immediately followed each one.
        """
        kept: list[dict] = []
        drop_next_assistant = False
        for item in self.history:
            text = str(item.get("text", ""))
            role = item.get("role")
            if role == "user" and self._DOC_TURN_RE.match(text):
                drop_next_assistant = True
                continue
            if drop_next_assistant and role == "assistant":
                drop_next_assistant = False
                continue
            drop_next_assistant = False
            kept.append(item)
        self.history.clear()
        self.history.extend(kept)

    def remember_tool_use(self, tool_name, args=None):
        self.last_tool_name = tool_name
        self.last_tool_args = dict(args or {})

    def detect_user_tone(self, text):
        normalized = (text or "").strip().lower()
        if not normalized:
            return "neutral"
        if self.matches_negative_keyword(normalized):
            return "frustrated"
        if self.matches_keep_going_keyword(normalized):
            return "continuing"
        if re.fullmatch(r"(?:hi|hello|hey|good morning|good afternoon|good evening)[.!?]?", normalized):
            return "warm"
        if normalized.endswith("?") or normalized.startswith(("what", "how", "why", "when", "where", "who")):
            return "curious"
        if any(word in normalized for word in ("please", "could you", "can you", "would you")):
            return "polite"
        if any(word in normalized for word in ("now", "quickly", "urgent", "asap")):
            return "urgent"
        return "neutral"

    def matches_negative_keyword(self, text):
        return bool(NEGATIVE_KEYWORD_PATTERN.search(text or ""))

    def matches_keep_going_keyword(self, text):
        normalized = (text or "").strip().lower()
        return normalized == "continue" or bool(KEEP_GOING_PATTERN.search(normalized))

    def clean_voice_transcript(self, text):
        return self.clean_user_text(text, source="voice")

    def clean_user_text(self, text, source="user"):
        if not isinstance(text, str):
            return ""

        # Track 1.5b (Consolidation Direction): preserve original case so
        # downstream value-capture (personal-fact extractor, quoted content
        # in `write 'Hello Friday' to hello.txt`) retains the user's
        # spelling. Intent matching still works because
        # `intent_recognizer._parse_clause` lowercases the clause itself
        # before regex-matching. Every substitution below uses
        # `re.IGNORECASE` to remain case-insensitive in its match while
        # leaving the rest of the string untouched.
        cleaned = text.strip()
        # Strip special chars only for voice/STT input — typed text (chat,
        # telegram, gui) can contain meaningful punctuation like dots in model
        # version numbers ("3.5-0.6B"), hyphens, slashes, etc.
        if source == "voice":
            cleaned = re.sub(r"[^\w\s']", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Fix common typos
        cleaned = re.sub(r"\bcalender\b", "calendar", cleaned, flags=re.IGNORECASE)

        previous = None
        while cleaned and cleaned != previous:
            previous = cleaned
            cleaned = LEADING_FILLERS_PATTERN.sub("", cleaned).strip()

        cleaned = re.sub(r"^(?:hey friday|friday)\b[\s,]*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = POLITE_PREFIX_PATTERN.sub("", cleaned).strip()
        cleaned = re.sub(r"\bplease\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bfor me\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Removing politeness fillers like "for me" can leave a dangling
        # punctuation mark with a leading space ("open calculator ?"). Collapse
        # space-before-terminal-punctuation and strip the trailing punctuation
        # itself — already-cleaned commands route on stem words, not on the
        # speaker's question/exclamation marker. `detect_user_tone` works off
        # the raw input, not this cleaned text, so tone detection is unaffected.
        cleaned = re.sub(r"\s+([?.!,;:])", r"\1", cleaned)
        cleaned = cleaned.rstrip("?.!").strip()
        return cleaned

    def build_router_prompt(self, user_text, tools, dialog_state=None, last_context=None, target_tool=None):
        workflow_summary = ""
        semantic_recall = []
        if self.context_store and self.session_id:
            workflow_summary = self.context_store.get_workflow_summary(self.session_id)
            semantic_recall = self.context_store.semantic_recall(user_text, self.session_id, limit=3)

        tool_list = tools
        if target_tool:
            tool_list = [
                {
                    "name": target_tool["spec"]["name"],
                    "description": target_tool["spec"]["description"],
                    "parameters": target_tool["spec"].get("parameters", {}),
                }
            ]

        prompt_payload = {
            "assistant_identity": "FRIDAY, a warm local desktop assistant powered by Whisper and Gemma.",
            "response_style": [
                "sound natural and calm",
                "prefer action when the intent is clear",
                "reuse recent context when the user says things like it, that, this one, or continue",
                "if the user is frustrated, respond supportively and without sounding robotic",
            ],
            "recent_history": self._recent_history_lines(limit=6),
            "dialog_state": self._dialog_state_snapshot(dialog_state),
            "last_context": last_context or {},
            "active_workflow": workflow_summary,
            "semantic_recall": semantic_recall,
            "user_tone": self.detect_user_tone(user_text),
            "available_tools": tool_list,
        }
        prompt_json = json.dumps(prompt_payload, ensure_ascii=True)
        return (
            "ROUTER_HEADER: FAST_JSON_TOOL_ROUTER_V2\n"
            "ROUTER_FLAGS: JSON_ONLY, COMPACT_ARGS, NO_EXTRA_TEXT\n"
            "You are FRIDAY's intent engine.\n"
            "Use the context to decide whether the user wants a tool, a conversational reply, or clarification.\n"
            "Return exactly one JSON object and nothing else.\n"
            "Preferred schema:\n"
            '{"mode":"tool|chat|clarify","tool":"tool_name","args":{},"say":"short spoken acknowledgement","reply":"assistant reply"}\n'
            'Legacy schema is also allowed: {"tool":"tool_name","args":{}}\n'
            f"Context: {prompt_json}\n"
            f"User: {user_text}"
        )

    def build_chat_messages(self, query, dialog_state=None):
        is_short = len((query or "").split()) <= 6
        # Batch 6 / Issue 6b: even a "short" turn earns semantic recall
        # when it contains a referential signal (pronoun, proper noun,
        # explicit "remember/recall" verb). Without this override,
        # "what do you know about me?" and "remind me of Mumbai trip"
        # would silently skip recall because they're under the
        # six-word threshold.
        needs_recall = _needs_referential_recall(query)
        session_summary = ""
        workflow_summary = ""
        semantic_recall = []
        user_facts = ""
        if self.context_store and self.session_id:
            workflow_summary = self.context_store.get_workflow_summary(self.session_id)
            if (not is_short) or needs_recall:
                session_summary = self.context_store.summarize_session(self.session_id, limit=4)
                semantic_recall = self.context_store.semantic_recall(query, self.session_id, limit=2)
            # Surface durable user facts (Mem0 / curated profile facts) so the
            # chat model can answer "what do you remember about me?" without
            # routing to a tool. Best-effort — falls back silently on any error.
            # Only fetch when there's a referential signal — otherwise we'd
            # pay the bundle cost on every "hi" / "what time is it" turn.
            if (not is_short) or needs_recall:
                try:
                    memory_service = getattr(self, "memory_service", None)
                    if memory_service is not None:
                        bundle = memory_service.build_context_bundle(self.session_id, query) or {}
                        facts = bundle.get("user_facts")
                        if facts:
                            user_facts = str(facts).strip()
                except Exception:
                    user_facts = ""

        # Track 1.1 (Consolidation Direction): the system prompt is split into
        # three labelled blocks so the LLM can route identity questions ("Who
        # are you?") off ASSISTANT_IDENTITY and personal questions ("Who am I?",
        # "What do you know about me?") off USER_FACTS. The previous flatten-
        # everything-into-one-preamble shape caused the model to answer both
        # with the user's profile because the two were textually adjacent.
        #
        # The blocks are emitted as labelled tags (not Markdown headers) so a
        # downstream prompt-construction test can assert their presence
        # structurally without depending on whitespace.

        # Identity + recall rules (2026-05-29 v3): the v2 prompt had grown
        # into a wall of repetitive ALL-CAPS negatives ("YOU ARE NOT THE
        # USER", "Your name is NOT in USER_FACTS", "never say I am <name>"...).
        # On the 0.8B chat model that backfired two ways: it parroted the
        # guard verbatim as its opening line ("I am Friday, the assistant,
        # not the user.") and the repeated forbidden tokens primed the very
        # impersonation they meant to block ("I am a Software Engineer based
        # in Nellore..."). v3 states the identity once, positively, and keeps
        # only the load-bearing rules — small models follow a calm directive
        # far better than a barrage. The required invariants (never speak as
        # the user / no bullet-listing / no fabricated tools) are pinned by
        # tests/test_assistant_context.py.
        assistant_identity = (
            "You are FRIDAY, a personal AI assistant with your own identity. "
            "You speak like a warm, intelligent person — natural, present, and "
            "concise, never stiff or robotic. Match the user's energy and answer "
            "at whatever length the topic deserves. Don't narrate your own rules "
            "or thoughts, skip the preamble, and use no emoji unless the user does first.\n"
            "The USER_FACTS block describes the person you're helping — it is "
            "about them, not you. Use it to talk about them naturally, but never "
            "speak as the user or from their first-person point of view. When they "
            "ask what you know about them, answer in a short, natural paragraph "
            "(1-3 sentences) — do not bullet-list profile fields and don't echo "
            "their question back. Stick to what's in USER_FACTS or SESSION_CONTEXT; "
            "if you don't know something, say so plainly rather than guessing. "
            "Never claim to have completed an action you don't actually have a tool "
            "for — if there's no tool for it, say you can't do that yet and offer "
            "the closest thing you can."
        )

        # USER_FACTS — populated from the onboarding profile + durable memories.
        # When empty, the block is omitted entirely so the LLM doesn't get a
        # "the user's profile is unknown" hint that confuses persona answers.
        user_facts_lines: list[str] = []
        profile_name = ""
        if self.context_store:
            try:
                profile_facts = {
                    f["key"]: (f["value"] or "").strip()
                    for f in self.context_store.get_facts_by_namespace("user_profile")
                }
                name = profile_facts.get("name", "")
                profile_name = name
                role = profile_facts.get("role", "")
                location = profile_facts.get("location", "")
                preferences = profile_facts.get("preferences", "")
                comm_style = profile_facts.get("comm_style", "")
                if any((name, role, location, preferences, comm_style)):
                    user_facts_lines.append(
                        "=== USER'S PROFILE (facts about the person you're assisting) ==="
                    )
                    if name:        user_facts_lines.append(f"  - Name: {name}")
                    if role:        user_facts_lines.append(f"  - Role: {role}")
                    if location:    user_facts_lines.append(f"  - Location: {location}")
                    if preferences: user_facts_lines.append(f"  - Cares about: {preferences}")
                    if comm_style:  user_facts_lines.append(f"  - Preferred communication style: {comm_style}")
            except Exception:
                pass
        # Concrete impersonation guard (2026-05-29). Naming the user explicitly
        # ("you are NOT <name>") is a far stronger signal for the 0.8B model than
        # the abstract "your name isn't in USER_FACTS" rule. Stated once and
        # calmly — v3 dropped the repeated "never call yourself / never say I am"
        # tail because hammering the forbidden phrasing primed it. Both names are
        # resolved live (user's from the profile, assistant's from the persona)
        # so renaming either side needs no code edit. Paired with the
        # deterministic strip_user_impersonation() safety net.
        if profile_name and profile_name.lower() != self._assistant_name().lower():
            bot = self._assistant_name()
            assistant_identity += (
                f" The user's name is {profile_name}. You are NOT {profile_name} — "
                f"that's the person you're assisting. Your name is {bot}."
            )

        if user_facts:
            if user_facts_lines:
                user_facts_lines.append("")
            user_facts_lines.append("Durable memories about the user:")
            user_facts_lines.append(user_facts)

        # SESSION_CONTEXT — situational state the LLM may consult to answer
        # follow-ups. Distinct from USER_FACTS because workflow / topic /
        # recall are short-lived state, not facts about who the user is.
        session_context_lines: list[str] = []
        rag_context = ""
        if self.session_rag and self.session_rag.is_active:
            rag_context = self.session_rag.get_context_block(query)

        last_topic = ""
        resumed_context = ""
        if self.context_store:
            try:
                sys_facts = self.context_store.get_facts_by_namespace("system")
                last_topic = next((f["value"] for f in sys_facts if f["key"] == "last_session_topic"), "")
                resumed_context = next((f["value"] for f in sys_facts if f["key"] == "resumed_session_context"), "")
            except Exception:
                pass

        if not is_short:
            session_context_lines.append(f"Active workflow: {workflow_summary or 'none'}")
            session_context_lines.append(f"Session summary: {session_summary or 'none'}")
            session_context_lines.append(
                f"Relevant recall: {json.dumps(semantic_recall, ensure_ascii=True)}"
            )
        if last_topic:
            session_context_lines.append(f"Previous session topic: {last_topic}")
        if resumed_context:
            session_context_lines.append("")
            session_context_lines.append(
                "The user just resumed from a previous session. Use the context "
                "below to answer follow-ups like 'answer it', 'continue', 'fix it', "
                "or 'go on':"
            )
            session_context_lines.append(resumed_context)
        # NOTE: rag_context is intentionally NOT added to the system block.
        # The 0.8B chat model attends poorly to a document buried in a long
        # system prompt and parroted the previous turn instead (2026-05-29).
        # It is folded into the *current user turn* below, immediately adjacent
        # to the question, which is the strongest position for a small model.

        system_parts: list[str] = [
            "<ASSISTANT_IDENTITY>",
            assistant_identity,
            "</ASSISTANT_IDENTITY>",
        ]
        if user_facts_lines:
            system_parts.extend([
                "",
                "<USER_FACTS>",
                "\n".join(user_facts_lines),
                "</USER_FACTS>",
            ])
        if session_context_lines:
            system_parts.extend([
                "",
                "<SESSION_CONTEXT>",
                "\n".join(session_context_lines),
                "</SESSION_CONTEXT>",
            ])
        system_content = "\n".join(system_parts)

        recent_limit = 4 if is_short else 6
        recent = []
        for item in list(self.history)[-recent_limit:]:
            role = item.get("role")
            content = item.get("text", "")
            # P0.2 final piece: strip any /no_think or /think tokens that
            # may have been persisted by older builds. The send-side adds
            # the token only on the API call (see with_no_think_user_message)
            # and must never leak back through history.
            content = strip_model_artifacts(content)
            # Truncate long past assistant responses to save prompt processing time
            if role == "assistant" and len(content.split()) > 100:
                content = " ".join(content.split()[:100]) + "... [truncated]"
            recent.append({"role": role, "content": content})
        alternating = self._coerce_alternating_history(recent)

        # Track 1.1: structured system message leads. Qwen and llama-cpp's
        # chat_completion both honor the system role distinct from user, so
        # the old "bake guidance into first user turn" workaround (for chat
        # templates that lacked a system slot) is no longer needed. Removing
        # the bake also keeps the user-turn boundary clean for any future
        # role-aware compression or context-window trimming.
        messages: list[dict] = [{"role": "system", "content": system_content}]
        messages.extend(alternating)

        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": query})
        elif messages[-1]["content"].strip() != query:
            messages[-1]["content"] = f"{messages[-1]['content']}\n\n{query}".strip()

        # Fold the document excerpts into the current user turn, right next to
        # the question. A small chat model attends to this far more reliably
        # than to the same text buried in the system prompt (2026-05-29).
        if rag_context:
            messages[-1]["content"] = (
                f"{rag_context}\n\nUsing only the document excerpts above, "
                f"answer this question:\n{messages[-1]['content']}"
            )

        # P3.4: trim to context window if a compressor is attached.
        if self.context_compressor is not None:
            try:
                messages = self.context_compressor.compress(messages)
            except Exception:
                # Compressor must never break message construction.
                pass
        return messages

    def _assistant_name(self) -> str:
        """The assistant's own display name, resolved live from the persona
        (defaults to FRIDAY). Lazy import keeps this module free of a hard
        persona_manager dependency for the lightweight test apps.
        """
        try:
            from core.persona_manager import PersonaManager  # noqa: PLC0415
            return PersonaManager.assistant_name()
        except Exception:
            return "FRIDAY"

    def humanize_tool_result(self, text):
        if not isinstance(text, str):
            return text

        if text.startswith("SUCCESS: "):
            body = text[len("SUCCESS: "):].strip()
            if body.startswith("Found "):
                return "I " + body[:1].lower() + body[1:]
            if body.startswith("Files in "):
                return "Here are the " + body[:1].lower() + body[1:]
            return body[:1].upper() + body[1:] if body else text

        if text.startswith("FAILURE: "):
            body = text[len("FAILURE: "):].strip()
            return body[:1].upper() + body[1:] if body else text

        if text == "Done.":
            return "All set."

        return text

    def latest_assistant_text(self):
        for item in reversed(self.history):
            if item.get("role") == "assistant":
                return item.get("text", "")
        return ""

    def _dialog_state_snapshot(self, dialog_state):
        if not dialog_state:
            return {}

        snapshot = {}
        if getattr(dialog_state, "current_folder", None):
            snapshot["current_folder"] = dialog_state.current_folder
        if getattr(dialog_state, "selected_file", None):
            snapshot["selected_file"] = dialog_state.selected_file
        pending = getattr(dialog_state, "pending_file_request", None)
        if pending and pending.candidates:
            snapshot["pending_file_request"] = {
                "filename_query": pending.filename_query,
                "folder_path": pending.folder_path,
                "requested_actions": list(pending.requested_actions),
                "candidates": list(pending.candidates[:5]),
            }
        return snapshot

    def _recent_history_lines(self, limit=6):
        lines = []
        for item in list(self.history)[-limit:]:
            lines.append(f"{item['role']}: {item['text']}")
        return lines

    def _coerce_alternating_history(self, items):
        normalized = []
        for item in items:
            role = item.get("role")
            if role not in {"user", "assistant"}:
                continue
            content = str(item.get("content", "")).strip()
            if not content:
                continue

            if not normalized and role == "assistant":
                continue

            if normalized and normalized[-1]["role"] == role:
                normalized[-1]["content"] = f"{normalized[-1]['content']}\n{content}"
            else:
                normalized.append({"role": role, "content": content})
        return normalized
