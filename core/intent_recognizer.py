import re
import os

from core.dialog_state import PendingGoalSelection
from core.workflows.disambiguation import (
    looks_like_selection as _pick_looks_like_selection,
    CANCEL_RE as _PICK_CANCEL_RE,
)

# Patterns that unambiguously mark a knowledge/explanation question.
# When matched, plan() short-circuits to [] so the turn goes to the LLM.
_KNOWLEDGE_Q_RE = re.compile(
    r"^(?:"
    r"(?:explain|describe|define|elaborate(?:\s+on)?|clarify|discuss|outline|summarise|summarize\s+(?:what|how|why|the))\b"
    # Don't poach tool invocations: "describe this image", "explain this meme"
    # are handled by _parse_vision_action.
    r"(?!\s+(?:this|the|my|that)\s+(?:image|picture|photo|meme|screenshot|screen|clipboard))|"
    # `compare/contrast` only fires as a knowledge question if it's NOT
    # followed (within ~4 words) by a tool-noun. Without this guard,
    # "compare these two screenshots" / "compare the last two scans"
    # would short-circuit to the LLM instead of routing to the vision /
    # security tools.
    r"(?:compare|contrast|differentiate|distinguish)\b"
    # Negative lookahead — DON'T treat as knowledge-question when
    # followed (within ~4 words) by a tool-noun (screenshots / scans /
    # files) OR by `vs|versus|with|and|from` which mark a comparative
    # research query that should route to research_topic instead.
    r"(?!(?:\s+\S+){0,4}\s+(?:screenshots?|scans?|scan\s+results?|images?|pictures?|files?)\b)"
    r"(?!(?:\s+\S+){0,6}\s+(?:vs\.?|versus|with|and|from)\s+\S+)|"
    # `analyze/analyse` only fires for knowledge — not when it's "analyze my
    # screen / clipboard / image / code / error" which belong to tools.
    r"(?:analyze|analyse)\b"
    r"(?!\s+(?:my|the|this|that)\s+(?:screen|clipboard|image|picture|screenshot|code|error|page|section))|"
    r"what\s+(?:causes?|happens?\s+(?:when|if))\b|"
    # "what is/are the [named knowledge concept]" — specific known knowledge terms
    r"what\s+(?:is|are)\s+(?:the\s+)?(?:difference|relationship|connection|effect|cause|reason|purpose|role|function|mechanism|principle|formula|equation|process|concept|theory|law|stages?|types?|kinds?|symptoms?|characteristics?|properties|advantages?|disadvantages?)\b|"
    # "what is/are the X of/in/for Y ..." — named concept with prepositional qualifier
    # e.g. "Time OF Useful Consciousness", "capital OF France", "role OF gravity IN orbit"
    r"what\s+(?:is|are|was|were)\s+(?:a\s+|an\s+|the\s+)?\w+\s+(?:of|for|in|behind|about)\s+\w+(?:\s+\w+)*\b|"
    r"how\s+(?:does|do|did|would)\b|"
    r"why\s+(?:does|do|did|is|are|was|were|would|will)\b|"
    r"can\s+you\s+(?:explain|describe|clarify|help\s+me\s+understand)\b|"
    r"(?:give\s+me|provide)\s+(?:an?\s+)?(?:overview|explanation|description|detail)\s+(?:of|about)\b|"
    r"(?:identify|list|name)\s+(?:the\s+)?(?:main|key|primary|different|various|major|important|common|types?|kinds?|stages?|phases?|effects?|causes?|symptoms?|benefits?|advantages?|disadvantages?|characteristics?|properties|principles?|equations?|laws?)\b"
    r")",
    re.IGNORECASE,
)

def _get_extract_app_names():
    try:
        from modules.system_control.app_launcher import extract_app_names  # noqa: PLC0415
        return extract_app_names
    except Exception:
        return lambda _text: []

extract_app_names = _get_extract_app_names()

# ── Session-RAG document-question detection ──────────────────────────────
# A document loaded into the in-memory session RAG (core/session_rag.py) is
# answered via chat, which injects the relevant excerpts. These patterns let
# plan() recognise "the user is asking about the loaded document" so the turn
# is routed to llm_chat instead of falling through to read_file/open_file.
# `[Re: <name>]` is the prefix the GUI prepends to the FIRST message after a
# file is attached (gui/hud.py) — a strong, unambiguous doc-question signal.
_RE_PREFIX_RE = re.compile(r"^\s*\[re:\s*[^\]]*\]\s*", re.IGNORECASE)
_DOC_NOUN_RE = re.compile(
    r"\b(?:document|doc|file|pdf|paper|report|resume|cv|article|essay|"
    r"page|content|section|chapter|attachment)\b",
    re.IGNORECASE,
)
_DOC_INTENT_RE = re.compile(
    r"\b(?:what|how|who|whom|when|where|why|which|find|explain|summari[sz]e|"
    r"tell|describe|define|list|show|give|does|do|is|are|read|about|"
    r"mention|contain|say)\b",
    re.IGNORECASE,
)
# Doc-referential phrases that point at the loaded file by pronoun even
# without a doc noun ("what does it say", "summarize this").
_DOC_VERB_PHRASE_RE = re.compile(
    r"\b(?:"
    r"what\s+does\s+(?:it|this|that)\s+say|"
    r"what'?s?\s+(?:in|inside)\s+(?:it|this|that)|"
    r"tell\s+me\s+about\s+(?:it|this|that)|"
    r"summari[sz]e\s+(?:it|this|that)|"
    r"explain\s+(?:it|this|that)|"
    r"(?:go|walk\s+me)\s+through\s+(?:it|this|that)"
    r")\b",
    re.IGNORECASE,
)

_ARTIFACT_PRONOUNS = re.compile(
    r"\b(it|that|this|the result|the output|that file|the code|the list|the summary)\b",
    re.IGNORECASE,
)
_ORDINAL_PATTERN = re.compile(
    r"\b(?:the\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)"
    r"(?:\s+(?:one|item|option|result|file))?\b",
    re.IGNORECASE,
)


class IntentRecognizer:
    def __init__(self, router):
        self.router = router

    def plan(self, text, context=None):
        # STT typo correction (Issue 8). Idempotent — safe to run again
        # when the router already normalized, but covers the path where
        # plan() is called directly (tests, capability broker shortcuts).
        from core.text_normalize import normalize_for_routing  # noqa: PLC0415
        text = normalize_for_routing(text)
        cleaned = self._clean_text(text)
        if not cleaned:
            return []
        # Session-RAG document question. Checked BEFORE the knowledge-question
        # short-circuit because phrasings like "what is there in the document?"
        # match _KNOWLEDGE_Q_RE and would otherwise return [] and fall through
        # to the lexical router, which mis-routed them to read_file ("Which
        # file would you like me to read?", 2026-05-29 log bug). When a doc is
        # loaded in the in-memory session RAG we route to chat instead, where
        # assistant_context injects the relevant excerpts.
        doc_action = self._session_rag_doc_action(cleaned)
        if doc_action is not None:
            return [doc_action]
        # Knowledge/explanation questions must never route to a tool.
        if self._is_knowledge_question(cleaned):
            return []
        # Track 1.4d (Consolidation Direction): the prior
        # `cleaned = self._resolve_references(cleaned)` step (ordinal
        # text-rewriting) has been deleted. Ordinal resolution lives in
        # `core/planning/context_resolver.py` path 2 — after intent
        # classification, the resolver rewrites the plan when the user
        # asked about an ordinal with a registered list in scope. The
        # pending-file-selection path in `_parse_pending_selection`
        # already handles the in-dialog case.

        actions = []
        seen_read_only_actions = set()
        current_context = dict(context or {})
        clauses = self._split_into_clauses(cleaned)
        for clause in clauses:
            action = self._parse_clause(clause, current_context)
            if not action:
                return []
            action_key = (action["tool"], self._hashable_args(action.get("args", {})))
            if action_key in seen_read_only_actions and not action.get("args"):
                continue
            if not action.get("args"):
                seen_read_only_actions.add(action_key)
            actions.append(action)
            current_context = {
                "tool": action["tool"],
                "domain": action.get("domain", action["tool"]),
                "args": dict(action.get("args", {})),
            }
        return actions

    def _is_knowledge_question(self, text: str) -> bool:
        """Return True for clear knowledge/explanation questions.

        These must never be routed to a deterministic tool regardless of which
        status-domain keywords (time, battery, hello, etc.) they happen to
        contain. Minimum 4 words to avoid catching very short commands.
        """
        stripped = re.sub(r"^\[.*?\]\s*", "", text.strip())
        if len(stripped.split()) < 4:
            return False
        return bool(_KNOWLEDGE_Q_RE.match(stripped))

    def _clean_text(self, text):
        text = " ".join(text.strip().split())
        text = re.sub(r"\s+", " ", text)
        return text.strip(" \t\r\n")

    def _is_session_doc_question(self, cleaned: str) -> bool:
        """True when *cleaned* is a question about a loaded session document.

        Three signals: the GUI's `[Re: <name>]` attach prefix (unambiguous),
        a doc-referential phrase ("what does it say"), or an explicit document
        noun paired with an interrogative/command word. Bare pronoun questions
        like "what time is it" are deliberately excluded so they don't get
        force-routed to the document.
        """
        low = cleaned.lower()
        if _RE_PREFIX_RE.search(low):
            return True
        if _DOC_VERB_PHRASE_RE.search(low):
            return True
        return bool(_DOC_NOUN_RE.search(low) and _DOC_INTENT_RE.search(low))

    def _session_rag_doc_action(self, cleaned: str):
        """Route a question about the loaded session document to chat.

        Returns an `llm_chat` action (so assistant_context injects the
        relevant excerpts) or None. Only fires when a document is active in
        the in-memory session RAG, so it can't poach ordinary requests.
        """
        tools = getattr(self.router, "_tools_by_name", {})
        if "llm_chat" not in tools:
            return None
        ac = getattr(self.router, "assistant_context", None)
        session_rag = getattr(ac, "session_rag", None) if ac else None
        if session_rag is None or not getattr(session_rag, "is_active", False):
            return None
        if not self._is_session_doc_question(cleaned):
            return None
        query = _RE_PREFIX_RE.sub("", cleaned).strip() or cleaned
        return {"tool": "llm_chat", "args": {"query": query}, "text": cleaned, "domain": "document"}

    # Track 1.4d (2026-05-18): `_resolve_references` deleted.
    # Three text-injection mechanisms it used to perform:
    #   1. Ordinal rewriting (`"the second one"` → `use "<value>"`) —
    #      now handled post-plan by `ContextResolver` path 2 OR by
    #      `_parse_pending_selection` when a pending file list is
    #      active. The verb-parsers don't need pre-rewriting anymore.
    #   2. Artifact-stub prefix (`[artifact:read_file (text)] `) —
    #      already deleted in Track 1.4c (zero consumers).
    #   3. Active-document prefix (`[active_document=<path>] `) —
    #      already deleted in Track 1.4c; `_parse_query_document`
    #      consults the registry directly.
    # `_ORDINAL_PATTERN` is retained because it documents the
    # canonical ordinal shape; if removed entirely, it's still
    # available at the module level for anyone who needs it.

    def _split_into_clauses(self, text):
        # Code-eval guard: `execute python: x = 5; print(x)` must stay one
        # clause; semicolons are valid Python syntax inside `evaluate_code`.
        if re.search(r"^\s*(?:evaluate|run|execute|eval)\s+(?:this\s+)?(?:python|py|code)\s*[:\s]", text, re.IGNORECASE):
            return [text.strip()]
        # `tl;dr X` is a single research request — the semicolon is part
        # of the idiom, not a clause separator.
        if re.search(r"^\s*tl;dr\b", text, re.IGNORECASE):
            return [text.strip()]

        clauses = [text]
        for splitter in (
            re.compile(r"\b(?:and then|then|also|after that|afterwards|plus)\b", re.IGNORECASE),
            re.compile(r"\s*;\s*"),
        ):
            expanded = []
            for clause in clauses:
                expanded.extend(part.strip() for part in splitter.split(clause) if part.strip())
            clauses = expanded

        expanded = []
        for clause in clauses:
            expanded.extend(self._split_on_action_and(clause))
        return [clause for clause in expanded if clause]

    def _split_on_action_and(self, clause):
        if self._is_multi_app_launch_clause(clause):
            return [clause.strip()]
        if re.search(r"\bopen\s+youtube(?:\s+music)?\b.*\band\s+play\b", clause, re.IGNORECASE):
            return [clause.strip()]
        # Don't split "crawl <URL> and find X" / "fetch <URL> and summarize" —
        # the "and …" portion is an *instruction modifier* for the URL-action,
        # not a second tool call. Without this guard the splitter produces
        # ["crawl https://…", "find ML stories"] and the second half routes
        # to search_indexed_files (the 2026-05-23 16:42 bug).
        if re.search(
            r"\b(?:crawl|scrape|spider|harvest|fetch|extract|download)\b.*https?://.*\band\b",
            clause,
            re.IGNORECASE,
        ):
            return [clause.strip()]
        # Don't split when both halves act on a shared pronoun like "it":
        # "open and read it to me" describes two actions on the same target.
        # The downstream file controller can detect both verbs in one clause.
        if re.search(
            r"\b(?:open|read|summarize|preview|show|play)\s+and\s+(?:open|read|summarize|preview|show|play)\b.*?\b(?:it|this|that|the file|to me|out loud)\b",
            clause,
            re.IGNORECASE,
        ):
            return [clause.strip()]

        lower_clause = clause.lower()
        for marker in self._action_connectors_for(lower_clause):
            idx = lower_clause.find(marker)
            while idx != -1:
                left = clause[:idx].strip(" ,")
                right = clause[idx + len(marker):].strip(" ,")
                if left and right and self._looks_like_action_start(right):
                    return self._split_on_action_and(left) + self._split_on_action_and(right)
                idx = lower_clause.find(marker, idx + len(marker))
        return [clause.strip()]

    def _action_connectors_for(self, lower_clause):
        connectors = [" and "]
        # Whisper sometimes hears "and time" as "on time". Only add " on " as
        # a connector for short status/time requests (≤8 words) — never for
        # longer sentences where "time" is part of a concept name.
        if len(lower_clause.split()) <= 8 and re.search(
            r"\b(?:system info|system information|system status|system health|system details|"
            r"current time|the time|current date|today'?s date|battery|cpu|ram|memory)\b",
            lower_clause,
        ):
            connectors.append(" on ")
        return connectors

    def _is_multi_app_launch_clause(self, clause):
        clause_lower = clause.lower()
        if not re.search(r"\b(?:open|launch|start|bring up)\b", clause_lower):
            return False
        if re.search(r"\b(?:file|folder)\b", clause_lower):
            return False
        return len(extract_app_names(clause_lower)) > 1

    def _looks_like_action_start(self, text):
        normalized = text.lower().strip()
        normalized = re.sub(r"^(?:the|my|current)\s+", "", normalized)
        if self._looks_like_short_status_fragment(normalized):
            return True
        starters = (
            "open", "launch", "start", "bring up", "take", "capture", "find", "search",
            "locate", "set", "save", "write", "append", "add", "read", "show", "list", "get", "check", "tell",
            "what", "summarize", "summary", "remind", "enable", "disable", "turn",
            "mute", "unmute", "increase", "decrease", "lower", "raise", "stop", "pause",
            "play",
        )
        return any(normalized.startswith(starter) for starter in starters)

    def _looks_like_short_status_fragment(self, normalized):
        fragments = (
            "time",
            "current time",
            "the time",
            "date",
            "today's date",
            "current date",
            "system info",
            "system information",
            "system status",
            "system health",
            "system details",
            "battery",
            "battery status",
        )
        return any(normalized == fragment or normalized.startswith(f"{fragment} ") for fragment in fragments)

    def _hashable_args(self, args):
        if not isinstance(args, dict):
            return ()
        return tuple(sorted((str(key), repr(value)) for key, value in args.items()))

    def _parse_clause(self, clause, context):
        clause_lower = clause.lower().strip()

        for parser in self._clause_parsers():
            action = parser(clause, clause_lower, context)
            if action:
                return action
        return None

    def _clause_parsers(self):
        """The ordered deterministic parser chain — the single source of truth
        for both `_parse_clause` and the intent conflict detector
        (`scripts/diagnostics/intent_eval.py`). Order is load-bearing: narrow /
        explicit parsers run before broad catch-alls (see inline notes)."""
        return (
            # Pending destructive-action confirmation must fire BEFORE any other
            # parser so "yes, wipe everything" is never mis-routed to a greeting
            # or other intent when a wipe confirmation is outstanding.
            # `_parse_pending_destructive` (the generic Phase-3 guard) runs
            # first: while ANY destructive action is armed, this turn is the
            # yes/no answer and must not be parsed as a fresh command.
            self._parse_pending_destructive,
            # A pending disambiguation pick is, like the destructive
            # confirmation above, an answer to FRIDAY's own question — route a
            # selection ("2", "the firefox one") before any fresh-command parser
            # can poach it. Unlike the destructive guard it only intercepts
            # selection-shaped utterances, so unrelated commands fall through.
            self._parse_pending_pick,
            self._parse_pending_wipe,
            self._parse_pending_selection,
            self._parse_personal_fact,
            self._parse_dictation,
            self._parse_focus_session,
            # Goals must run BEFORE email/research/launch_app so "update my
            # Friday launch goal to 75%" never gets poached by the embedding
            # router's launch_app match on the word "launch".
            self._parse_goals,
            # Email must run BEFORE _parse_research_topic: the research
            # parser's greedy "summari[sz]e (.+)" catch-all would otherwise
            # turn "summarize my emails" into a web-research run on the topic
            # "emails". _parse_email_action is narrow (requires email/mail/
            # inbox/messages nouns) so promoting it can't poach anything else.
            self._parse_email_action,
            # quick_answer (instant chat answer, no storage) must run BEFORE
            # _parse_research_topic so "quick answer on X" doesn't get pulled
            # into the heavier research pipeline.
            self._parse_quick_answer,
            self._parse_research_topic,
            # newspaper_extract must run BEFORE _parse_web_url_action so
            # "get just the article from <URL>" → newspaper_extract instead
            # of being grabbed by the generic web_extract route.
            self._parse_newspaper_extract,
            self._parse_web_url_action,
            self._parse_security,
            self._parse_google_search,
            self._parse_browser_media,
            self._parse_volume,
            self._parse_system,
            self._parse_friday_status,
            self._parse_time_date,
            self._parse_screenshot,
            # Track 6 / 6.3 (2026-05-23): environmental-awareness +
            # security parsers. Order matters — screen_lock must run
            # before _parse_help so "lock screen" never matches a help
            # query, and _parse_environment must run before
            # _parse_file_action so "find file foo.txt" doesn't get
            # captured by the broader file-search router.
            self._parse_screen_lock,
            self._parse_brightness,
            self._parse_environment,
            self._parse_vision_action,
            self._parse_query_document,
            self._parse_news_action,
            # Step 5a (2026-05-24) — the 7 ported source tools.
            # Each parser is narrow (verb + domain noun) so it never
            # poaches the generic web_search / search_file routes.
            self._parse_source_tools,
            # Step 4 (2026-05-23) — long-tail parsers for the 30+
            # capabilities that previously had zero deterministic
            # coverage. Ordered narrow → broad so unambiguous shapes
            # (clipboard, HA, code-eval) win before more generic ones.
            self._parse_homeassistant,
            self._parse_awareness,
            self._parse_clipboard,
            self._parse_code_eval,
            self._parse_send_notification,
            self._parse_window_query,
            self._parse_weather,
            self._parse_triggers,
            # "forget how I talk" / "reset what you learned" targets the routing
            # learning ledger — must run BEFORE _parse_memory_query so it isn't
            # swallowed by the broader memory-wipe regex (which keys on memory
            # nouns, but order keeps the boundary explicit).
            self._parse_forget_learned,
            # Memory recall/delete must come BEFORE _parse_notes so "what do you
            # remember about me?" routes to show_memories rather than save_note.
            self._parse_memory_query,
            # Free-form "remember X" write path (P0.3): catches "remember I love
            # cars" before _parse_notes converts it to a bare save_note with no
            # key/value extraction.
            self._parse_free_remember,
            # Calendar/reminder must come BEFORE _parse_manage_file:
            # "add a calendar event" matches manage_file's broad "add" keyword
            # and would intercept the intent before _parse_reminder ever runs.
            self._parse_reminder,
            self._parse_notes,
            self._parse_file_action,
            self._parse_launch_app,
            self._parse_manage_file,
            self._parse_voice_toggle,
            self._parse_cancel_task,
            self._parse_exit,
            self._parse_help,
            self._parse_identity,
            self._parse_greeting,
            self._parse_confirmation,
        )

    def _parse_focus_session(self, clause, clause_lower, context):
        """Route focus / pomodoro / do-not-disturb phrases.

        2026-05-23 Step 3 — added the spoken phrasings that fell into
        chat: "silence my notifications for an hour", "block me from
        notifications for 30 min", "DND for 25", "deep work mode".

        2026-05-26 — proper-implementation pass:
          • dropped the bare ``focus on`` trigger that hijacked ordinary
            speech ("focus on my homework", "let's focus on the bug");
          • ``enable``/``activate`` + ``turn off`` verbs are now accepted
            for symmetry with ``start``/``turn on``;
          • the spoken/numeric duration is extracted into
            ``args["minutes"]`` so it matches the capability's declared
            parameter instead of relying on the plugin to re-parse text.
        """
        tools = getattr(self.router, "_tools_by_name", {})
        if "start_focus_session" not in tools:
            return None
        # End / cancel (incl. "turn off focus" for symmetry with "turn on").
        # The determiner group accepts my/the/this so "end the focus session"
        # is caught here and never falls through to the bare `focus session`
        # branch of the Start regex below (2026-05-30 intent-eval fix).
        if re.search(
            r"\b(?:end|stop|exit|cancel|disable|leave|quit)\s+(?:my\s+|the\s+|this\s+)?"
            r"(?:focus(?:\s+session|\s+mode)?|pomodoro|do\s+not\s+disturb|dnd|deep\s+work(?:\s+mode)?|"
            r"quiet\s+(?:time|mode|hours)|notification\s+block)\b"
            r"|\bturn\s+off\s+(?:focus|dnd|do\s+not\s+disturb|deep\s+work)\b",
            clause_lower,
        ):
            return {"tool": "end_focus_session", "args": {}, "text": clause, "domain": "focus"}
        # Status. The optional `session|mode` lets "focus session status" /
        # "focus mode remaining" match (the noun sits between focus and the
        # status word) instead of falling through to Start (2026-05-30 fix).
        if re.search(
            r"\b(?:focus|pomodoro|dnd|deep\s+work|do\s+not\s+disturb)(?:\s+session|\s+mode)?\s+(?:status|left|remaining|time)\b"
            r"|\bhow\s+much\s+(?:focus|time)\s+(?:is\s+)?(?:left|remaining)\b"
            r"|\bam\s+i\s+(?:still\s+)?(?:in\s+)?focus(?:\s+(?:mode|session))?\b",
            clause_lower,
        ):
            return {"tool": "focus_session_status", "args": {}, "text": clause, "domain": "focus"}
        # Start. NOTE: the object group below intentionally does NOT match a
        # bare "focus on" — that phrase belongs to ordinary speech, not a
        # session start. "focus mode on" still routes via "mode\s+on".
        if re.search(
            r"\b(?:start|begin|enter|kick\s+off|go\s+into|enable|activate|put\s+me\s+in)\s+(?:a\s+|the\s+)?"
            r"(?:focus(?:\s+session|\s+mode)?|pomodoro|do\s+not\s+disturb|dnd|deep\s+work(?:\s+mode)?|"
            r"quiet\s+(?:time|mode|hours))\b"
            r"|\b(?:focus|pomodoro|dnd|deep\s+work)\s+(?:for\s+\d+|mode|session)\b"
            # "focus for <spoken duration>" — anchored to a real duration token
            # so "focus for the meeting" / "focus for clarity" never match.
            r"|\b(?:focus|pomodoro|dnd|deep\s+work)\s+for\s+"
            r"(?:five|ten|fifteen|twenty(?:\s+five)?|thirty|forty(?:\s+five)?|fifty|sixty|ninety|"
            r"half\s+an?\s+hour|an?\s+hour)\b"
            r"|\bdo\s+not\s+disturb\s+(?:for\s+(?:\d+\s*(?:minutes?|mins?|hours?|hrs?)|"
            r"(?:a|an)\s+(?:hour|minute|while)))\b"
            r"|\b(?:silence|mute|block)\s+(?:my\s+)?notifications?\s+(?:for\s+\d+\s*(?:minutes?|mins?|hours?|hrs?)|"
            r"for\s+(?:a|an)\s+(?:hour|minute|while))\b"
            r"|\bblock\s+me\s+from\s+notifications?\b"
            r"|\b\d+\s*(?:minutes?|mins?|hours?|hrs?)\s+(?:of\s+)?(?:focus|deep\s+work|quiet)\b"
            r"|\bturn\s+on\s+(?:focus|dnd|do\s+not\s+disturb|deep\s+work)\b",
            clause_lower,
        ):
            minutes = self._focus_minutes(clause_lower)
            args = {"minutes": minutes} if minutes else {}
            return {"tool": "start_focus_session", "args": args, "text": clause, "domain": "focus"}
        return None

    # Spoken cardinals that pair with a time unit in focus utterances.
    _FOCUS_CARDINALS = {
        "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25,
        "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60,
        "ninety": 90,
    }

    def _focus_minutes(self, clause_lower):
        """Extract the session length (minutes, capped 1–240) from a focus
        clause, or None when the user named no duration (handler defaults to
        25). Handles "for 50 minutes", "for 2 hours", bare "for 25" → minutes,
        "for an hour", "for half an hour", and spoken cardinals
        ("for fifty minutes")."""
        def _cap(value):
            return max(1, min(int(value), 240))

        # Numeric with an explicit unit: "50 minutes", "2 hours", "90 min".
        m = re.search(r"(\d{1,3})\s*(hours?|hrs?|minutes?|mins?)\b", clause_lower)
        if m:
            value = int(m.group(1))
            return _cap(value * 60 if m.group(2).startswith("h") else value)
        # "for half an hour" / "half an hour".
        if re.search(r"\bhalf\s+an?\s+hour\b", clause_lower):
            return 30
        # "for an hour" / "for a hour".
        if re.search(r"\bfor\s+an?\s+hour\b", clause_lower):
            return 60
        # Spoken cardinals, but only when paired with a time unit so we never
        # mistake "twenty five" in unrelated speech for a duration.
        for word, val in sorted(self._FOCUS_CARDINALS.items(), key=lambda x: -len(x[0])):
            if re.search(rf"\b{re.escape(word)}\s*(?:minutes?|mins?|hours?|hrs?)\b", clause_lower):
                return _cap(val)
        # Bare "for 25" with no unit → minutes (e.g. "dnd for 25").
        m = re.search(r"\bfor\s+(\d{1,3})\b", clause_lower)
        if m:
            return _cap(m.group(1))
        return None

    def _parse_dictation(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if {"start_dictation", "end_dictation", "cancel_dictation"} - set(tools):
            return None
        if re.search(r"\b(?:cancel|discard|throw away)\s+(?:the\s+)?(?:memo|dictation|recording)\b", clause_lower):
            return {"tool": "cancel_dictation", "args": {}, "text": clause, "domain": "dictation"}
        if re.search(
            r"\b(?:end|stop|finish|save|close)\s+(?:the\s+)?(?:memo|dictation|recording|note(?:\s+taking)?|writing)\b",
            clause_lower,
        ):
            return {"tool": "end_dictation", "args": {}, "text": clause, "domain": "dictation"}
        if re.search(r"\b(?:end|stop|finish)\s+dictating\b", clause_lower):
            return {"tool": "end_dictation", "args": {}, "text": clause, "domain": "dictation"}
        # NOTE: dictation owns voice memos/recordings — it requires the
        # "note taking" qualifier, NOT a bare "note". "take a note" / "note
        # that X" are the save_note path (_parse_notes); without this guard
        # the dictation start regex poached them (2026-05-30 intent-eval fix).
        start_match = re.search(
            r"\b(?:take|start|begin|record|capture)\s+(?:a\s+|new\s+|the\s+)?(?:memo|dictation|note\s+taking|recording|journal entry)(?:\s+(?:called|named|titled)\s+(.+))?$",
            clause_lower,
        )
        if start_match:
            label = (start_match.group(1) or "").strip(" .!?'\"")
            args = {"label": label} if label else {}
            return {"tool": "start_dictation", "args": args, "text": clause, "domain": "dictation"}
        if re.search(r"\b(?:dictation\s+mode\s+on|enter\s+dictation|dictate(?:\s+for\s+me)?)\b", clause_lower):
            return {"tool": "start_dictation", "args": {}, "text": clause, "domain": "dictation"}
        return None

    # Step 5d (2026-05-24) — mode-detection helpers for research_topic.
    # `QUICK_PATTERNS` / `DEEP_PATTERNS` each map the phrase prefix to a
    # capture group containing the topic. When neither matches, we fall
    # back to the legacy generic patterns and leave mode unset so the
    # research_planner workflow asks the user for a focus.
    # The connector word ("on / about / for / of") is OPTIONAL — users
    # type "quick research X" just as often as "quick research on X".
    # The shape is `verb(?:\s+(?:connectors))?\s+(.+)` so the trailing
    # `\s+` consumes the separator regardless of whether the connector
    # was present. Bug from 2026-05-24 17:35: the older shape
    # `verb\s+(?:connectors)?\s+(.+)` required the connector OR a
    # second space, so "quick research Tamil Nadu" fell through to chat.
    _RESEARCH_QUICK_PATTERNS = (
        r"^(?:please\s+)?(?:tldr|tl;dr)(?:\s+(?:of|on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?(?:briefly|in\s+brief|quick\s+brief|short\s+brief|shortly)"
        r"(?:\s+(?:on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?(?:quick|fast|rapid)\s+(?:research|brief|overview|summary|recap|look|"
        r"primer|sketch|rundown)(?:\s+(?:on|about|for|of))?\s+(.+)$",
        r"^(?:please\s+)?(?:give|get|put\s+together)\s+me\s+(?:a\s+)?(?:one[\s-]?pager|"
        r"one[\s-]?page\s+(?:summary|brief|primer)|short\s+(?:summary|brief|primer))"
        r"(?:\s+(?:on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?summari[sz]e\s+(?:the\s+|my\s+|a\s+)?(?:topic\s+(?:of\s+)?)?(.+)$",
        r"^(?:please\s+)?(?:overview|primer)(?:\s+(?:of|on|about|for))?\s+(.+)$",
    )
    # Same connector-optional shape as quick patterns. 2026-05-24 17:37
    # bug: "Deep Dive Quantum Computing" never matched because the older
    # `\s+(?:on|into|...)\s+(.+)$` required a connector word.
    _RESEARCH_DEEP_PATTERNS = (
        r"^(?:please\s+)?do\s+(?:a\s+)?(?:deep\s+dive|literature\s+review|"
        r"thorough\s+(?:research|review|deep\s+dive))(?:\s+(?:on|about|into|for))?\s+(.+)$",
        r"^(?:please\s+)?(?:thorough(?:ly)?|comprehensive(?:ly)?|exhaustive(?:ly)?|"
        r"in[\s-]?depth|full|long[\s-]?form)\s+(?:research|brief|briefing|"
        r"analysis|study|review|report)(?:\s+(?:on|about|for|of))?\s+(.+)$",
        r"^(?:please\s+)?(?:deep|in[\s-]?depth)\s+(?:dive|analysis|investigation|"
        r"research|look)(?:\s+(?:on|into|about|for|of))?\s+(.+)$",
        r"^(?:please\s+)?(?:give|get|put\s+together)\s+me\s+(?:a\s+)?"
        r"(?:detailed|long|long[\s-]?form|comprehensive|deep|in[\s-]?depth|full)\s+"
        r"(?:research|brief|briefing|report|analysis|study|review)"
        r"(?:\s+(?:on|about|for|of))?\s+(.+)$",
        r"^(?:please\s+)?(?:write|draft|produce|generate|prepare)\s+(?:me\s+)?"
        r"(?:a\s+)?(?:detailed|long|long[\s-]?form|comprehensive|deep|in[\s-]?depth)\s+"
        r"(?:research\s+)?(?:report|briefing|brief|analysis|paper)"
        r"(?:\s+(?:on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?(?:(?:give|get|put\s+together)\s+me\s+(?:a\s+)?)?literature\s+review(?:\s+(?:on|about|for|of))?\s+(.+)$",
        r"^(?:please\s+)?detailed\s+(?:research|briefing|brief)(?:\s+(?:on|about|for|of))?\s+(.+)$",
        # Bare "research X" / "investigate X" / "study X" default to
        # DEEP mode (no follow-up focus prompt). 2026-05-24 default-
        # to-new-pipeline UX. Users who want a quicker result say
        # "quick research on X" / "tldr X" / "briefly on X" instead —
        # those are caught by `_RESEARCH_QUICK_PATTERNS` above this
        # block in the parser dispatch.
        r"^(?:please\s+)?research\s+(?:the\s+latest\s+(?:on|about)\s+|on\s+|about\s+|into\s+)?(.+)$",
        r"^(?:please\s+)?(?:investigate|study)\s+(.+)$",
    )
    # Comparative phrasings always go deep — multi-source synthesis is
    # the value-add.
    _RESEARCH_COMPARE_PATTERNS = (
        r"^(?:please\s+)?compare\s+(.+?)\s+(?:vs|versus|to|with|and)\s+(.+)$",
        r"^(?:please\s+)?(?:contrast|differentiate)\s+(.+?)\s+(?:vs|versus|with|and|from)\s+(.+)$",
        r"^(?:please\s+)?which\s+is\s+(?:better|best)[,:]?\s+(.+)$",
        r"^(?:please\s+)?(.+?)\s+vs\.?\s+(.+?)\s+(?:comparison|difference|differences)\s*\??$",
    )

    _QUICK_ANSWER_PATTERNS = (
        r"^(?:please\s+)?(?:give\s+me\s+(?:a\s+)?)?quick\s+answer(?:\s+(?:to|on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?(?:do\s+a\s+)?quick\s+search(?:\s+(?:on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?quickly\s+(?:look\s+up|tell\s+me|answer)(?:\s+(?:on|about|for))?\s+(.+)$",
        r"^(?:please\s+)?just\s+(?:tell|answer)\s+me(?:\s+about)?\s+(.+)$",
    )

    def _parse_quick_answer(self, clause, clause_lower, context):
        """Route 'quick answer' phrasings to the instant chat-answer tool.

        Deliberately narrow: only explicit 'quick answer'/'quick search'/
        'just tell me' phrasings. Plain questions stay with chat, and
        'quick research on X' stays with _parse_research_topic.
        """
        if "quick_answer" not in getattr(self.router, "_tools_by_name", {}):
            return None
        for pat in self._QUICK_ANSWER_PATTERNS:
            m = re.match(pat, clause_lower)
            if m:
                query = m.group(1).strip(" .!?:'\"")
                if query and len(query) >= 2:
                    return {
                        "tool": "quick_answer",
                        "args": {"query": query},
                        "text": clause,
                        "domain": "web",
                    }
        return None

    def _parse_research_topic(self, clause, clause_lower, context):
        if "research_topic" not in getattr(self.router, "_tools_by_name", {}):
            return None

        # Mode-explicit phrasings win FIRST. They skip the "any specific
        # angle?" follow-up because the user already told us how deep
        # to go.
        for pat in self._RESEARCH_QUICK_PATTERNS:
            m = re.match(pat, clause_lower)
            if m:
                topic = m.group(1).strip(" .!?:'\"")
                if topic and len(topic) >= 2:
                    return {
                        "tool": "research_topic",
                        "args": {"topic": topic, "mode": "quick"},
                        "text": clause,
                        "domain": "research",
                    }
        for pat in self._RESEARCH_DEEP_PATTERNS:
            m = re.match(pat, clause_lower)
            if m:
                topic = m.group(1).strip(" .!?:'\"")
                if topic and len(topic) >= 2:
                    return {
                        "tool": "research_topic",
                        "args": {"topic": topic, "mode": "deep"},
                        "text": clause,
                        "domain": "research",
                    }
        # Comparative phrasings → always deep, with both sides stitched
        # back into the topic so the writer sees them.
        for pat in self._RESEARCH_COMPARE_PATTERNS:
            m = re.match(pat, clause_lower)
            if m:
                if m.lastindex and m.lastindex >= 2:
                    left = (m.group(1) or "").strip(" .!?:'\"")
                    right = (m.group(2) or "").strip(" .!?:'\"")
                    topic = f"{left} vs {right}" if left and right else (left or right)
                else:
                    topic = (m.group(1) or "").strip(" .!?:'\"")
                if topic and len(topic) >= 2:
                    return {
                        "tool": "research_topic",
                        "args": {"topic": topic, "mode": "deep"},
                        "text": clause,
                        "domain": "research",
                    }

        # Legacy generic patterns — leave mode UNSET so the research
        # planner asks the user for focus + depth. Used by callers
        # like "brief me on X" / "find papers on X" where intent is
        # ambiguous (a quick briefing? a paper survey?).
        topic_patterns = (
            r"^(?:please\s+)?(?:put\s+together|prepare|write|draft|generate)\s+(?:me\s+)?"
            r"(?:a\s+)?(?:research\s+)?briefing\s+(?:on|about|for)\s+(.+)$",
            r"^(?:please\s+)?brief\s+me\s+(?:on|about)\s+(.+)$",
            r"^(?:please\s+)?(?:find|gather|fetch|pull|collect|surface|dig\s+up)\s+(?:me\s+)?"
            r"(?:some\s+)?(?:research\s+(?:papers|articles)|articles|papers|sources|references)"
            r"(?:\s+(?:on|about|for))?\s+(.+)$",
            r"^(?:please\s+)?give\s+me\s+(?:a\s+)?briefing\s+(?:on|about|of)\s+(.+)$",
        )
        for pattern in topic_patterns:
            match = re.match(pattern, clause_lower)
            if not match:
                continue
            topic = match.group(1).strip(" .!?:'\"")
            if not topic or len(topic) < 2:
                continue
            return {
                "tool": "research_topic",
                "args": {"topic": topic},
                "text": clause,
                "domain": "research",
            }
        return None

    # ── Hermes-ported web tools (2026-05-23) ──────────────────────────
    # Reliable disambiguation between three web verbs:
    #   • "google for X" / "search the web for X" → search_google (browser_automation)
    #   • "fetch <URL>" / "extract <URL>" / "read this URL" → web_extract
    #   • "crawl <URL>" / "scrape this site" → web_crawl
    # The fetch and crawl parsers REQUIRE an explicit https?:// URL so
    # they can never collide with search_indexed_files ("find ML
    # stories") or with launch_app ("crawl" as a verb without a URL).
    _URL_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
    _WEB_FETCH_VERBS = re.compile(
        r"\b(?:fetch|extract|read|open|grab|pull|get|download)\b", re.IGNORECASE
    )
    _WEB_CRAWL_VERBS = re.compile(
        r"\b(?:crawl|scrape|spider|harvest)\b", re.IGNORECASE
    )

    _NEWSPAPER_PHRASES_RE = re.compile(
        r"\b(?:clean\s+text|article\s+body|main\s+content|just\s+the\s+article|"
        r"strip\s+(?:nav|footer|boilerplate)|newspaper\s+extract|"
        r"reader\s+(?:mode|view))\b",
        re.IGNORECASE,
    )

    def _parse_newspaper_extract(self, clause, clause_lower, context):
        """Route URL + "clean text / article body / reader mode / …" to
        the trafilatura-backed extractor instead of the generic
        web_extract (which keeps nav / footer garbage).

        Runs BEFORE `_parse_web_url_action` so the more specific phrasing
        wins.
        """
        tools = getattr(self.router, "_tools_by_name", {})
        if "newspaper_extract" not in tools:
            return None
        url_match = self._URL_PATTERN.search(clause)
        if not url_match:
            return None
        if not self._NEWSPAPER_PHRASES_RE.search(clause):
            return None
        return {
            "tool": "newspaper_extract",
            "args": {"url": url_match.group(0).rstrip(".,;:!?)")},
            "text": clause,
            "domain": "research",
        }

    def _parse_web_url_action(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        url_match = self._URL_PATTERN.search(clause)
        if not url_match:
            return None
        url = url_match.group(0).rstrip(".,;:!?)\"")

        # Crawl is checked first — "crawl <URL>" must beat "extract <URL>"
        # when both verbs appear. The bare verb pattern is enough; the URL
        # is the disambiguator.
        if "web_crawl" in tools and self._WEB_CRAWL_VERBS.search(clause_lower):
            # Optional "and find X" / "for X" → instructions slot.
            instr = ""
            inst_match = re.search(
                r"\b(?:and\s+(?:find|look\s+for|gather|extract)|for|to\s+find)\s+(.+)$",
                clause_lower,
            )
            if inst_match:
                instr = inst_match.group(1).strip(" .!?")
            return {
                "tool": "web_crawl",
                "args": {"url": url, "instructions": instr},
                "text": clause,
                "domain": "web",
            }

        if "web_extract" in tools and self._WEB_FETCH_VERBS.search(clause_lower):
            return {
                "tool": "web_extract",
                "args": {"url": url},
                "text": clause,
                "domain": "web",
            }

        # Bare URL with no verb → still try web_extract if available.
        # Common phrasing: "https://...". Don't poach if no web tools live.
        bare_url_only = clause.strip() == url
        if bare_url_only and "web_extract" in tools:
            return {
                "tool": "web_extract",
                "args": {"url": url},
                "text": clause,
                "domain": "web",
            }
        return None

    def _parse_google_search(self, clause, clause_lower, context):
        if "search_google" not in getattr(self.router, "_tools_by_name", {}):
            return None
        # "search google for X", "google search X", "google for X", "look up X"
        patterns = (
            r"\bsearch\s+google\s+for\s+(.+)$",
            r"\bgoogle\s+search\s+for\s+(.+)$",
            r"\bgoogle\s+(?:for\s+)?(.+)$",
            r"\bsearch\s+(?:on|in)\s+google\s+for\s+(.+)$",
            r"\bsearch\s+(?:the\s+)?(?:web|internet)\s+for\s+(.+)$",
            r"\blook\s+up\s+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, clause_lower)
            if match:
                query = match.group(1).strip(" ?.!,")
                # Avoid intercepting "google calendar" / "google drive" / etc.
                if query.split()[:1] and query.split()[0] in {"calendar", "drive", "docs", "sheets", "tasks", "keep"}:
                    return None
                if not query:
                    return None
                browser_name = "chromium" if "chromium" in clause_lower else "chrome"
                return {
                    "tool": "search_google",
                    "args": {"query": query, "browser_name": browser_name},
                    "text": clause,
                    "domain": "browser",
                }
        return None

    def _parse_browser_media(self, clause, clause_lower, context):
        browser_name = "chromium" if "chromium" in clause_lower else "chrome"
        active_browser = self._active_browser_workflow()
        tools = getattr(self.router, "_tools_by_name", {})

        # Re-open continuation ("open it again" / "reopen" / "play it again" /
        # "resume that" / "open the video again"). The v2 turn path catches
        # these earlier via the browser_media workflow's can_continue; this is
        # the deterministic safety net for the v1 path (no workflow hook) so
        # they never fall through to open_file. Only fires when a browser_media
        # workflow is active, so it can't poach a plain "open my file".
        # Placed before play_video/bare_play so "play it again" isn't parsed
        # with a literal query of "it again". Shares the workflow path's
        # matcher (modules.browser_automation.media_helpers).
        if active_browser:
            from modules.browser_automation.media_helpers import (  # noqa: PLC0415
                is_reopen_media_command,
            )
            if is_reopen_media_command(clause_lower):
                query = active_browser.get("query", "")
                bname = active_browser.get("browser_name") or browser_name
                platform = active_browser.get("platform") or "youtube"
                if query:
                    tool_name = "play_youtube_music" if platform == "youtube_music" else "play_youtube"
                    if tool_name in tools:
                        return {
                            "tool": tool_name,
                            "args": {"query": query, "browser_name": bname},
                            "text": clause,
                            "domain": "browser",
                        }
                if "open_browser_url" in tools:
                    url = (
                        "https://music.youtube.com" if platform == "youtube_music"
                        else "https://www.youtube.com"
                    )
                    return {
                        "tool": "open_browser_url",
                        "args": {"url": url, "browser_name": bname},
                        "text": clause,
                        "domain": "browser",
                    }

        play_music = re.search(r"\bplay\s+(.+?)\s+(?:in|on)\s+youtube music\b", clause_lower)
        if play_music and "play_youtube_music" in getattr(self.router, "_tools_by_name", {}):
            query = play_music.group(1).strip()
            if query in {"it", "this", "that"} and active_browser:
                query = active_browser.get("query", query)
            return {
                "tool": "play_youtube_music",
                "args": {"query": query, "browser_name": browser_name},
                "text": clause,
                "domain": "browser",
            }

        open_and_play_music = re.search(r"\bopen\s+youtube music\b.*?\band\s+play\s+(.+)$", clause_lower)
        if open_and_play_music and "play_youtube_music" in getattr(self.router, "_tools_by_name", {}):
            return {
                "tool": "play_youtube_music",
                "args": {"query": open_and_play_music.group(1).strip(), "browser_name": browser_name},
                "text": clause,
                "domain": "browser",
            }

        open_and_play_video = re.search(r"\bopen\s+youtube\b.*?\band\s+play\s+(.+)$", clause_lower)
        if (
            open_and_play_video
            and "play_youtube" in getattr(self.router, "_tools_by_name", {})
            and "youtube music" not in open_and_play_video.group(1)
        ):
            return {
                "tool": "play_youtube",
                "args": {"query": open_and_play_video.group(1).strip(), "browser_name": browser_name},
                "text": clause,
                "domain": "browser",
            }

        play_video = re.search(r"\bplay\s+(.+?)\s+(?:in|on)\s+youtube\b", clause_lower)
        if play_video and "play_youtube" in getattr(self.router, "_tools_by_name", {}):
            query = play_video.group(1).strip()
            if query in {"it", "this", "that"} and active_browser:
                query = active_browser.get("query", query)
            return {
                "tool": "play_youtube",
                "args": {"query": query, "browser_name": browser_name},
                "text": clause,
                "domain": "browser",
            }

        bare_play = re.search(r"\bplay\s+(.+)$", clause_lower)
        if bare_play:
            query = bare_play.group(1).strip()
            if query in {"it", "this", "that"} and active_browser:
                query = active_browser.get("query", query)
            if query and query not in {"it", "this", "that"}:
                platform = self._default_browser_platform(query, active_browser)
                tool_name = "play_youtube_music" if platform == "youtube_music" else "play_youtube"
                if tool_name in getattr(self.router, "_tools_by_name", {}):
                    return {
                        "tool": tool_name,
                        "args": {"query": query, "browser_name": browser_name},
                        "text": clause,
                        "domain": "browser",
                    }

        if re.search(r"\bopen\s+youtube music\b", clause_lower) and "open_browser_url" in getattr(self.router, "_tools_by_name", {}):
            return {
                "tool": "open_browser_url",
                "args": {"url": "https://music.youtube.com", "browser_name": browser_name},
                "text": clause,
                "domain": "browser",
            }

        if re.search(r"\bopen\s+youtube\b", clause_lower) and "open_browser_url" in getattr(self.router, "_tools_by_name", {}):
            return {
                "tool": "open_browser_url",
                "args": {"url": "https://www.youtube.com", "browser_name": browser_name},
                "text": clause,
                "domain": "browser",
            }

        if active_browser and "browser_media_control" in getattr(self.router, "_tools_by_name", {}):
            normalized = clause_lower.strip(" .!?")
            
            # Complex phrase matching for skipping/reverting (making 'seconds' optional)
            if re.search(r"\b(?:skip|forward|move)\b.*?\b(?:seconds?|secs?)\b", normalized) or re.search(r"\bfast\s+forward\b", normalized):
                return {"tool": "browser_media_control", "args": {"control": "forward"}, "text": clause, "domain": "browser"}
            if re.search(r"\b(?:revert|back|rewind|previous)\b.*?\b(?:seconds?|secs?)\b", normalized):
                return {"tool": "browser_media_control", "args": {"control": "backward"}, "text": clause, "domain": "browser"}
            
            mapping = {
                "play": "resume",
                "pause": "pause",
                "resume": "resume",
                "stop": "pause",
                "next": "next",
                "skip": "next",
                "next video": "next",
                "previous video": "previous",
                "previous": "previous",
                "rewind": "previous", # Requested mapping: Shift+P
                "forward": "forward",
                "backward": "backward",
                "revert": "backward",
                "back": "backward",
            }
            if normalized in mapping:
                return {
                    "tool": "browser_media_control",
                    "args": {"control": mapping[normalized]},
                    "text": clause,
                    "domain": "browser",
                }
            if "music instead" in normalized:
                control = "play"
                query = active_browser.get("query", "")
                return {
                    "tool": "play_youtube_music",
                    "args": {"query": query, "browser_name": active_browser.get("browser_name", "chrome")},
                    "text": clause,
                    "domain": "browser",
                }
            if "youtube instead" in normalized:
                return {
                    "tool": "play_youtube",
                    "args": {"query": active_browser.get("query", ""), "browser_name": active_browser.get("browser_name", "chrome")},
                    "text": clause,
                    "domain": "browser",
                }

        return None

    # Track 2.1 (Consolidation Direction): deterministic personal-fact
    # storage and recall. Catches phrases like "my X is Y" / "where do
    # I live" before they fall through to chat where the LLM would
    # paraphrase or hallucinate. Routes to `record_personal_fact` /
    # `recall_personal_fact` capabilities backed by MemoryFacade.

    _RECORD_FACT_PATTERN = re.compile(
        r"^(?:my\s+|i'?m\s+|i\s+am\s+)"
        r"(name|location|role|job|profession|hometown|city|email|phone|birthday|"
        r"favou?rite\s+\w+|preferred\s+\w+)"
        r"\s+(?:is|=|:)\s+(.+?)\s*$",
        re.IGNORECASE,
    )
    _CALL_ME_PATTERN = re.compile(r"^call\s+me\s+(.+?)\s*$", re.IGNORECASE)
    _RECALL_FACT_PATTERNS = (
        (re.compile(r"^where\s+(?:do|am)\s+i\s+(?:live|from)\b", re.IGNORECASE), "location"),
        (re.compile(r"^what'?s?\s+my\s+(name|location|role|job|profession|hometown|city|email|phone|birthday)\b", re.IGNORECASE), None),
        (re.compile(r"^what\s+is\s+my\s+(name|location|role|job|profession|hometown|city|email|phone|birthday)\b", re.IGNORECASE), None),
        (re.compile(r"^who\s+am\s+i\b", re.IGNORECASE), "name"),
    )

    def _parse_personal_fact(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        # Record path — "my location is Nellore" / "i am a builder" / "call me X".
        if "record_personal_fact" in tools:
            match = self._RECORD_FACT_PATTERN.match(clause.strip())
            if match:
                key = match.group(1).lower().replace(" ", "_")
                value = match.group(2).strip().rstrip(".!?")
                if value:
                    return {
                        "tool": "record_personal_fact",
                        "args": {"key": key, "value": value},
                        "text": clause,
                        "domain": "memory",
                    }
            call_me = self._CALL_ME_PATTERN.match(clause.strip())
            if call_me:
                value = call_me.group(1).strip().rstrip(".!?")
                if value:
                    return {
                        "tool": "record_personal_fact",
                        "args": {"key": "name", "value": value},
                        "text": clause,
                        "domain": "memory",
                    }
        # Recall path — "where do i live" / "what's my name" / "who am i".
        if "recall_personal_fact" in tools:
            stripped = clause.strip().rstrip(".!?")
            for pattern, default_key in self._RECALL_FACT_PATTERNS:
                m = pattern.match(stripped)
                if m:
                    if default_key:
                        key = default_key
                    else:
                        try:
                            key = m.group(1).lower()
                        except IndexError:
                            continue
                    return {
                        "tool": "recall_personal_fact",
                        "args": {"key": key},
                        "text": clause,
                        "domain": "memory",
                    }
        return None

    # A standalone goodbye/exit phrase that must escape ANY pending slot-fill.
    # Mirrors the vocabulary in `_parse_exit`; kept narrow (whole-clause match)
    # so a real filename like "exit_plan.txt" is never mistaken for a quit.
    _EXIT_ESCAPE_RE = re.compile(
        r"(?:bye|goodbye|exit|quit|stop\s+assistant)(?:\s+friday)?[.!?]*"
        r"|(?:shut\s*down|close)\s+(?:friday|the\s+assistant|yourself)[.!?]*",
        re.IGNORECASE,
    )

    def _parse_pending_selection(self, clause, clause_lower, context):
        dialog_state = getattr(self.router, "dialog_state", None)
        if not dialog_state:
            return None

        # A bare goodbye/exit while a slot-fill is outstanding means "abandon
        # the prompt and shut down" — NOT "the filename is 'bye'". Without this
        # escape the pending-file-name branch below swallows "bye" as the
        # filename and searches for it (which is how "bye" matched the
        # *goodbye* test files on 2026-05-29). Clear every pending slot and
        # fall through so `_parse_exit` routes to shutdown_assistant.
        if self._EXIT_ESCAPE_RE.fullmatch(clause_lower.strip()):
            dialog_state.reset_pending("exit during pending slot-fill")
            return None

        # ── Pending file-NAME request ─────────────────────────────────────────
        # FRIDAY asked "Which file would you like me to X?" — no candidates yet.
        # User's next input IS the file name; intercept before domain parsers
        # (e.g. "screenshot" → take_screenshot) can steal it.
        pending_fname = getattr(dialog_state, "pending_file_name_request", None)
        if pending_fname:
            if re.search(r"\b(?:cancel|never\s*mind|forget\s+it|skip)\b", clause_lower):
                dialog_state.pending_file_name_request = None
                return None  # let _parse_confirmation handle the cancel
            dialog_state.pending_file_name_request = None
            action_to_tool = {
                "open": "open_file",
                "read": "read_file",
                "summarize": "summarize_file",
                "find": "search_file",
            }
            tool = action_to_tool.get(pending_fname, "open_file")
            # Strip leading articles so "the screenshot" → filename "screenshot"
            filename = re.sub(
                r"^\s*(?:the|a|an|my|that|this|it)\s+", "", clause, flags=re.IGNORECASE
            ).strip()
            return {"tool": tool, "args": {"filename": filename or clause.strip()}, "text": clause, "domain": "files"}

        # ── Pending folder request ────────────────────────────────────────────
        # FRIDAY asked "Which folder should I X?" — user is providing a folder name.
        pending_folder = getattr(dialog_state, "pending_folder_request", None)
        if pending_folder:
            if re.search(r"\b(?:cancel|never\s*mind|forget\s+it|skip)\b", clause_lower):
                dialog_state.pending_folder_request = None
                return None
            dialog_state.pending_folder_request = None
            tool = "open_folder" if pending_folder == "open" else "list_folder_contents"
            return {"tool": tool, "args": {}, "text": clause, "domain": "files"}

        # ── Pending candidate list ────────────────────────────────────────────
        # Track 1.4b note: `core/planning/context_resolver.py` path 3
        # (`_pending_selection_rescue`) covers the SAME selection-shape
        # inputs at the post-plan layer for the v2 turn path. The branches
        # below remain in place because the v1 turn path (CapabilityBroker
        # / CommandRouter) has no resolver hook — deleting these without
        # Track 3 retiring v1 first would silently regress v1 turns that
        # arrive with a pending file request. Deletion is scheduled for
        # the Track 3 commit that removes v1.
        # ── Pending goal selection ─────────────────────────────────────────
        pending_goal = getattr(dialog_state, "pending_goal_selection", None)
        if isinstance(pending_goal, PendingGoalSelection) and pending_goal.candidates:
            if re.search(r"\b(?:cancel|never\s*mind|forget\s+it|skip|none)\b", clause_lower):
                dialog_state.clear_pending_goal_selection()
                return None
            return {"tool": "select_goal_candidate", "args": {}, "text": clause, "domain": "goals"}

        pending = getattr(dialog_state, "pending_file_request", None)
        if not pending or not pending.candidates:
            return None

        normalized = clause_lower.strip(" .!?")
        if re.fullmatch(r"(?:option\s+)?\d+", normalized):
            return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        # Track 1.3: ordinal references — both word ("first one") and digit
        # ("1st one") forms route to candidate selection when a pending list
        # is active. The bug at 11:51:36 on 2026-05-17 ("1st one" → llm_chat
        # hallucination) was this branch missing. `choose_candidate_from_text`
        # handles the actual index mapping.
        if re.fullmatch(
            r"(?:the\s+)?"
            r"(?:1st|2nd|3rd|[4-9]th|10th"
            r"|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)"
            r"(?:\s+(?:one|option|file|item|result))?",
            normalized,
        ):
            return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        if re.fullmatch(r"(?:the\s+)?(?:pdf|txt|md|json|csv|py|docx)\s+one", normalized):
            return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        if normalized in {"that one", "this one"}:
            return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        candidate_names = {os.path.basename(path).lower() for path in pending.candidates}
        candidate_stems = {os.path.splitext(name)[0] for name in candidate_names}

        # Exact match (normalized)
        if normalized in candidate_names or normalized in candidate_stems:
            return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        # Prefix match: "screenshot" matches "screenshot_20260515_123456.png"
        # Requires ≥3 chars to avoid over-matching short words.
        if len(normalized) >= 3:
            for stem in candidate_stems:
                norm_stem = re.sub(r"[^a-z0-9 ]+", " ", stem).strip()
                if norm_stem.startswith(normalized.replace("_", " ").replace("-", " ")):
                    return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        return None

    def _parse_launch_app(self, clause, clause_lower, context):
        if re.search(r"\b(?:file|folder)\b", clause_lower):
            return None
        pending = getattr(getattr(self.router, "dialog_state", None), "pending_file_request", None)
        if pending and re.search(r"\b(?:open|launch|start|bring up)\s+(?:it|this|that|one)\b", clause_lower):
            return None
        app_names = extract_app_names(clause_lower)
        if app_names and re.search(r"\b(?:open|launch|start|bring up)\b", clause_lower):
            return {
                "tool": "launch_app",
                "args": {"app_names": app_names},
                "text": clause,
                "domain": "apps",
            }
        return None

    def _parse_volume(self, clause, clause_lower, context):
        """Route volume phrases to `set_volume`.

        Coverage (2026-05-23 Step 3 broadened the verb list):
          • Absolute: "set volume to 50", "volume 50", "volume to 50%".
          • Up/down: "volume up/down", "turn up/down the volume".
          • Unambiguous audio verbs (no 'volume' word required):
            "louder", "quieter", "softer", "crank it" — these only make
            sense for audio so we don't need the audio-term gate.
          • Audio-term-gated verbs: "raise/increase/lower/decrease" + a
            'volume/sound/audio' anchor. Without the anchor, "raise"
            would steal "raise the question" and "lower" would steal
            "lower the screen" (which we want for brightness).
          • Mute / unmute. Bare "mute" only if the whole utterance is
            literally "mute" — otherwise "mute the alarm" would match.
        """
        absolute_percent = self._extract_volume_percent(clause_lower, context)
        if absolute_percent is not None:
            return {
                "tool": "set_volume",
                "args": {"percent": absolute_percent},
                "text": clause,
                "domain": "volume",
            }

        direction = None
        has_audio_term = bool(re.search(r"\b(?:volume|sound|audio)\b", clause_lower))

        # 1. Mute / unmute first — they don't take a direction step.
        if re.search(r"\bunmute\b", clause_lower):
            direction = "unmute"
        elif re.search(r"\bmute\b", clause_lower) and (has_audio_term or re.fullmatch(r"mute[.!?]?", clause_lower.strip())):
            direction = "mute"
        # 2. Explicit volume up/down.
        elif re.search(r"\bvolume\s+up\b|\bturn\s+(?:up\s+)?(?:the\s+)?volume\b", clause_lower) and "up" in clause_lower:
            direction = "up"
        elif re.search(r"\bvolume\s+down\b|\bturn\s+(?:down\s+)?(?:the\s+)?volume\b", clause_lower) and "down" in clause_lower:
            direction = "down"
        # 3. Unambiguous audio adjectives — don't need 'volume' word.
        elif re.search(r"\b(?:louder|crank\s+it|pump\s+it\s+up|too\s+quiet)\b", clause_lower):
            direction = "up"
        elif re.search(r"\b(?:quieter|softer|too\s+loud|tone\s+(?:it\s+)?down)\b", clause_lower):
            direction = "down"
        # 4. Audio-term-gated verbs.
        elif has_audio_term and re.search(r"\b(?:increase|raise|crank|pump|boost)\b", clause_lower):
            direction = "up"
        elif has_audio_term and re.search(r"\b(?:decrease|lower|soften|reduce|drop)\b", clause_lower):
            direction = "down"
        # 5. "Turn it up/down" — only when the previous turn was volume.
        elif context.get("domain") == "volume" and re.search(r"\bturn\s+(?:it\s+)?(?:up|down)\b", clause_lower):
            direction = "up" if "up" in clause_lower else "down"
        elif "volume" in clause_lower and context.get("domain") == "volume":
            direction = context.get("args", {}).get("direction")

        if not direction:
            return None

        steps = self._extract_count(clause_lower)
        return {
            "tool": "set_volume",
            "args": {"direction": direction, "steps": steps},
            "text": clause,
            "domain": "volume",
        }

    def _parse_system(self, clause, clause_lower, context):
        if re.search(r"\b(?:system info|system information|system status|system health|system details)\b", clause_lower):
            return {"tool": "get_system_status", "args": {}, "text": clause, "domain": "system"}

        # Require an explicit battery-status framing. Bare `battery` overmatches on
        # phrases like "the battery in my car died".
        if re.search(
            r"\b(?:battery\s+(?:status|level|percent(?:age)?|charge|life|remaining|health)|"
            r"how(?:'s|\s+is|\s+much)\s+(?:my\s+|the\s+)?battery|"
            r"what(?:'s|\s+is)\s+(?:my\s+|the\s+)?battery(?:\s+(?:status|level|at))?|"
            r"check\s+(?:my\s+|the\s+)?battery)\b",
            clause_lower,
        ):
            return {"tool": "get_battery", "args": {}, "text": clause, "domain": "system"}

        # CPU/RAM queries must include an explicit resource-status marker.
        # Lone words like "memory", "performance", "usage" overmatch heavily.
        if re.search(
            r"\b(?:cpu|ram)\s+(?:usage|load|status|free|info)\b"
            r"|\bmemory\s+(?:usage|load|status|free|info)\b"
            r"|\b(?:resource|performance)\s+(?:usage|status|info)\b"
            r"|\b(?:show|check|tell\s+me|what(?:'s|\s+is))\s+(?:my\s+|the\s+)?(?:cpu|ram|memory|resource)\s+(?:usage|load|status)\b"
            r"|\bhow\s+much\s+(?:cpu|ram|memory)\s+(?:am\s+i\s+using|is\s+(?:being\s+)?used|is\s+free|do\s+i\s+have)\b",
            clause_lower,
        ):
            return {"tool": "get_cpu_ram", "args": {}, "text": clause, "domain": "system"}

        return None

    def _parse_friday_status(self, clause, clause_lower, context):
        if "get_friday_status" not in getattr(self.router, "_tools_by_name", {}):
            return None
        if re.search(
            r"\b(?:"
            r"friday\s+status|"
            r"friday,?\s+(?:are\s+you\s+(?:ready|okay|ok|up|there|running|working|functional|online)|how\s+are\s+you(?:\s+doing)?)|"
            r"(?:how\s+are\s+you(?:\s+doing)?|are\s+you\s+(?:ready|okay|ok|up|there|running|working|functional|online))\s*,?\s*friday|"
            r"(?:assistant|runtime|model)\s+status|"
            r"check\s+(?:friday|the\s+assistant|runtime)|"
            r"(?:your|assistant'?s?)\s+status"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_friday_status", "args": {}, "text": clause, "domain": "system"}
        return None

    def _parse_time_date(self, clause, clause_lower, context):
        # ── time queries ────────────────────────────────────────────────
        # "what time is it" / "current time" / "tell me the time" — always time queries.
        # "what is the time" is a time query only when NOT followed by "of <noun>",
        # which would indicate a concept name like "Time of Useful Consciousness".
        if re.search(
            r"\b(?:what\s+time\s+is\s+it|current\s+time|tell\s+me(?:\s+the)?\s+time|"
            r"what\s+time(?:\s+is)?\s+it\s+now|got\s+the\s+time|do\s+you\s+have\s+the\s+time|"
            r"the\s+time\s+please|time\s+please|time\s+now)\b"
            r"|what(?:'s|\s+is)?\s+(?:the\s+)?time\b(?!\s+of\b)",
            clause_lower,
        ) or re.fullmatch(r"(?:the\s+)?time", clause_lower.strip(" .!?")):
            return {"tool": "get_time", "args": {}, "text": clause, "domain": "time"}

        # ── date queries ────────────────────────────────────────────────
        if re.search(
            r"\b(?:today(?:'s)?\s+date|what(?:'s|\s+is)?\s+(?:the\s+)?date|what\s+day\s+is\s+(?:it|today)|"
            r"current\s+date|tell\s+me(?:\s+the)?\s+date|"
            r"what(?:'s|\s+is)?\s+today(?:'s\s+date)?|what(?:'s|\s+is)?\s+the\s+day(?:\s+today)?|"
            r"date\s+today|date\s+please)\b",
            clause_lower,
        ) or re.fullmatch(r"(?:the\s+)?(?:date|today)", clause_lower.strip(" .!?")):
            return {"tool": "get_date", "args": {}, "text": clause, "domain": "date"}

        return None

    def _parse_screenshot(self, clause, clause_lower, context):
        # Require an explicit capture verb. The previous `or "screenshot" in clause_lower`
        # fallback fired on any mention of the word, e.g. "I deleted my screenshot folder".
        # Strict screenshot verbs (only ones that mean "capture an image").
        # NOTE: "make" was here briefly but `make my screen brighter`
        # matches the same shape; restricted to the capture-only verbs.
        if re.search(
            r"\b(?:take|capture|grab|snap|shoot|print|do)\s+"
            r"(?:a\s+|another\s+|the\s+|my\s+|me\s+a\s+)?"
            r"(?:screenshot|screen\s*shot|screen\s+capture|snapshot|"
            r"pic(?:ture)?\s+of\s+(?:my\s+|the\s+)?screen|"
            r"shot\s+of\s+(?:my\s+|the\s+)?screen|print\s*screen)\b",
            clause_lower,
        ):
            return {"tool": "take_screenshot", "args": {}, "text": clause, "domain": "screen"}
        # "capture my screen" / "grab the screen" — narrower verb list so
        # "make my screen brighter" (brightness) can't be poached.
        if re.search(
            r"\b(?:capture|grab|snap)\s+(?:a\s+|the\s+|my\s+)?screen\b(?!\s+brighter|\s+darker|\s+brightness)",
            clause_lower,
        ):
            return {"tool": "take_screenshot", "args": {}, "text": clause, "domain": "screen"}
        # "get me a screenshot" — explicit 'get me' shape.
        if re.search(
            r"\bget\s+me\s+(?:a\s+)?(?:screenshot|screen\s*shot|snapshot)\b",
            clause_lower,
        ):
            return {"tool": "take_screenshot", "args": {}, "text": clause, "domain": "screen"}
        # Bare imperative "screenshot" / "screenshot please" / "snap it".
        if re.fullmatch(
            r"(?:please\s+)?(?:screen\s*shot|snapshot|print\s*screen)(?:\s+please)?[.!?]?",
            clause_lower.strip(),
        ):
            return {"tool": "take_screenshot", "args": {}, "text": clause, "domain": "screen"}
        return None

    # ------------------------------------------------------------------
    # Track 6 / 6.3 (2026-05-23): environmental-awareness + screen-lock
    # intent parsers. The capabilities themselves were registered with
    # context_terms, but context_terms only feed the RouteScorer — the
    # deterministic IntentRecognizer needs explicit patterns or the
    # request falls through to the LLM planner where small models
    # hallucinate (seen in the 15:35 session: "Friday rescan my apps"
    # → chat → 'The user wants to rescan their apps...').
    # ------------------------------------------------------------------

    def _parse_environment(self, clause, clause_lower, context):
        """Route 'rescan apps / reindex files / find file X' deterministically."""
        tools = getattr(self.router, "_tools_by_name", {})

        # refresh_app_index -------------------------------------------------
        if "refresh_app_index" in tools and re.search(
            r"\b(?:re-?scan|re-?index|re-?fresh|re-?build|update)\s+"
            r"(?:my\s+|the\s+|installed\s+)?(?:apps?|applications?|app\s+index|application\s+index)\b"
            r"|\b(?:apps?|applications?)\s+(?:re-?scan|re-?index|re-?fresh)\b",
            clause_lower,
        ):
            return {"tool": "refresh_app_index", "args": {}, "text": clause, "domain": "environment"}

        # refresh_file_index ------------------------------------------------
        if "refresh_file_index" in tools and re.search(
            r"\b(?:re-?index|re-?scan|re-?fresh|re-?build|update)\s+"
            r"(?:my\s+|the\s+)?(?:files?|filesystem|file\s+index|files?\s+index)\b"
            r"|\bscan\s+(?:my\s+|the\s+)?(?:filesystem|drive|disks?)\b"
            r"|\brebuild\s+(?:the\s+)?(?:file\s+)?index\b",
            clause_lower,
        ):
            return {"tool": "refresh_file_index", "args": {}, "text": clause, "domain": "environment"}

        # search_indexed_files ---------------------------------------------
        #
        # Two patterns — both intentionally stricter than the verb
        # phrasings used elsewhere so we don't poach from `search_file`
        # (which already handles "find the file <natural language>"):
        #
        #   A) explicit "called <name>" — strongest user signal.
        #   B) implicit pattern: requires the query to look like a
        #      filename (contains an extension like .md, .pdf, .txt).
        #
        # Anything else falls through to the existing `_parse_file_action`
        # which knows how to do fuzzy filename matching on disk. The
        # split keeps the workflow-orchestration test green while still
        # giving users a fast index lookup when they ask for it.
        if "search_indexed_files" in tools:
            verbs = r"(?:where(?:'s|\s+is)?|find|locate|look\s+for|search\s+for)"
            # Pattern A — explicit "called <name>" with the word "file".
            m = re.search(
                rf"{verbs}\s+(?:the\s+)?(?:indexed\s+)?file\s+called\s+([\w.\-]+(?:\s+[\w.\-]+){{0,2}})",
                clause_lower,
            )
            # Pattern B — name with extension, "file" word optional.
            if not m:
                m = re.search(
                    rf"{verbs}\s+(?:the\s+)?(?:indexed\s+)?(?:file\s+)?([\w\-]+\.\w{{1,5}})",
                    clause_lower,
                )
            if m:
                query = m.group(1).strip().strip(".?!,")
                return {
                    "tool": "search_indexed_files",
                    "args": {"query": query},
                    "text": clause,
                    "domain": "environment",
                }
        return None

    def _parse_brightness(self, clause, clause_lower, context):
        """Route brightness phrases deterministically to `set_brightness`.

        Accepted shapes (2026-05-23 Step 3 broadened the coverage from the
        previous list of two):
          • "set brightness to 60" / "brightness 60%" / "brightness to 60"
          • "dim (the screen) to 30" / "brighten to 80"
          • "make it brighter/darker/dimmer" — relative (delta), handler
            converts to a sensible absolute (defaults to ±20).
          • "make my screen brighter" / "turn down the screen" /
            "lower the screen brightness" / "raise screen brightness"
          • "max brightness" / "minimum brightness" / "full brightness" /
            "lowest brightness" / "dim the screen all the way"
          • Spoken numbers: "set brightness to fifty" / "twenty five"
            / "seventy five" — see the `cardinals` map.

        Honest failure mode lives in the capability handler (see
        modules/system_control/brightness.py) — this parser only handles
        the routing, the percent extraction, and the cardinal-to-int
        coercion for spoken numbers.
        """
        if "set_brightness" not in getattr(self.router, "_tools_by_name", {}):
            return None

        # Cardinal map for spoken numbers ("set brightness to fifty").
        cardinals = {
            "zero": 0, "five": 5, "ten": 10, "fifteen": 15,
            "twenty": 20, "twenty five": 25,
            "thirty": 30, "thirty five": 35,
            "forty": 40, "forty five": 45,
            "fifty": 50, "fifty five": 55,
            "sixty": 60, "sixty five": 65,
            "seventy": 70, "seventy five": 75,
            "eighty": 80, "eighty five": 85,
            "ninety": 90, "ninety five": 95,
            "hundred": 100, "one hundred": 100, "a hundred": 100,
            "max": 100, "maximum": 100, "full": 100,
            "minimum": 0, "min": 0, "lowest": 0, "darkest": 0,
        }

        # Trigger words — must appear for this parser to fire.
        # Broadened to include "the screen" + verbs that pair with it.
        is_brightness_clause = bool(
            re.search(
                r"\bbrightness\b"
                r"|\bbright(?:er|est|en)?\b"
                r"|\bdim(?:mer|mest)?\b"
                r"|\bdark(?:er|est)?\b"
                r"|\b(?:make|turn|set|lower|raise|increase|decrease|push|crank)\s+"
                r"(?:up|down|the|my|it|screen)\b.*\b(?:screen|brightness|display|backlight)\b"
                r"|\b(?:screen|display)\s+(?:brightness|light)\b",
                clause_lower,
            )
        )
        if not is_brightness_clause:
            return None

        percent: int | None = None

        # 1. Explicit numeric ("60", "60%", "to 60").
        m = re.search(r"(\d{1,3})\s*%?", clause_lower)
        if m:
            value = int(m.group(1))
            if 0 <= value <= 100:
                percent = value

        # 2. Spoken cardinals ("set brightness to fifty"), longest first.
        if percent is None:
            for word, val in sorted(cardinals.items(), key=lambda x: -len(x[0])):
                if re.search(rf"\b{re.escape(word)}\b\s*(?:%|percent)?", clause_lower):
                    percent = val
                    break

        # 3. Pure adjectives — "max/full brightness", "min/lowest brightness".
        if percent is None and re.search(
            r"\b(?:max|maximum|full|highest|brightest)\s+(?:brightness|light)?\b"
            r"|\bbrightness\s+(?:to\s+)?(?:max|maximum|full)\b",
            clause_lower,
        ):
            percent = 100
        if percent is None and re.search(
            r"\b(?:min|minimum|lowest|darkest)\s+(?:brightness|light)?\b"
            r"|\bbrightness\s+(?:to\s+)?(?:min|minimum|lowest)\b"
            r"|\bdim\s+(?:the\s+screen\s+)?all\s+the\s+way\b",
            clause_lower,
        ):
            percent = 0

        # 4. Relative deltas ("brighter" / "darker" with no number) — bump
        # by ±20 from a notional 50% baseline. The handler can refine; we
        # at least take the request out of chat-mode hell.
        if percent is None:
            if re.search(r"\b(?:brighter|raise|increase|lighten|turn\s+up\s+(?:the\s+)?(?:screen|brightness|display))\b", clause_lower):
                percent = 80
            elif re.search(r"\b(?:dimmer|darker|lower|decrease|turn\s+down\s+(?:the\s+)?(?:screen|brightness|display))\b", clause_lower):
                percent = 30

        if percent is None:
            return None

        return {
            "tool": "set_brightness",
            "args": {"percent": percent},
            "text": clause,
            "domain": "brightness",
        }

    def _parse_screen_lock(self, clause, clause_lower, context):
        """Route lock/unlock phrases to the lock capabilities.

        2026-05-23 Step 3 — broadened to cover spoken phrasings the user
        actually says: "lock the computer", "lock my pc", "lock me out",
        "secure the laptop", "step away mode", "going afk".
        """
        tools = getattr(self.router, "_tools_by_name", {})

        if "lock_screen" in tools and re.search(
            r"\block\s+(?:the\s+|my\s+|this\s+)?"
            r"(?:screen|friday|yourself|assistant|console|computer|laptop|pc|machine|desktop|workstation|session)\b"
            r"|\block\s+me\s+(?:out|down)\b"
            r"|\b(?:enable|engage|activate|turn\s+on)\s+(?:screen\s+|the\s+)?lock(?:\s+screen)?\b"
            r"|\bsecure\s+(?:the\s+|my\s+)?(?:computer|laptop|pc|screen|machine|workstation)\b"
            r"|\b(?:step\s+away|away\s+from\s+keyboard)(?:\s+mode)?\b"
            r"|\b(?:going\s+)?afk\b"
            r"|\b(?:i'?m|im)\s+(?:going\s+)?afk\b",
            clause_lower,
        ):
            return {"tool": "lock_screen", "args": {}, "text": clause, "domain": "security"}

        if "unlock_screen" in tools and re.search(
            r"\bunlock\b|\b(?:disable|turn\s+off|deactivate)\s+(?:screen\s+|the\s+)?lock\b"
            r"|\bi'?m\s+back\b",
            clause_lower,
        ):
            # PIN is whatever 3-8 digit number appears anywhere in the
            # clause. Keep it permissive — the handler can ask again if
            # the PIN is empty or doesn't match.
            pin_match = re.search(r"\b(\d{3,8})\b", clause_lower)
            pin = pin_match.group(1) if pin_match else ""
            return {
                "tool": "unlock_screen",
                "args": {"pin": pin},
                "text": clause,
                "domain": "security",
            }
        return None

    def _parse_vision_action(self, clause, clause_lower, context):
        """Route screen-analysis phrases to VLM tools before file parsers can intercept them.

        2026-05-23 Step 4 — added phrasings for the rest of the vision
        plugin: find_ui_element, compare_screenshots, debug_code_screenshot,
        recent_screen_activity, roast_desktop, review_design, explain_meme.
        """
        tools = getattr(self.router, "_tools_by_name", {})

        if "summarize_screen" in tools and re.search(
            r"\bsummarize\s+(?:my\s+|the\s+)?screen\b", clause_lower
        ):
            return {"tool": "summarize_screen", "args": {}, "text": clause, "domain": "screen"}
        if "analyze_screen" in tools and re.search(
            r"\b(?:analyze|explain|check|describe|inspect|look\s+at)\s+(?:my\s+|the\s+)?screen\b",
            clause_lower,
        ):
            return {"tool": "analyze_screen", "args": {}, "text": clause, "domain": "screen"}
        if "read_text_from_image" in tools and re.search(
            r"\bread\s+(?:the\s+|my\s+)?(?:screen|text\s+(?:from|on)\s+(?:the\s+|my\s+)?screen)\b",
            clause_lower,
        ):
            return {"tool": "read_text_from_image", "args": {}, "text": clause, "domain": "screen"}
        if "summarize_screen" in tools and re.search(
            r"\b(?:what\s+am\s+i\s+looking\s+at|give\s+me\s+(?:an?\s+)?(?:summary|overview)\s+of\s+(?:my\s+|the\s+)?screen)\b",
            clause_lower,
        ):
            return {"tool": "summarize_screen", "args": {}, "text": clause, "domain": "screen"}

        # find_ui_element — "where is the submit button" / "find the close X"
        if "find_ui_element" in tools and re.search(
            r"\b(?:where(?:'s|\s+is)|find|locate|point\s+(?:to|out))\s+(?:the\s+)?"
            r"(.+?\s+(?:button|menu|tab|icon|link|field|input|checkbox|toggle))\b",
            clause_lower,
        ):
            m = re.search(
                r"\b(?:where(?:'s|\s+is)|find|locate|point\s+(?:to|out))\s+(?:the\s+)?(.+)$",
                clause_lower,
            )
            target = m.group(1).strip(" .!?") if m else ""
            return {
                "tool": "find_ui_element",
                "args": {"target": target} if target else {},
                "text": clause,
                "domain": "vision",
            }

        # compare_screenshots
        if "compare_screenshots" in tools and re.search(
            r"\bcompare\s+(?:these\s+|the\s+|my\s+)?(?:two\s+)?screenshots?\b"
            r"|\b(?:what(?:'s|\s+is)?\s+(?:the\s+)?diff(?:erence)?|spot\s+the\s+diff(?:erence)?)\s+"
            r"between\s+(?:these\s+|the\s+)?screenshots?\b"
            r"|\bdiff\s+(?:my\s+|the\s+)?screenshots?\b",
            clause_lower,
        ):
            return {"tool": "compare_screenshots", "args": {}, "text": clause, "domain": "vision"}

        # debug_code_screenshot — "debug this code", "why is this broken"
        if "debug_code_screenshot" in tools and re.search(
            r"\b(?:debug|fix|what(?:'s|\s+is)\s+wrong\s+with|why\s+(?:is|does))\s+"
            r"(?:this\s+|my\s+|the\s+)?(?:code|script|program|error)\b"
            r"|\bdebug\s+(?:my\s+|the\s+)?screen(?:shot)?\b",
            clause_lower,
        ):
            return {"tool": "debug_code_screenshot", "args": {}, "text": clause, "domain": "vision"}

        # recent_screen_activity
        if "recent_screen_activity" in tools and re.search(
            r"\b(?:what(?:'ve|\s+have)\s+i\s+been\s+(?:doing|working\s+on)|"
            r"recent\s+(?:screen\s+)?activity|"
            r"what\s+did\s+i\s+just\s+(?:do|see|look\s+at)|"
            r"my\s+recent\s+activity)\b",
            clause_lower,
        ):
            return {"tool": "recent_screen_activity", "args": {}, "text": clause, "domain": "vision"}

        # roast_desktop
        if "roast_desktop" in tools and re.search(
            r"\broast\s+(?:my\s+|the\s+)?(?:desktop|screen|setup|wallpaper|workspace)\b",
            clause_lower,
        ):
            return {"tool": "roast_desktop", "args": {}, "text": clause, "domain": "vision"}

        # review_design
        if "review_design" in tools and re.search(
            r"\breview\s+(?:my\s+|the\s+)?(?:design|ui|ux|interface|mockup|wireframe)\b"
            r"|\b(?:critique|feedback\s+on)\s+(?:my\s+|the\s+)?(?:design|ui|mockup)\b",
            clause_lower,
        ):
            return {"tool": "review_design", "args": {}, "text": clause, "domain": "vision"}

        # explain_meme
        if "explain_meme" in tools and re.search(
            r"\bexplain\s+(?:this\s+|the\s+)?meme\b"
            r"|\bwhat(?:'s|\s+is)\s+(?:this|the)\s+meme\b"
            r"|\bi\s+don'?t\s+get\s+(?:this|the)\s+meme\b",
            clause_lower,
        ):
            return {"tool": "explain_meme", "args": {}, "text": clause, "domain": "vision"}

        # describe_image — generic "describe this image / picture"
        if "describe_image" in tools and re.search(
            r"\bdescribe\s+(?:this\s+|the\s+|my\s+)?(?:image|picture|photo|pic|screenshot)\b"
            r"|\bwhat(?:'s|\s+is)\s+in\s+(?:this\s+|the\s+|my\s+)?(?:image|picture|photo)\b",
            clause_lower,
        ):
            return {"tool": "describe_image", "args": {}, "text": clause, "domain": "vision"}

        return None

    def _parse_query_document(self, clause, clause_lower, context):
        """Route document questions to query_document when an active document is in context.

        Track 1.4c (Consolidation Direction): consults the session
        reference store directly instead of looking for a text-injected
        `[active_document=<path>]` prefix. The previous injection
        mechanism is gone; this parser is self-sufficient.
        """
        if "query_document" not in getattr(self.router, "_tools_by_name", {}):
            return None
        store = getattr(self.router, "context_store", None)
        session_id = getattr(self.router, "session_id", "")
        if store is None or not session_id:
            return None
        try:
            active_doc = store.get_reference(session_id, "active_document") or ""
        except Exception:
            active_doc = ""
        if not active_doc:
            return None
        # If the text already names a concrete file path, defer to file-
        # action parsers — they'll route to read_file / open_file with the
        # explicit target. The active-document fallback only fires when
        # the user is talking about "this document" / "the file" / etc.
        if re.search(r"[/~\\][^\s]+\.[a-zA-Z]{1,6}", clause):
            return None
        if re.search(
            r"\b(?:what|how|who|when|where|why|find|explain|summarize|summarise|"
            r"tell\s+me|search|locate|query|list|show|describe|define)\b",
            clause_lower,
        ):
            return {"tool": "query_document", "args": {}, "text": clause, "domain": "document"}
        return None

    def _parse_email_action(self, clause, clause_lower, context):
        """Route email/inbox commands to workspace capabilities before generic parsers fire."""
        tools = getattr(self.router, "_tools_by_name", {})

        if "summarize_inbox" in tools and re.search(
            r"\b(?:summarize|summary\s+of|digest|overview\s+of)\s+(?:my\s+|the\s+)?(?:emails?|inbox|mails?|messages?)\b"
            r"|\bemail\s+(?:summary|digest|overview)\b"
            r"|\binbox\s+(?:summary|digest|overview)\b"
            r"|\bwhat(?:'s|\s+is)\s+in\s+(?:my\s+)?(?:inbox|emails?)\b"
            r"|\bgive\s+me\s+(?:a\s+)?(?:summary|digest|overview)\s+of\s+(?:my\s+)?(?:emails?|inbox|mails?)\b",
            clause_lower,
        ):
            return {"tool": "summarize_inbox", "args": {}, "text": clause, "domain": "email"}

        if "check_unread_emails" in tools and re.search(
            r"\b(?:check|show|list|get|any)\s+(?:my\s+)?(?:unread\s+)?(?:emails?|inbox|mails?|messages?)\b"
            r"|\b(?:unread|new)\s+(?:emails?|messages?|mails?)\b"
            r"|\bdo\s+i\s+have\s+(?:any\s+)?(?:emails?|messages?|mails?)\b"
            r"|\bhow\s+many\s+(?:unread\s+)?(?:emails?|messages?|mails?)\b",
            clause_lower,
        ):
            return {"tool": "check_unread_emails", "args": {}, "text": clause, "domain": "email"}

        if "read_latest_email" in tools and re.search(
            r"\bread\s+(?:my\s+)?(?:latest|last|most\s+recent|newest|top|first)\s+(?:unread\s+)?(?:email|message|mail)\b"
            r"|\b(?:what(?:'s|\s+is)\s+(?:my\s+)?latest\s+(?:email|message|mail)|read\s+(?:the\s+)?latest\s+(?:email|message|mail))\b",
            clause_lower,
        ):
            return {"tool": "read_latest_email", "args": {}, "text": clause, "domain": "email"}

        if "daily_briefing" in tools and re.search(
            r"\b(?:daily\s+briefing|morning\s+briefing|daily\s+update|morning\s+update|brief\s+me|give\s+me\s+(?:a\s+)?(?:daily\s+)?briefing)\b",
            clause_lower,
        ):
            return {"tool": "daily_briefing", "args": {}, "text": clause, "domain": "email"}

        return None

    def _parse_news_action(self, clause, clause_lower, context):
        """Route Feed Prism news commands using natural category language.

        World monitor is disabled. All category terms ("tech news", "global news",
        "briefing", etc.) route directly to Feed Prism tools.
        Note: "daily briefing" / "morning briefing" / "brief me" are handled by
        _parse_email_action (runs earlier) and will not reach this parser.
        """
        tools = getattr(self.router, "_tools_by_name", {})

        # ── Technology (TechCrunch, The Verge, Wired) ──────────────────────────
        if "get_technology_news" in tools and re.search(
            r"\b(?:"
            r"tech(?:nology)?\s+news|"
            r"tech(?:nology)?\s+(?:articles?|stories|headlines?|updates?)|"
            r"latest\s+(?:tech(?:nology)?|technology)(?:\s+news)?|"
            r"techcrunch|the\s+verge\b|wired\b"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_technology_news", "args": {}, "text": clause, "domain": "news"}

        # ── Global news (Al Jazeera, BBC World, NPR) ──────────────────────────
        if "get_global_news_feed" in tools and re.search(
            r"\b(?:"
            r"global\s+news|world\s+news|international\s+news|"
            r"latest\s+(?:global|world|international)\s+news|"
            r"al\s+jazeera|bbc\s+(?:world|news)|npr(?:\s+news)?\b"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_global_news_feed", "args": {}, "text": clause, "domain": "news"}

        # ── Company news (Google Blog, Apple Newsroom) ─────────────────────────
        if "get_company_news" in tools and re.search(
            r"\b(?:"
            r"company\s+news|corporate\s+news|"
            r"(?:google|apple)\s+(?:newsroom|blog|news|announcements?)|"
            r"big\s+(?:company|tech)\s+news"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_company_news", "args": {}, "text": clause, "domain": "news"}

        # ── Startup news (Product Hunt) ─────────────────────────────────────────
        if "get_startup_news" in tools and re.search(
            r"\b(?:"
            r"startup\s+(?:news|stories|launches?|updates?)|"
            r"product\s+hunt(?:\s+(?:news|launches?|picks?|today))?|"
            r"(?:new|latest|top)\s+startups?"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_startup_news", "args": {}, "text": clause, "domain": "news"}

        # ── Security news (The Hacker News Security) ───────────────────────────
        if "get_security_news" in tools and re.search(
            r"\b(?:"
            r"(?:cyber)?security\s+news|cyber\s+news|"
            r"(?:latest|top|recent)\s+(?:cyber)?security(?:\s+news)?|"
            r"the\s+hacker\s+news|hacker\s+news\s+security|"
            r"cyber(?:security)?\s+(?:threats?|breaches?|attacks?|alerts?)"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_security_news", "args": {}, "text": clause, "domain": "news"}

        # ── Business news (Forbes Business) ────────────────────────────────────
        if "get_business_news" in tools and re.search(
            r"\b(?:"
            r"business\s+news|finance\s+news|financial\s+news|market\s+news|"
            r"(?:latest|top|recent)\s+business(?:\s+news)?|"
            r"forbes(?:\s+(?:news|business))?|bloomberg(?:\s+(?:news|business))?|"
            r"cnbc(?:\s+(?:news|business))?"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_business_news", "args": {}, "text": clause, "domain": "news"}

        # ── Cumulative briefing — all Feed Prism categories ────────────────────
        if "get_news_briefing" in tools and re.search(
            r"\b(?:"
            r"news\s+(?:briefing|brief\b|summary|roundup|feed|aggregat(?:ion|ed|or)|compilation)|"
            r"(?:give\s+me\s+(?:the|a)|get\s+(?:the|a)|what(?:'s|\s+is)\s+(?:the\s+)?)\s*news\b|"
            r"(?:all|full|complete|cumulative|combined|aggregated)\s+news|"
            r"news\s+from\s+all\s+(?:categories|sources)|"
            r"today(?:'s)?\s+news|"
            r"feed\s+prism\s+(?:briefing|news)"
            r")\b",
            clause_lower,
        ):
            return {"tool": "get_news_briefing", "args": {}, "text": clause, "domain": "news"}

        # ── World monitor (2026-05-23) ────────────────────────────────────
        if "get_world_monitor_news" in tools and re.search(
            r"\bworld\s+monitor\b"
            r"|\bglobal\s+(?:monitor|tracker|watch)\s+news\b"
            r"|\bworld\s+(?:news\s+)?monitor(?:ing)?\b",
            clause_lower,
        ):
            return {"tool": "get_world_monitor_news", "args": {}, "text": clause, "domain": "news"}

        return None

    def _parse_file_action(self, clause, clause_lower, context):
        active_file = self._active_file_reference()
        pending = getattr(getattr(self.router, "dialog_state", None), "pending_file_request", None)
        # Multi-action on the pending file: "open and read it", "read and summarize it".
        # Prefer the most informative downstream verb so a single tool fires; the
        # file controller still picks up secondary verbs from text via _detect_requested_actions.
        if pending and re.search(
            r"\b(?:open|read|summarize)\s+and\s+(?:open|read|summarize)\s+(?:it|this|that|the file|to me|out loud)\b",
            clause_lower,
        ):
            if "summarize" in clause_lower:
                return {"tool": "summarize_file", "args": {}, "text": clause, "domain": "files"}
            if "read" in clause_lower:
                return {"tool": "read_file", "args": {}, "text": clause, "domain": "files"}
            return {"tool": "open_file", "args": {}, "text": clause, "domain": "files"}
        if pending and re.search(r"\bopen\s+(?:it|this|that|the file)\b", clause_lower):
            return {"tool": "open_file", "args": {}, "text": clause, "domain": "files"}
        if pending and re.search(r"\bread\s+(?:it|this|that|the file)\b", clause_lower):
            return {"tool": "read_file", "args": {}, "text": clause, "domain": "files"}
        if pending and re.search(r"\bsummarize\s+(?:it|this|that|the file)\b", clause_lower):
            return {"tool": "summarize_file", "args": {}, "text": clause, "domain": "files"}

        if re.search(r"\b(?:which one|pick|choose|select|option\s+\d+)\b", clause_lower):
            return {"tool": "select_file_candidate", "args": {}, "text": clause, "domain": "files"}

        if re.search(r"\b(?:what are|list|show)\b.*\b(?:other\s+)?files?\b", clause_lower):
            return {"tool": "list_folder_contents", "args": {}, "text": clause, "domain": "files"}

        if re.search(r"\b(?:summarize|summary of|sum up)\b", clause_lower):
            if not re.search(
                r"\b(?:screen|display|desktop|monitor|email|emails|inbox|mail|messages?|"
                r"calendar|event|meeting|appointment|news|briefing|reminder|schedule|today)\b",
                clause_lower,
            ):
                return {"tool": "summarize_file", "args": {}, "text": clause, "domain": "files"}

        if re.search(r"\b(?:read|show contents of|preview)\b", clause_lower) and (
            "file" in clause_lower or "folder" in clause_lower or "it" in clause_lower or context.get("domain") == "files"
        ):
            # Don't intercept calendar/reminder/news reads
            if not re.search(
                r"\b(?:calendar|event|meeting|appointment|reminder|schedule|news|briefing)\b",
                clause_lower,
            ):
                return {"tool": "read_file", "args": {}, "text": clause, "domain": "files"}

        if re.search(r"\bopen\s+(?:the\s+)?folder\b", clause_lower):
            return {"tool": "open_folder", "args": {}, "text": clause, "domain": "files"}

        if re.search(r"\bopen\s+(?:the\s+)?(?:file\s+[a-z0-9][a-z0-9 _\-.]*|[a-z0-9][a-z0-9 _\-.]*\s+file)\b", clause_lower):
            return {"tool": "open_file", "args": {}, "text": clause, "domain": "files"}

        if "folder" in clause_lower and "open" in clause_lower:
            return {"tool": "open_file", "args": {}, "text": clause, "domain": "files"}

        if active_file:
            names = {active_file["filename"], active_file["stem"]}
            if re.search(r"\bopen\b", clause_lower) and any(name and re.search(rf"\b{re.escape(name)}\b", clause_lower) for name in names):
                return {"tool": "open_file", "args": {"filename": active_file["filename"]}, "text": clause, "domain": "files"}
            if re.search(r"\bread\b", clause_lower) and any(name and re.search(rf"\b{re.escape(name)}\b", clause_lower) for name in names):
                return {"tool": "read_file", "args": {"filename": active_file["filename"]}, "text": clause, "domain": "files"}
            if re.search(r"\bsummarize\b", clause_lower) and any(name and re.search(rf"\b{re.escape(name)}\b", clause_lower) for name in names):
                return {"tool": "summarize_file", "args": {"filename": active_file["filename"]}, "text": clause, "domain": "files"}

        # "open <file.ext>" always routes to open_file; bare "open it" only matches
        # when there is an active file or a pending file request so context-free
        # pronouns ("open it" after "the YouTube tab closed") fall through to the LLM.
        if re.search(r"\bopen\b", clause_lower) and re.search(r"\b(?:pdf|txt|md|json|csv|py|docx)\b", clause_lower):
            return {"tool": "open_file", "args": {}, "text": clause, "domain": "files"}
        if re.search(r"\bopen\b", clause_lower) and "it" in clause_lower and (active_file or pending):
            return {"tool": "open_file", "args": {}, "text": clause, "domain": "files"}

        # Require explicit "file" keyword to avoid intercepting "find a solution",
        # "search for news", "locate my friend", etc.
        if re.search(r"\b(?:find|search|locate)\b", clause_lower) and (
            "file" in clause_lower
            or re.search(r"\.[a-z]{2,4}\b", clause_lower)  # has file extension
        ):
            return {"tool": "search_file", "args": {}, "text": clause, "domain": "files"}
        file_phrase = re.fullmatch(r"file\s+(.+)", clause_lower)
        if file_phrase:
            return {
                "tool": "search_file",
                "args": {"query": file_phrase.group(1).strip()},
                "text": clause,
                "domain": "files",
            }
        if self._should_recover_file_reference(clause_lower, context):
            return {
                "tool": "search_file",
                "args": {"query": clause.strip()},
                "text": clause,
                "domain": "files",
            }
        return None

    def _parse_manage_file(self, clause, clause_lower, context):
        if "manage_file" not in getattr(self.router, "_tools_by_name", {}):
            return None
        # Hard guard: calendar/reminder/note phrases must never be intercepted here.
        # These have their own dedicated parsers that run earlier; this guard
        # is a safety net so the ordering can never silently revert this fix.
        if re.search(
            r"\b(?:calendar\s+event|event|meeting|appointment|reminder|reminders?)\b",
            clause_lower,
        ):
            return None
        if not re.search(r"\b(?:create|make|write|save|append|add)\b", clause_lower):
            return None

        action = "create"
        if re.search(r"\b(?:append|add)\b", clause_lower):
            action = "append"
        elif re.search(r"\b(?:write|save)\b", clause_lower):
            action = "write"

        filename = ""
        det = r"(?:(?:the|a|an|new)\s+)?"
        patterns = (
            rf"\b(?:to|into|in)\s+{det}file\s+(?:named\s+|called\s+)?([a-z0-9][a-z0-9 _\-.]*)$",
            rf"\b(?:to|into|in)\s+{det}([a-z0-9][a-z0-9 _\-.]*)\s+file$",
            r"\b(?:file\s+)?(?:named|called)\s+([a-z0-9][a-z0-9 _\-.]*)$",
            rf"\b(?:create|make)\s+{det}file\s+(?:named\s+|called\s+)?([a-z0-9][a-z0-9 _\-.]*)$",
            rf"\b(?:to|into|in)\s+{det}(?!file\b|document\b)([a-z0-9][a-z0-9 _\-]*\.(?:pdf|txt|md|json|csv|py|docx))$",
            rf"\b(?:to|into|in)\s+{det}(?!file\b|document\b)([a-z0-9][a-z0-9 _\-]+?\s+(?:pdf|txt|md|json|csv|py|docx))$",
        )
        for pattern in patterns:
            match = re.search(pattern, clause_lower)
            if match:
                filename = " ".join(match.group(1).strip(" .,!?:;\"'").split())
                break

        if not filename:
            # Only use the active-file reference when the user explicitly
            # refers back to it ("add this to it", "append to the file").
            # A bare "add <something>" without any file pronoun or the word
            # "file" must NOT silently grab the last selected file — that
            # causes "add a calendar event" to update a screenshot.
            has_file_ref = bool(re.search(
                r"\b(?:it|that|this\s+file|the\s+file|same\s+file|the\s+same|to\s+it)\b",
                clause_lower,
            ) or "file" in clause_lower or "document" in clause_lower)
            active_file = self._active_file_reference()
            if active_file and action in {"write", "append"} and has_file_ref:
                filename = active_file["filename"]
            elif context.get("domain") == "files" and action in {"write", "append"} and has_file_ref:
                return {
                    "tool": "manage_file",
                    "args": {"action": action},
                    "text": clause,
                    "domain": "files",
                }
            else:
                return None

        return {
            "tool": "manage_file",
            "args": {"action": action, "filename": filename},
            "text": clause,
            "domain": "files",
        }

    def _parse_reminder(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})

        if "create_calendar_event" in tools and re.search(
            r"\b(?:create|add|schedule|set\s+up|book)\b.*\b(?:calendar\s+event|event|meeting|appointment)\b",
            clause_lower,
        ):
            return {"tool": "create_calendar_event", "args": {}, "text": clause, "domain": "calendar"}
        if "create_calendar_event" in tools and re.search(
            r"\badd\s+(?:.+?)\s+to\s+(?:my\s+)?calendar\b",
            clause_lower,
        ):
            return {"tool": "create_calendar_event", "args": {}, "text": clause, "domain": "calendar"}

        # Reschedule/move now routes to the Google Calendar update handler
        # (2026-05-31: the local move_calendar_event capability was removed; the
        # WorkspaceAgent's update_calendar_event was built for exactly this
        # "move my 3pm to 4pm" phrasing). Gated on the Google capability being
        # loaded, so these no-op cleanly when the workspace agent is absent.
        if "update_calendar_event" in tools and re.search(
            r"\b(?:move|reschedule|shift|push|change)\b.*\b(?:reminder|event|meeting|appointment|standup|gym|focus|block|the\s+next|the\s+\d{1,2}(?:\s*(?:am|pm))?)\b.*\b(?:to|by|until|forward|back|ahead|earlier|later)\b",
            clause_lower,
        ):
            return {"tool": "update_calendar_event", "args": {}, "text": clause, "domain": "calendar"}
        # "move my 3 PM to 4 PM", "shift my 9 AM by an hour" — clock-time targets.
        if "update_calendar_event" in tools and re.search(
            r"\b(?:move|reschedule|shift|push|change)\s+(?:my\s+|the\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+(?:to|by)\b",
            clause_lower,
        ):
            return {"tool": "update_calendar_event", "args": {}, "text": clause, "domain": "calendar"}
        if "update_calendar_event" in tools and re.search(
            r"\b(?:move|reschedule|shift|push|change)\s+(?:the\s+|my\s+)?(?:next|upcoming)\b",
            clause_lower,
        ):
            return {"tool": "update_calendar_event", "args": {}, "text": clause, "domain": "calendar"}

        if "cancel_calendar_event" in tools and re.search(
            r"\b(?:cancel|delete|remove|drop)\b.*\b(?:reminder|calendar\s+event|event|meeting|appointment|block|standup|gym\s+block|focus\s+block)\b",
            clause_lower,
        ):
            return {"tool": "cancel_calendar_event", "args": {}, "text": clause, "domain": "calendar"}

        if "remind me" in clause_lower or re.search(r"\bset (?:a )?reminder\b", clause_lower):
            return {"tool": "set_reminder", "args": {}, "text": clause, "domain": "reminder"}

        # ── Listing path (2026-05-23 audit) ───────────────────────────
        # User log: "What's on my list today?" routed to chat and the
        # LLM fabricated a pep talk instead of calling the calendar tool.
        list_calendar_today_re = (
            r"\bwhat'?s?\s+(?:on\s+(?:my\s+)?(?:list|schedule|agenda|calendar|plate)|"
            r"my\s+(?:agenda|schedule))\s+(?:today|for\s+today)\b"
            r"|\bwhat\s+do\s+i\s+have\s+(?:today|on\s+today|going\s+on\s+today)\b"
            r"|\bshow\s+(?:me\s+)?(?:my\s+)?(?:agenda|schedule|calendar)\s+(?:for\s+)?today\b"
            r"|\btoday'?s?\s+(?:agenda|schedule|events?|calendar)\b"
        )
        if "get_calendar_today" in tools and re.search(list_calendar_today_re, clause_lower):
            return {"tool": "get_calendar_today", "args": {}, "text": clause, "domain": "calendar"}

        list_calendar_week_re = (
            r"\bwhat'?s?\s+on\s+(?:my\s+)?(?:list|schedule|agenda|calendar)\s+this\s+week\b"
            r"|\bthis\s+week'?s?\s+(?:agenda|schedule|events|calendar)\b"
            r"|\bshow\s+(?:me\s+)?(?:my\s+)?(?:agenda|schedule|calendar)\s+"
            r"(?:for\s+)?(?:this\s+|the\s+)?week\b"
        )
        if "get_calendar_week" in tools and re.search(list_calendar_week_re, clause_lower):
            return {"tool": "get_calendar_week", "args": {}, "text": clause, "domain": "calendar"}

        list_reminders_re = (
            r"\b(?:show|list|what(?:'s|\s+are)?)\s+(?:my\s+)?reminders?\b"
            r"|\bwhat\s+reminders?\s+do\s+i\s+have\b"
            r"|\bdo\s+i\s+have\s+any\s+reminders?\b"
        )
        if "list_reminders" in tools and re.search(list_reminders_re, clause_lower):
            return {"tool": "list_reminders", "args": {}, "text": clause, "domain": "reminder"}

        return None

    # ── Security tools (Phase 1: nmap-backed) ──────────────────────────
    # Gated at the capability handler by `authorized_scopes` — if the
    # target isn't in the configured allowlist, the tool refuses. The
    # intent parser only routes; it does NOT bypass any safety gate.
    _IP_OR_HOST = (
        r"(?:"
        r"(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?"          # IPv4 or CIDR
        r"|[a-z0-9][a-z0-9\-]*(?:\.[a-z][a-z0-9\-]+)+"   # FQDN
        r")"
    )

    def _parse_security(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})

        if "host_service_scan" in tools:
            m = re.search(
                rf"\b(?:scan|port\s+scan|service\s+scan|nmap)\s+(?:host\s+|target\s+)?({self._IP_OR_HOST})"
                rf"(?:\s+(?:for\s+(?:open\s+)?(?:ports?|services?)|with\s+nmap))?",
                clause_lower,
            )
            if m:
                return {
                    "tool": "host_service_scan",
                    "args": {"target": m.group(1)},
                    "text": clause,
                    "domain": "security",
                }

        if "ping_sweep" in tools:
            m = re.search(
                rf"\b(?:ping\s+sweep|sweep|discover|enumerate)\s+(?:network\s+|subnet\s+|cidr\s+)?({self._IP_OR_HOST})",
                clause_lower,
            )
            if m:
                return {
                    "tool": "ping_sweep",
                    "args": {"target": m.group(1)},
                    "text": clause,
                    "domain": "security",
                }

        # DNS enumeration (Phase 2) ---------------------------------------
        if "dns_enum_owned_domain" in tools:
            m = re.search(
                r"\b(?:dns\s+(?:enum(?:erate|eration)?|recon|scan)|enumerate\s+dns|"
                r"(?:subdomain|sub-domain)\s+(?:scan|enum(?:eration)?|discovery))\s+"
                r"(?:on\s+|for\s+|of\s+)?([a-z0-9][a-z0-9\-]*(?:\.[a-z][a-z0-9\-]+)+)",
                clause_lower,
            )
            if m:
                return {
                    "tool": "dns_enum_owned_domain",
                    "args": {"domain": m.group(1)},
                    "text": clause,
                    "domain": "security",
                }

        # Web directory / fuzzing (Phase 2) -------------------------------
        if "web_directory_enum" in tools:
            m = re.search(
                r"\b(?:fuzz|brute(?:force)?|enumerate|dirb(?:uster)?|gobuster|ffuf|"
                r"directory\s+(?:scan|enum(?:eration)?|fuzz)|web\s+(?:dir|path)\s+(?:scan|enum))\s+"
                r"(?:on\s+|for\s+|against\s+)?(https?://[^\s]+|[a-z0-9][a-z0-9\-]*(?:\.[a-z][a-z0-9\-]+)+)",
                clause_lower,
            )
            if m:
                return {
                    "tool": "web_directory_enum",
                    "args": {"target": m.group(1).rstrip(".,;:!?")},
                    "text": clause,
                    "domain": "security",
                }

        # Compare scan results --------------------------------------------
        if "compare_scan_results" in tools and re.search(
            r"\bcompare\s+(?:the\s+|my\s+)?(?:last|previous|recent)?"
            r"(?:\s+(?:two|three|few))?\s*(?:scan\s+results?|scans?)\b"
            r"|\bdiff(?:erence)?\s+(?:between\s+)?(?:the\s+)?(?:scans?|scan\s+results?)\b"
            r"|\bwhat\s+changed\s+(?:between\s+|since)\s+(?:the\s+)?(?:last\s+)?scan\b",
            clause_lower,
        ):
            return {
                "tool": "compare_scan_results",
                "args": {},
                "text": clause,
                "domain": "security",
            }

        # Generate security report ----------------------------------------
        if "security_report_generate" in tools and re.search(
            r"\b(?:generate|create|write|build|make)\s+(?:a\s+|the\s+)?"
            r"(?:security|recon|pentest|scan)\s+report\b"
            r"|\b(?:write\s+up|export)\s+(?:the\s+|my\s+)?(?:security|recon|scan)\s+(?:report|findings|results)\b",
            clause_lower,
        ):
            return {
                "tool": "security_report_generate",
                "args": {},
                "text": clause,
                "domain": "security",
            }
        return None

    # Affirmation phrasings that confirm a pending destructive action. Kept
    # broad on the YES side (the prompt says "say yes to confirm, or anything
    # else to cancel") so a hesitant non-answer safely cancels.
    _DESTRUCTIVE_AFFIRM_RE = re.compile(
        r"\b(?:yes|yeah|yep|yup|sure|ok|okay|confirm(?:ed)?|affirmative|"
        r"go\s+ahead|do\s+it|please\s+do|proceed|absolutely|definitely|"
        r"that'?s\s+right|correct)\b",
        re.IGNORECASE,
    )

    def _parse_pending_destructive(self, clause, clause_lower, context):
        """Intercept the yes/no turn for any armed destructive action.

        While :class:`core.workflows.confirmation.ConfirmationGuard` has an
        action stashed in session state, this parser fires first and routes
        an affirmation to ``confirm_pending_action`` (anything else →
        ``cancel_pending_action``). It does NOT clear the pending flag — the
        guard's ``confirm``/``cancel`` own that — so a single source clears
        it and the flag can't go stale (both branches resolve it this turn).
        """
        cs = getattr(self.router, "context_store", None)
        session_id = getattr(self.router, "session_id", None)
        if not cs or not session_id:
            return None
        try:
            state = cs.get_session_state(session_id) or {}
        except Exception:
            return None
        if not state.get("pending_destructive_action"):
            return None
        tools = getattr(self.router, "_tools_by_name", {})
        if self._DESTRUCTIVE_AFFIRM_RE.search(clause_lower):
            if "confirm_pending_action" in tools:
                return {
                    "tool": "confirm_pending_action", "args": {},
                    "text": clause, "domain": "confirmation",
                }
        if "cancel_pending_action" in tools:
            return {
                "tool": "cancel_pending_action", "args": {},
                "text": clause, "domain": "confirmation",
            }
        return None

    def _parse_pending_pick(self, clause, clause_lower, context):
        """Intercept the selection turn for an armed disambiguation pick.

        While :class:`core.workflows.disambiguation.DisambiguationGuard` has a
        pick stashed in session state, a selection-shaped utterance ("2", "the
        second one", a candidate's name) routes to ``pick_pending_candidate``
        and a clear "cancel"/"never mind" routes to ``cancel_pending_pick``.
        Anything that does NOT look like a selection falls through to normal
        routing — so a user who changes their mind ("actually, what's the
        weather?") isn't trapped; the stale pick is harmless and is overwritten
        or cleared by the next arm/pick/cancel.
        """
        cs = getattr(self.router, "context_store", None)
        session_id = getattr(self.router, "session_id", None)
        if not cs or not session_id:
            return None
        try:
            state = cs.get_session_state(session_id) or {}
        except Exception:
            return None
        pending = state.get("pending_pick")
        if not isinstance(pending, dict):
            return None
        tools = getattr(self.router, "_tools_by_name", {})
        if _PICK_CANCEL_RE.search(clause_lower):
            if "cancel_pending_pick" in tools:
                return {
                    "tool": "cancel_pending_pick", "args": {},
                    "text": clause, "domain": "disambiguation",
                }
            return None
        labels = [
            c.get("label", "") for c in pending.get("candidates", [])
            if isinstance(c, dict)
        ]
        if _pick_looks_like_selection(clause_lower, labels):
            if "pick_pending_candidate" in tools:
                return {
                    "tool": "pick_pending_candidate", "args": {},
                    "text": clause, "domain": "disambiguation",
                }
        return None

    _WIPE_CONFIRM_RE = re.compile(
        r"\byes\b.{0,30}\bwipe\b.{0,20}\beverything\b", re.IGNORECASE
    )

    def _parse_pending_wipe(self, clause, clause_lower, context):
        """Intercept the confirmation turn for a pending memory-wipe request.

        Reads the session state to see if wipe_memory_init was triggered on
        the previous turn. If so, this parser fires first and routes to
        confirm_memory_wipe or cancel_memory_wipe regardless of other patterns.
        Clears the pending flag in either branch to avoid sticky state.
        """
        cs = getattr(self.router, "context_store", None)
        session_id = getattr(self.router, "session_id", None)
        if not cs or not session_id:
            return None
        try:
            state = cs.get_session_state(session_id) or {}
        except Exception:
            return None
        if not state.get("pending_memory_wipe"):
            return None
        state.pop("pending_memory_wipe", None)
        try:
            cs.save_session_state(session_id, state)
        except Exception:
            pass
        tools = getattr(self.router, "_tools_by_name", {})
        if self._WIPE_CONFIRM_RE.search(clause_lower):
            if "confirm_memory_wipe" in tools:
                return {"tool": "confirm_memory_wipe", "args": {}, "text": clause, "domain": "memory"}
        if "cancel_memory_wipe" in tools:
            return {"tool": "cancel_memory_wipe", "args": {}, "text": clause, "domain": "memory"}
        return None

    def _parse_notes(self, clause, clause_lower, context):
        if re.search(
            r"\b(?:save\s+(?:a\s+)?note|note\s+(?:down|this|that)|remember\s+(?:this|that)|"
            r"jot\s+(?:this\s+|that\s+|it\s+)?down|(?:make|take)\s+(?:a\s+)?(?:quick\s+)?note|"
            r"add\s+to\s+(?:my\s+)?notes?|keep\s+(?:this|that)\s+in\s+(?:your|my)\s+notes?)\b",
            clause_lower,
        ):
            return {"tool": "save_note", "args": {}, "text": clause, "domain": "notes"}
        # read_notes: allow "show me my notes" (filler "me") and "what are my
        # notes" / "what notes do I have" interrogatives (2026-05-30 fix).
        if re.search(
            r"\b(?:read|show|list)\s+(?:me\s+)?(?:my\s+)?notes\b"
            r"|\bwhat\s+(?:are|were)\s+(?:my\s+)?notes\b"
            r"|\bwhat\s+notes\s+do\s+i\s+have\b",
            clause_lower,
        ):
            return {"tool": "read_notes", "args": {}, "text": clause, "domain": "notes"}
        return None

    # Mapping from natural-language nouns to canonical memory keys
    # used by `MemoryFacade.forget`. Order matters: longer phrases first.
    _FORGET_KEY_ALIASES = (
        (re.compile(r"\b(?:love|like|enjoy|prefer)(?:s|d|ed)?\s+for\b", re.IGNORECASE), "loves"),
        (re.compile(r"\bthat\s+i\s+(?:love|loved)\b", re.IGNORECASE), "loves"),
        (re.compile(r"\bthat\s+i\s+(?:like|liked)\b", re.IGNORECASE), "likes"),
        (re.compile(r"\bthat\s+i\s+(?:hate|hated|dislike|disliked)\b", re.IGNORECASE), "dislikes"),
        (re.compile(r"\bthat\s+i\s+(?:prefer|preferred)\b", re.IGNORECASE), "preferences"),
        (re.compile(r"\bthat\s+i'?m\s+(?:a|an)\b", re.IGNORECASE), "role"),
        (re.compile(r"\bwhere\s+i\s+(?:live|am\s+from)\b", re.IGNORECASE), "location"),
        (re.compile(r"\bmy\s+(love|loves|like|likes|dislike|dislikes|preference|preferences|"
                    r"name|location|hometown|city|email|phone|birthday|role|job|profession)\b",
                    re.IGNORECASE), None),  # captured group 1 is the key
    )

    def _extract_forget_target(self, clause_lower: str):
        """Return the memory key the user wants to forget, or None.

        Recognises:
          • "forget my <field>"      → field
          • "forget my love for X"   → "loves"
          • "forget that I love X"   → "loves"
          • "forget where I live"    → "location"
          • bare "forget that"       → "*" (handler treats this as "no
            specific key" and re-asks)
        """
        if not re.search(r"\bforget\b", clause_lower):
            return None
        # Anti-poach: "forget it" / "forget about it" / "forget everything"
        # belong to other parsers (pending-wipe confirmation, wipe init).
        if re.search(r"\bforget\s+(?:it|about\s+it|everything|all)\b", clause_lower):
            return None
        for pattern, canonical in self._FORGET_KEY_ALIASES:
            m = pattern.search(clause_lower)
            if not m:
                continue
            if canonical is not None:
                return canonical
            # The fallback pattern captures the noun directly.
            key = m.group(1).lower()
            # Normalise plurals → canonical singular form used by
            # MemoryFacade._PROFILE_KEYS.
            aliases = {
                "love": "loves", "loves": "loves",
                "like": "likes", "likes": "likes",
                "dislike": "dislikes", "dislikes": "dislikes",
                "preference": "preferences", "preferences": "preferences",
                "hometown": "location", "city": "location",
                "job": "role", "profession": "role",
            }
            return aliases.get(key, key)
        return None

    # ── Step 4 (2026-05-23) ─────────────────────────────────────────────
    # Long-tail parsers for the unwired user-facing capabilities. Each
    # block follows the same shape: tool-presence guard, narrow regex,
    # canonical action dict. Each has anti-poach guards where the verb
    # otherwise overlaps a more specific tool.

    # ── Step 5a (2026-05-24) — ported source tools ──────────────────────
    #
    # Each clause is checked against:
    #   • wikipedia_summary / wikipedia_search — "wikipedia X", "wiki <topic>"
    #   • arxiv_search — "arxiv <topic>", "papers on <topic>", "arxiv ID lookup"
    #   • hackernews_top / hackernews_search — "hacker news", "what's on hn",
    #                                            "hn search for X"
    #   • pubmed_search — "pubmed <topic>", "medical papers on <topic>"
    #   • newspaper_extract — already covered by `_parse_web_url_action`
    #                          (web_extract); this parser only activates if
    #                          the user explicitly asks for "clean text" /
    #                          "article body" / "newspaper extract".
    #   • yfinance_quote — "quote MSFT", "price of AAPL", "stock <ticker>"
    #   • pdf_text_search — "search my PDFs for X", "find in my PDFs"

    _TICKER_RE = re.compile(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b")
    _ARXIV_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b")

    def _parse_source_tools(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})

        # ── wikipedia ───────────────────────────────────────────────────
        # Check the SEARCH form first ("search wikipedia for X" — verb
        # outside `wikipedia`) so it doesn't get poached by the broader
        # summary regex that grabs everything after `wikipedia`.
        if "wikipedia_search" in tools:
            m = re.search(
                r"\b(?:search|find)\s+wiki(?:pedia)?\s+(?:for\s+|articles?\s+(?:on|about)\s+)?(.+)$",
                clause_lower,
            ) or re.search(
                r"\bfind\s+wikipedia\s+articles?\s+(?:on|about|for)\s+(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "wikipedia_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }
        # Summary form: `wikipedia` must be at clause start OR after a
        # tool verb (look up / wiki / on). Reject sentences where
        # `wikipedia` appears mid-narration ("I read about it on
        # wikipedia yesterday").
        if "wikipedia_summary" in tools:
            m = re.search(
                r"^(?:please\s+)?(?:look\s+up\s+|show\s+me\s+|give\s+me\s+|tell\s+me\s+about\s+)?"
                r"(?:wikipedia|wiki)\s+"
                r"(?:summary\s+(?:of|for|on)\s+|article\s+(?:on|about)\s+|"
                r"page\s+(?:on|about)\s+|on\s+|about\s+|for\s+|summary\s+|of\s+)?"
                r"(.+)$",
                clause_lower,
            )
            if m is None:
                m = re.search(
                    r"\blook\s+up\s+(.+?)\s+on\s+wiki(?:pedia)?\b",
                    clause_lower,
                )
                if m:
                    topic = m.group(1).strip(" ?.!,'\"")
                    if topic:
                        return {
                            "tool": "wikipedia_summary",
                            "args": {"query": topic},
                            "text": clause,
                            "domain": "research",
                        }
            else:
                topic = m.group(1).strip(" ?.!,'\"")
                # Reject if the topic looks like time-narration filler.
                if topic and topic not in {"yesterday", "today", "earlier"}:
                    return {
                        "tool": "wikipedia_summary",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }

        # ── arxiv ───────────────────────────────────────────────────────
        if "arxiv_search" in tools:
            # Explicit arxiv keyword.
            m = re.search(
                r"\barxiv\s+(?:search\s+(?:for\s+)?|papers?\s+(?:on|about|for)\s+|"
                r"on\s+|about\s+|for\s+|search\s+)?(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                # Don't pick up bare arxiv IDs as queries — those have a
                # dedicated handler in the existing skill chain.
                if topic and not self._ARXIV_ID_RE.fullmatch(topic):
                    return {
                        "tool": "arxiv_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }
            # "academic papers on X" / "research papers on X" — academic ask.
            m = re.search(
                r"\b(?:academic|research|scientific)\s+papers?\s+(?:on|about|for)\s+(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "arxiv_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }

        # ── hackernews ──────────────────────────────────────────────────
        if "hackernews_top" in tools and re.search(
            r"\b(?:top\s+(?:stories\s+on\s+)?hacker\s*news|"
            r"hacker\s*news\s+top|what'?s?\s+(?:on|trending\s+on)\s+hacker\s*news|"
            r"top\s+hn\s+stories|hn\s+top|trending\s+on\s+hn)\b",
            clause_lower,
        ):
            return {
                "tool": "hackernews_top",
                "args": {},
                "text": clause,
                "domain": "research",
            }
        if "hackernews_search" in tools:
            m = re.search(
                r"\b(?:hacker\s*news|hn)\s+(?:search\s+(?:for\s+)?|stories?\s+(?:on|about)\s+|"
                r"discussions?\s+(?:on|about)\s+|on\s+|about\s+)(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "hackernews_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }
            m = re.search(
                r"\bsearch\s+(?:hacker\s*news|hn)\s+(?:for\s+)?(.+)$", clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "hackernews_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }

        # ── pubmed ──────────────────────────────────────────────────────
        if "pubmed_search" in tools:
            m = re.search(
                r"\bpubmed\s+(?:search\s+(?:for\s+)?|on\s+|about\s+|for\s+)?(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "pubmed_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }
            m = re.search(
                r"\b(?:medical|clinical|biomedical)\s+papers?\s+(?:on|about|for)\s+(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "pubmed_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "research",
                    }

        # newspaper_extract is handled by _parse_newspaper_extract earlier
        # in the chain (runs BEFORE _parse_web_url_action so URL+clean
        # phrasing wins over plain `fetch <URL>` → web_extract).

        # ── yfinance_quote ──────────────────────────────────────────────
        if "yfinance_quote" in tools:
            m = re.search(
                r"\b(?:quote|price|stock\s+price|stock\s+quote)\s+(?:of\s+|for\s+)?"
                r"([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b",
                clause,  # case-sensitive — tickers are uppercase
            )
            if m:
                return {
                    "tool": "yfinance_quote",
                    "args": {"ticker": m.group(1)},
                    "text": clause,
                    "domain": "finance",
                }
            m = re.search(
                r"\b(?:what'?s|how'?s)\s+([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\s+"
                r"(?:trading\s+at|doing|priced\s+at)\b",
                clause,
            )
            if m:
                return {
                    "tool": "yfinance_quote",
                    "args": {"ticker": m.group(1)},
                    "text": clause,
                    "domain": "finance",
                }

        # ── pdf_text_search ─────────────────────────────────────────────
        if "pdf_text_search" in tools:
            # "search/find/look (in|through) (my|the) pdfs (for|about|FREE) X"
            m = re.search(
                r"\b(?:search|find|look\s+(?:for|up))\s+(?:in\s+|through\s+)?"
                r"(?:my\s+|the\s+)?pdfs?\s+(?:for\s+|about\s+)?(.+)$",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "pdf_text_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "files",
                    }
            # "find/search/look for X in (my|the) pdfs"
            m = re.search(
                r"\b(?:find|search|look\s+(?:for|up))\s+(?:for\s+)?(.+?)\s+in\s+(?:my\s+|the\s+)?pdfs?\b",
                clause_lower,
            )
            if m:
                topic = m.group(1).strip(" ?.!,'\"")
                if topic:
                    return {
                        "tool": "pdf_text_search",
                        "args": {"query": topic},
                        "text": clause,
                        "domain": "files",
                    }

        return None

    # ---- weather ------------------------------------------------------

    _WEATHER_LOCATION_RE = re.compile(
        r"\b(?:in|at|for|of|around|near)\s+([A-Za-z][A-Za-z .,'\-]{1,60})\s*\??\s*$",
        re.IGNORECASE,
    )

    def _parse_weather(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "get_weather" not in tools:
            return None
        # Anti-poach: "open the weather app" / "weather application" belong to
        # launch_app — never route to get_weather.
        if re.search(r"\bweather\s+(?:app|application|widget)\b", clause_lower):
            return None
        if re.search(r"^(?:open|launch|start|run)\s+(?:the\s+)?weather\b", clause_lower):
            return None
        if not re.search(
            r"\b(?:weather|forecast|temperature|how(?:'s|\s+is)\s+(?:the\s+)?weather|"
            r"how\s+(?:hot|cold|warm|chilly)\s+(?:is\s+it|outside)|"
            r"is\s+it\s+(?:raining|snowing|sunny|cloudy|cold|hot|windy)|"
            r"is\s+it\s+going\s+to\s+(?:rain|snow)|"
            r"will\s+it\s+rain|chance\s+of\s+rain|"
            r"how(?:'s|\s+is)\s+(?:it\s+)?outside)\b",
            clause_lower,
        ):
            return None
        loc_match = self._WEATHER_LOCATION_RE.search(clause)
        location = loc_match.group(1).strip(" ?.!,") if loc_match else ""
        # Filter out obvious non-locations the trailing-noun pattern picks up.
        if location.lower() in {"today", "tomorrow", "now", "outside", "here", "there"}:
            location = ""
        return {
            "tool": "get_weather",
            "args": {"location": location} if location else {},
            "text": clause,
            "domain": "weather",
        }

    # ---- goals --------------------------------------------------------

    def _parse_goals(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        stripped = clause.strip().rstrip(".!?")

        # list goals
        if "list_goals" in tools and re.search(
            r"\b(?:list|show|what(?:'s|\s+are)?)\s+(?:my\s+|all\s+(?:my\s+)?)?goals?\b"
            r"|\bgoals?\s+(?:list|status)\b"
            r"|\bwhat\s+(?:goals?\s+)?am\s+i\s+working\s+on\b",
            clause_lower,
        ):
            return {"tool": "list_goals", "args": {}, "text": clause, "domain": "goals"}

        # create goal
        if "create_goal" in tools:
            m = re.search(
                r"^(?:i\s+have\s+a\s+new\s+goal[:\s]+|add\s+(?:a\s+)?(?:new\s+)?goal[:\s]+|"
                r"create\s+(?:a\s+)?(?:new\s+)?goal[:\s]+|new\s+goal[:\s]+|"
                r"set\s+(?:a\s+)?(?:new\s+)?goal[:\s]+|"
                r"my\s+(?:new\s+)?goal\s+is\s+(?:to\s+)?|"
                r"i\s+want\s+to\s+(?:set\s+a\s+goal\s+(?:to\s+)?|achieve\s+))"
                r"(.+)$",
                stripped,
                re.IGNORECASE,
            )
            if m:
                title = m.group(1).strip(" .!?'\"")
                if title:
                    return {
                        "tool": "create_goal",
                        "args": {"title": title},
                        "text": clause,
                        "domain": "goals",
                    }

        # update goal score — "update X goal to Y% / set X goal to Y% / mark X as Y% done"
        if "update_goal" in tools:
            m = re.search(
                r"(?:(?:update|set|mark)\s+)"                          # verb
                r"(?:my\s+|the\s+|that\s+)?"
                r"(?:goal\s+)?"
                r"([\w\s]+?)"                                          # goal title (non-greedy)
                r"\s+(?:goal\s+)?(?:to\s+)?"
                r"(?:(\d+)\s*%|(\d+\.?\d*)\s*(?:percent|done|complete))"  # score
                r"",
                clause_lower,
            )
            if m:
                title = m.group(1).strip()
                score_str = m.group(2) or m.group(3) or "0"
                score = max(0.0, min(1.0, float(score_str) / 100.0))
                return {
                    "tool": "update_goal",
                    "args": {"title": title, "score": score},
                    "text": clause,
                    "domain": "goals",
                }

        # delete / remove / clear goals
        if "delete_goal" in tools:
            m = re.search(
                r"\b(?:remove|delete|clear|erase)\s+(?:my\s+|the\s+)?(.+?)\s+goal\b",
                clause_lower,
            )
            if m:
                title = m.group(1).strip()
                if title:
                    return {"tool": "delete_goal", "args": {"title": title}, "text": clause, "domain": "goals"}
            if re.search(
                r"\b(?:remove|delete|clear|erase|destroy)\s+(?:my\s+|the\s+|all\s+)?goals?\b",
                clause_lower,
            ):
                return {"tool": "delete_goal", "args": {}, "text": clause, "domain": "goals"}

        # complete / finish goal
        if "complete_goal" in tools and re.search(
            r"\b(?:i\s+(?:finished|completed|achieved|did)|finish(?:ed)?|complete(?:d)?|"
            r"mark\s+(?:as\s+)?done|done\s+with)\s+"
            r"(?:my\s+|the\s+)?(?:goal\s+(?:of\s+|to\s+)?|.+?\s+goal)\b"
            r"|\bmark\s+(?:my\s+|the\s+)?goal\s+(?:as\s+)?done\b",
            clause_lower,
        ):
            m = re.search(
                r"(?:goal\s+(?:of\s+|to\s+)?|finished\s+|completed\s+|"
                r"achieved\s+|did\s+|mark\s+(?:my\s+|the\s+)?)"
                r"(.+?)(?:\s+(?:as\s+)?done)?\s*$",
                clause_lower,
                re.IGNORECASE,
            )
            title = m.group(1).strip(" .!?'\"") if m else ""
            return {
                "tool": "complete_goal",
                "args": {"title": title} if title else {},
                "text": clause,
                "domain": "goals",
            }

        # pause goal
        if "pause_goal" in tools and re.search(
            r"\bpause\s+(?:my\s+|the\s+)?goal\b|\bput\s+(?:my\s+|the\s+)?goal\s+(?:on\s+hold|aside)\b"
            r"|\b(?:hold|freeze|suspend)\s+(?:my\s+|the\s+)?goal\b",
            clause_lower,
        ):
            return {"tool": "pause_goal", "args": {}, "text": clause, "domain": "goals"}

        # detail
        if "get_goal_detail" in tools and re.search(
            r"\btell\s+me\s+about\s+(?:my\s+|the\s+)?goal\b"
            r"|\b(?:goal\s+detail|details?\s+of\s+(?:my\s+|the\s+)?goal)\b",
            clause_lower,
        ):
            return {"tool": "get_goal_detail", "args": {}, "text": clause, "domain": "goals"}

        return None

    # ---- triggers -----------------------------------------------------

    def _parse_triggers(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})

        # list triggers
        if "list_triggers" in tools and re.search(
            r"\b(?:list|show|what(?:'s|\s+are)?)\s+(?:my\s+|all\s+(?:my\s+)?)?triggers?\b"
            r"|\bactive\s+triggers?\b",
            clause_lower,
        ):
            return {"tool": "list_triggers", "args": {}, "text": clause, "domain": "triggers"}

        # remove trigger
        if "remove_trigger" in tools and re.search(
            r"\b(?:remove|delete|cancel|disable|stop)\s+(?:my\s+|the\s+)?trigger(?:\s+#?\d+)?\b",
            clause_lower,
        ):
            m = re.search(r"#?(\d+)", clause_lower)
            args = {"trigger_id": m.group(1)} if m else {}
            return {"tool": "remove_trigger", "args": args, "text": clause, "domain": "triggers"}

        # clipboard trigger
        if "add_clipboard_trigger" in tools and re.search(
            r"\bwatch\s+(?:my\s+)?clipboard\b"
            r"|\b(?:add|create|set\s+up)\s+(?:a\s+)?clipboard\s+(?:trigger|watcher|watch)\b"
            r"|\btell\s+me\s+when\s+(?:i\s+copy|my\s+clipboard\s+changes)\b",
            clause_lower,
        ):
            return {"tool": "add_clipboard_trigger", "args": {}, "text": clause, "domain": "triggers"}

        # cron trigger
        if "add_cron_trigger" in tools and re.search(
            r"\b(?:add|create|set\s+up|schedule)\s+(?:a\s+)?(?:cron|scheduled|recurring)\s+(?:trigger|job|task)\b"
            r"|\bevery\s+(?:day|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
            r"morning|evening|night|week|month|hour|\d+\s+(?:minutes?|hours?|days?))"
            r"\s+(?:remind\s+me|run|do|execute)\b",
            clause_lower,
        ):
            return {"tool": "add_cron_trigger", "args": {}, "text": clause, "domain": "triggers"}

        # file-watch trigger
        if "add_file_watch_trigger" in tools and re.search(
            r"\bwatch\s+(?:my\s+|the\s+)?(?:downloads?|desktop|documents?|folder|directory|"
            r"~/[A-Za-z0-9_\-/]+|/[A-Za-z0-9_\-/]+)\b"
            r"|\b(?:notify|tell|alert)\s+me\s+when\s+(?:a\s+)?(?:new\s+)?file\b"
            r"|\b(?:add|create|set\s+up)\s+(?:a\s+)?file[\s-]+watch(?:er|\s+trigger)?\b",
            clause_lower,
        ):
            return {"tool": "add_file_watch_trigger", "args": {}, "text": clause, "domain": "triggers"}

        return None

    # ---- clipboard ----------------------------------------------------

    def _parse_clipboard(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        stripped = clause.strip().rstrip(".!?")

        if "get_clipboard" in tools and re.search(
            r"\bwhat(?:'s|\s+is)\s+(?:in\s+)?(?:my\s+|the\s+)?clipboard\b"
            r"|\bshow\s+(?:my\s+|the\s+)?clipboard\b"
            r"|\bread\s+(?:my\s+|the\s+)?clipboard\b"
            r"|\bget\s+(?:my\s+|the\s+)?clipboard(?:\s+content(?:s)?)?\b"
            r"|\bpaste\s+(?:my\s+|the\s+)?clipboard\b",
            clause_lower,
        ):
            return {"tool": "get_clipboard", "args": {}, "text": clause, "domain": "clipboard"}

        if "set_clipboard" in tools:
            m = re.search(
                r"^(?:copy|put|set|paste\s+to\s+clipboard|copy\s+to\s+clipboard)\s+"
                r"(?:to\s+(?:my\s+|the\s+)?clipboard\s+)?"
                r"[\"'](.+?)[\"']\s*(?:to\s+(?:my\s+|the\s+)?clipboard)?\s*$",
                stripped,
                re.IGNORECASE,
            )
            if m:
                return {
                    "tool": "set_clipboard",
                    "args": {"text": m.group(1)},
                    "text": clause,
                    "domain": "clipboard",
                }
            m = re.search(
                r"^(?:copy|put|set)\s+(?:this\s+)?to\s+(?:my\s+|the\s+)?clipboard[:\s]+(.+)$",
                stripped,
                re.IGNORECASE,
            )
            if m:
                return {
                    "tool": "set_clipboard",
                    "args": {"text": m.group(1).strip()},
                    "text": clause,
                    "domain": "clipboard",
                }

        if "analyze_clipboard_image" in tools and re.search(
            r"\b(?:analy[sz]e|describe|explain|what(?:'s|\s+is)\s+(?:in|on))\s+"
            r"(?:my\s+|the\s+)?clipboard\s+(?:image|picture|screenshot)\b"
            r"|\b(?:analy[sz]e|describe|explain)\s+(?:my\s+|the\s+)?clipboard\b.*\b(?:image|picture|screenshot)\b",
            clause_lower,
        ):
            return {"tool": "analyze_clipboard_image", "args": {}, "text": clause, "domain": "vision"}

        return None

    # ---- Home Assistant ----------------------------------------------

    def _parse_homeassistant(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})

        # Anti-poach: ignore "turn on/off voice/dnd/focus/lock" — those go to
        # their own parsers, which run BEFORE this one in the chain anyway.
        if re.search(
            r"\b(?:voice|dnd|focus|do\s+not\s+disturb|lock|brightness|volume)\b",
            clause_lower,
        ):
            return None

        # turn_off
        if "ha_turn_off" in tools and re.search(
            r"\bturn\s+off\s+(?:the\s+|my\s+)?[a-z][a-z ]*\b"
            r"|\b(?:switch\s+off|deactivate|shut\s+off)\s+(?:the\s+|my\s+)?[a-z][a-z ]*\b",
            clause_lower,
        ):
            m = re.search(
                r"\b(?:turn|switch|shut)\s+off\s+(?:the\s+|my\s+)?(.+)$",
                clause_lower,
            ) or re.search(
                r"\bdeactivate\s+(?:the\s+|my\s+)?(.+)$",
                clause_lower,
            )
            entity = m.group(1).strip(" .!?") if m else ""
            return {
                "tool": "ha_turn_off",
                "args": {"entity": entity} if entity else {},
                "text": clause,
                "domain": "homeassistant",
            }

        # turn_on
        if "ha_turn_on" in tools and re.search(
            r"\bturn\s+on\s+(?:the\s+|my\s+)?[a-z][a-z ]*\b"
            r"|\b(?:switch\s+on|activate|power\s+on)\s+(?:the\s+|my\s+)?[a-z][a-z ]*\b",
            clause_lower,
        ):
            m = re.search(
                r"\b(?:turn|switch|power)\s+on\s+(?:the\s+|my\s+)?(.+)$",
                clause_lower,
            ) or re.search(
                r"\bactivate\s+(?:the\s+|my\s+)?(.+)$",
                clause_lower,
            )
            entity = m.group(1).strip(" .!?") if m else ""
            return {
                "tool": "ha_turn_on",
                "args": {"entity": entity} if entity else {},
                "text": clause,
                "domain": "homeassistant",
            }

        # set temperature
        if "ha_set_temperature" in tools:
            m = re.search(
                r"\bset\s+(?:the\s+)?(?:ac|thermostat|temperature|heater|aircon|"
                r"air\s+conditioner|heating|cooling)\s+to\s+(\d{1,3})\s*(?:degrees?|°|c|f)?\b",
                clause_lower,
            )
            if m:
                return {
                    "tool": "ha_set_temperature",
                    "args": {"temperature": int(m.group(1))},
                    "text": clause,
                    "domain": "homeassistant",
                }

        # state query — "is the X on/off/open/closed/locked", with optional
        # room-adjective ("kitchen light", "bedroom lamp", "front door").
        if "ha_get_state" in tools and re.search(
            r"\bis\s+(?:the\s+|my\s+)?"
            r"(?:(?:front|back|side|main)\s+door|"
            r"(?:kitchen|bedroom|bathroom|living\s+room|office|porch|garage|"
            r"hallway|attic|basement)\s+(?:light|lamp|fan|tv|heater|ac|window)|"
            r"garage|thermostat|ac|aircon|air\s+conditioner|fan|tv|heater|"
            r"lights?|outlet|switch|window)\s+"
            r"(?:on|off|open|closed|locked|unlocked|running|active)\b",
            clause_lower,
        ):
            return {"tool": "ha_get_state", "args": {}, "text": clause, "domain": "homeassistant"}

        return None

    # ---- awareness mode ---------------------------------------------

    def _parse_awareness(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "awareness_status" in tools and re.search(
            r"\bawareness\s+(?:status|mode\s+status|on|off)\b"
            r"|\bis\s+awareness\s+(?:mode\s+)?(?:on|off|enabled|active)\b"
            r"|\bare\s+you\s+(?:watching|aware|observing)\s+(?:my\s+)?screen\b",
            clause_lower,
        ):
            return {"tool": "awareness_status", "args": {}, "text": clause, "domain": "awareness"}
        if "enable_awareness_mode" in tools and re.search(
            r"\b(?:enable|turn\s+on|start|activate|engage)\s+(?:screen\s+)?awareness(?:\s+mode)?\b"
            r"|\bwatch\s+my\s+screen\b|\bstart\s+(?:watching|observing)\s+(?:my\s+)?screen\b",
            clause_lower,
        ):
            return {"tool": "enable_awareness_mode", "args": {}, "text": clause, "domain": "awareness"}
        if "disable_awareness_mode" in tools and re.search(
            r"\b(?:disable|turn\s+off|stop|deactivate)\s+(?:screen\s+)?awareness(?:\s+mode)?\b"
            r"|\bstop\s+(?:watching|observing)\s+(?:my\s+)?screen\b",
            clause_lower,
        ):
            return {"tool": "disable_awareness_mode", "args": {}, "text": clause, "domain": "awareness"}
        return None

    # ---- code eval --------------------------------------------------

    def _parse_code_eval(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "evaluate_code" not in tools:
            return None
        m = re.search(
            r"^(?:evaluate|run|execute|eval)(?:\s+this)?(?:\s+(?:python|py))?(?:\s+code)?[:\s]+(.+)$",
            clause.strip(),
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            code = m.group(1).strip(" `'\"")
            if code:
                return {
                    "tool": "evaluate_code",
                    "args": {"code": code},
                    "text": clause,
                    "domain": "code",
                }
        return None

    # ---- send notification -----------------------------------------

    def _parse_send_notification(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "send_notification" not in tools:
            return None
        m = re.search(
            r"^(?:send|show|post|fire)\s+(?:me\s+)?(?:a\s+)?(?:desktop\s+|system\s+|popup\s+)?"
            r"notification(?:\s+(?:saying|with\s+text|that\s+says))?[:\s]+(.+)$",
            clause.strip(),
            re.IGNORECASE,
        )
        if m:
            text = m.group(1).strip(" .'\"")
            return {
                "tool": "send_notification",
                "args": {"text": text},
                "text": clause,
                "domain": "notification",
            }
        m = re.search(
            r"^(?:notify|ping)\s+me(?:\s+with)?[:\s]+(.+)$",
            clause.strip(),
            re.IGNORECASE,
        )
        if m:
            return {
                "tool": "send_notification",
                "args": {"text": m.group(1).strip(" .'\"")},
                "text": clause,
                "domain": "notification",
            }
        return None

    # ---- active window query ----------------------------------------

    def _parse_window_query(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "get_active_window" not in tools:
            return None
        if re.search(
            r"\b(?:what(?:'s|\s+is)|which)\s+(?:my\s+|the\s+)?(?:active\s+|current\s+|focused\s+)?window\b"
            r"|\bwhat\s+(?:app|application|program)\s+(?:am\s+i|is)\s+(?:using|open|focused|active)\b"
            r"|\bwhat\s+am\s+i\s+(?:looking\s+at|focused\s+on|using)(?!\s+on\s+screen)\b"
            r"|\bcurrent(?:ly)?\s+focused\s+(?:window|app)\b",
            clause_lower,
        ):
            return {"tool": "get_active_window", "args": {}, "text": clause, "domain": "window"}
        return None

    def _parse_forget_learned(self, clause, clause_lower, context):
        """Route "forget how I talk" / "reset what you've learned" to the
        adaptive-intent reset (Adaptive Intent Phase 5).

        Distinct from the memory-fact wipe (`wipe_memory_init`): this clears
        the *routing learning* (learned phrasings + usage profile), not the
        user's facts/preferences. Anchored on talk/speak/phrasing/wording or
        an explicit "learned"/"learning" object so it never poaches a
        memory-fact wipe.
        """
        if "forget_learned_intents" not in getattr(self.router, "_tools_by_name", {}):
            return None
        verb = r"(?:forget|reset|clear|wipe|unlearn|stop\s+learning)"
        obj = (
            r"how\s+i\s+(?:talk|speak|word|phrase|say)"
            r"|the\s+way\s+i\s+(?:talk|speak|word|phrase)"
            r"|(?:my|the)\s+(?:phrasings?|wording|speech\s+patterns?)"
            r"|what\s+you(?:'ve|\s+have)?\s+learned(?:\s+about\s+(?:how\s+i\s+talk|my\s+phrasing))?"
            r"|your\s+(?:intent\s+)?learning"
            r"|how\s+i\s+word\s+things"
        )
        if re.search(rf"\b{verb}\b.{{0,30}}(?:{obj})", clause_lower) or \
           re.search(rf"(?:{obj}).{{0,20}}\b{verb}\b", clause_lower):
            return {"tool": "forget_learned_intents", "args": {},
                    "text": clause, "domain": "learning"}
        return None

    def _parse_memory_query(self, clause, clause_lower, context):
        """Route recall/forget queries to the memory_manager plugin.

        Without this, "what do you remember about me?" used to fall through to
        the LLM router (non-deterministic) or worse, hit save_note via the
        "remember" keyword. show_memories / delete_memory now have a
        deterministic intent surface symmetric to save_note.
        """
        tools = getattr(self.router, "_tools_by_name", {})

        if "show_memories" in tools and re.search(
            r"\b(?:what\s+do\s+you\s+(?:remember|know)(?:\s+about\s+(?:me|us))?"
            r"|what\s+have\s+you\s+learned(?:\s+about\s+me)?"
            r"|show\s+(?:me\s+)?(?:my\s+)?memories"
            r"|list\s+(?:my\s+)?memories"
            r"|what\s+are\s+my\s+preferences"
            r"|do\s+you\s+remember\s+(?:anything\s+)?about\s+me"
            # 2026-05-23: variants that used to fall into chat mode and
            # come back with an LLM-fabricated bullet repeat:
            r"|(?:what|tell\s+me)\s+(?:else|more)\s+(?:do\s+you\s+(?:know|remember)|about\s+me)"
            r"|anything\s+else\s+(?:about\s+me|you\s+(?:know|remember))"
            r"|tell\s+me\s+(?:everything|all)\s+(?:you\s+know|about\s+me))\b",
            clause_lower,
        ):
            # If the user asked for "else" / "more" / "everything", pass
            # a flag so the handler shows full key/value detail instead
            # of repeating the curated paragraph verbatim (2026-05-23
            # 21:36 → 21:37 session: identical reply twice in a row).
            more = bool(re.search(
                r"\b(?:else|more|anything\s+else|everything|all|in\s+detail|full(?:\s+list)?)\b",
                clause_lower,
            ))
            return {
                "tool": "show_memories",
                "args": {"more": True} if more else {},
                "text": clause,
                "domain": "memory",
            }

        # search_conversations -------------------------------------------
        # "Search my conversations for X" was routing to search_indexed_files
        # via the planner — wrong tool (file index, not chat history). The
        # search_conversations capability is FTS5-backed and exists in
        # modules/memory_manager. Bind it deterministically.
        if "search_conversations" in tools:
            m = re.search(
                r"\b(?:search|find|look\s+(?:up|for))\s+"
                r"(?:in\s+|through\s+)?(?:my\s+|our\s+)?(?:past\s+)?(?:conversations?|chats?|"
                r"conversation\s+history|chat\s+history|past\s+turns|past\s+messages)\s+"
                r"(?:for|about|on|mentioning)\s+(.+)$",
                clause_lower,
            )
            if m:
                query = m.group(1).strip(" .!?,")
                return {
                    "tool": "search_conversations",
                    "args": {"query": query},
                    "text": clause,
                    "domain": "memory",
                }
            m = re.search(
                r"\bwhat\s+(?:did\s+we|have\s+we)\s+(?:talk(?:ed)?|discuss(?:ed)?|"
                r"say|said)\s+about\s+(.+)$",
                clause_lower,
            )
            if m:
                query = m.group(1).strip(" .!?,")
                return {
                    "tool": "search_conversations",
                    "args": {"query": query},
                    "text": clause,
                    "domain": "memory",
                }

        # forget_memory ----------------------------------------------------
        # Tool name is `forget_memory` (not delete_memory — the original
        # capability was renamed during P0.2). The old regex referenced
        # the wrong name and silently never fired. Restored + extended
        # with key extraction so "forget my love for coding" routes
        # correctly with key="loves" instead of falling through to chat.
        if "forget_memory" in tools:
            forget_result = self._extract_forget_target(clause_lower)
            if forget_result is not None:
                return {
                    "tool": "forget_memory",
                    "args": {"key": forget_result},
                    "text": clause,
                    "domain": "memory",
                }

        if "wipe_memory_init" in tools and re.search(
            r"\b(?:forget|wipe|erase|clear|delete|reset)\b.{0,40}"
            r"\b(?:everything|all|my\s+memory|what\s+you\s+know|your\s+memory|my\s+data)\b"
            r"|\bstart\s+fresh\b|\bwipe\s+(?:your|my)\s+memory\b"
            r"|\bforget\s+everything\s+(?:you\s+know\s+)?about\s+me\b",
            clause_lower,
        ):
            return {"tool": "wipe_memory_init", "args": {}, "text": clause, "domain": "memory"}

        if "export_memory" in tools and re.search(
            r"\bexport\b.{0,30}\b(?:my\s+)?memor(?:y|ies)\b"
            r"|\bbackup\b.{0,30}\b(?:my\s+)?memor(?:y|ies)\b"
            r"|\bsave\b.{0,30}\b(?:my\s+)?memories\b.{0,15}\bfile\b",
            clause_lower,
        ):
            return {"tool": "export_memory", "args": {}, "text": clause, "domain": "memory"}

        return None

    # Bare "remember X" free-form write path (P0.3).
    # "remember this/that/it" is already handled by save_note; this catches
    # everything else: "remember I love cars", "remember that I like jazz", etc.
    _FREE_REMEMBER_PREFIX = re.compile(
        r"^\s*remember\s+(?:that\s+)?(?P<fact>.+?)\s*$", re.IGNORECASE
    )
    _PURELY_DEMONSTRATIVE = re.compile(r"^(this|that|it|these|those)[.!?]?$", re.IGNORECASE)
    _LOVE_LIKE_PATTERN = re.compile(
        r"^i\s+(?P<verb>love|like|enjoy|hate|prefer|dislike)\s+(?P<value>.+)$", re.IGNORECASE
    )

    def _parse_free_remember(self, clause, clause_lower, context):
        m = self._FREE_REMEMBER_PREFIX.match(clause_lower)
        if not m:
            return None
        fact = m.group("fact").strip()
        if not fact or self._PURELY_DEMONSTRATIVE.match(fact):
            return None

        tools = getattr(self.router, "_tools_by_name", {})

        # "remember I love cars" → record_personal_fact(loves=cars)
        love_m = self._LOVE_LIKE_PATTERN.match(fact)
        if love_m and "record_personal_fact" in tools:
            verb = love_m.group("verb").lower()
            value = love_m.group("value").strip().rstrip(".!?")
            key_map = {"love": "loves", "like": "likes", "enjoy": "enjoys",
                       "hate": "hates", "prefer": "prefers", "dislike": "dislikes"}
            key = key_map.get(verb, verb)
            return {
                "tool": "record_personal_fact",
                "args": {"key": key, "value": value},
                "text": clause,
                "domain": "memory",
            }

        # Generic free-form → save as a note
        if "save_note" in tools:
            return {"tool": "save_note", "args": {}, "text": fact, "domain": "notes"}

        return None

    def _parse_voice_toggle(self, clause, clause_lower, context):
        # The word "mode" is optional — humans say "set voice to manual"
        # almost as often as "set voice mode to manual" (Issue 2). Same
        # for the connector "to": "set voice manual" works too.
        mode_match = re.search(
            r"\b(?:set|switch|change)\s+(?:voice|conversation|listening)(?:\s+mode)?\s+(?:to\s+)?(persistent|always on|on[-\s]?demand|manual|off)\b",
            clause_lower,
        )
        if mode_match:
            mode = mode_match.group(1).replace("-", "_").replace(" ", "_")
            if mode == "always_on":
                mode = "persistent"
            if mode == "off":
                mode = "manual"
            return {"tool": "set_voice_mode", "args": {"mode": mode}, "text": clause, "domain": "voice"}
        if re.search(r"\b(?:use|enable)\s+on[-\s]?demand\s+(?:voice|conversation|listening)\b", clause_lower):
            return {"tool": "set_voice_mode", "args": {"mode": "on_demand"}, "text": clause, "domain": "voice"}
        if re.search(r"\b(?:use|enable)\s+(?:persistent|always on)\s+(?:voice|conversation|listening)\b", clause_lower):
            return {"tool": "set_voice_mode", "args": {"mode": "persistent"}, "text": clause, "domain": "voice"}
        if re.search(r"\bfriday\s+wake\s+up\b", clause_lower) or re.fullmatch(r"wake\s+up", clause_lower.strip()):
            return {"tool": "enable_voice", "args": {"wake_up": True}, "text": clause, "domain": "voice"}
        if re.search(r"\b(?:enable|start|turn on)\s+(?:the\s+)?(?:mic|microphone|voice)\b", clause_lower):
            return {"tool": "enable_voice", "args": {}, "text": clause, "domain": "voice"}
        if re.search(r"\b(?:disable|stop|turn off)\s+(?:the\s+)?(?:mic|microphone|voice)\b", clause_lower):
            return {"tool": "disable_voice", "args": {}, "text": clause, "domain": "voice"}
        return None

    def _parse_help(self, clause, clause_lower, context):
        # Only route to show_capabilities for explicit capability-listing requests.
        # "help me [do X]" must NOT match — only bare help queries or "what can you do".
        if re.search(r"\bwhat\s+(?:else\s+)?can\s+you\s+do\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        if re.search(r"\bshow\s+(?:me\s+)?(?:your\s+)?(?:commands|capabilities|abilities)\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        if re.search(r"\blist\s+(?:your\s+|all\s+)?(?:your\s+)?(?:commands|capabilities|abilities|tools?)\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        if re.search(r"\bwhat\s+(?:tools?|features?|commands?)\s+do\s+you\s+(?:have|support)\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        if re.search(r"\bwhat\s+can\s+(?:i|we)\s+ask\s+(?:you|friday)\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        if re.search(r"\btell\s+me\s+what\s+you\s+can\s+do\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        if re.search(r"\bwhat\s+(?:do\s+you\s+)?(?:support|handle)\b", clause_lower) and re.search(r"\b(?:friday|you)\b", clause_lower):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        # Bare "help" or "help friday" only — NOT "help me write X"
        if re.fullmatch(r"(?:help|help\s+friday)[.!?]?", clause_lower.strip()):
            return {"tool": "show_capabilities", "args": {}, "text": clause, "domain": "help"}
        return None

    def _parse_cancel_task(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "cancel_active_task" not in tools:
            return None

        # "never mind" — unambiguous cancel that shouldn't fall through to confirm_no.
        if re.fullmatch(r"never\s+mind[.!?]?", clause_lower):
            return {"tool": "cancel_active_task", "args": {}, "text": clause, "domain": "system"}

        # Phrasal: "cancel that", "stop what you're doing", "cancel the research",
        # "abort the task", "stop working on that", "stop what you are doing", etc.
        # Bare "cancel" / "stop" is NOT included — those fall through to
        # _parse_confirmation → confirm_no so pending yes/no dialogs work.
        if re.search(
            r"\b(?:cancel|stop|abort)\s+"
            r"(?:"
            r"(?:what|all)\s+(?:you|we|it)(?:'?re|\s+are)?\s+(?:doing|working(?:\s+on)?)|"
            r"(?:the|this|that)\s+(?:research|task|action|operation|work(?:flow)?|process|search)|"
            r"\w+ing\s+on\s+(?:that|this|it)|"
            r"(?:that|this|it)"
            r")\b",
            clause_lower,
        ):
            return {"tool": "cancel_active_task", "args": {}, "text": clause, "domain": "system"}

        return None

    def _parse_exit(self, clause, clause_lower, context):
        if re.fullmatch(r"(?:bye|goodbye|exit|quit|stop assistant)(?:\s+friday)?[.!?]?", clause_lower) or \
           re.search(r"\b(?:shut down|shutdown|close|exit|quit)\s+(?:friday|the assistant|yourself)\b", clause_lower):
            return {"tool": "shutdown_assistant", "args": {}, "text": clause, "domain": "system"}
        return None

    _IDENTITY_PATTERNS = (
        re.compile(r"^who\s+(?:are|r)\s+(?:you|u|friday)\b", re.IGNORECASE),
        re.compile(r"^what\s+(?:are|r)\s+(?:you|u|friday)\b", re.IGNORECASE),
        re.compile(r"^what'?s?\s+your\s+name\b", re.IGNORECASE),
        re.compile(r"^what\s+is\s+your\s+name\b", re.IGNORECASE),
        re.compile(r"\b(?:introduce|describe)\s+yourself\b", re.IGNORECASE),
        re.compile(r"^tell\s+me\s+about\s+(?:yourself|you|friday)\b", re.IGNORECASE),
        re.compile(r"^(?:are|r)\s+you\s+(?:an?\s+)?(?:ai|bot|robot|assistant|human|person|real)\b", re.IGNORECASE),
        re.compile(r"^state\s+your\s+(?:name|identity)\b", re.IGNORECASE),
        re.compile(r"^identify\s+yourself\b", re.IGNORECASE),
    )

    def _parse_identity(self, clause, clause_lower, context):
        tools = getattr(self.router, "_tools_by_name", {})
        if "identify_self" not in tools:
            return None
        stripped = clause.strip().rstrip(".!?")
        for pattern in self._IDENTITY_PATTERNS:
            if pattern.search(stripped):
                return {"tool": "identify_self", "args": {}, "text": clause, "domain": "identity"}
        return None

    def _parse_greeting(self, clause, clause_lower, context):
        if re.fullmatch(r"(?:hi|hello|hey|good morning|good afternoon|good evening)[.!?]?", clause_lower):
            return {"tool": "greet", "args": {}, "text": clause, "domain": "greeting"}
        return None

    def _parse_confirmation(self, clause, clause_lower, context):
        if re.fullmatch(r"(?:yes|yeah|yep|sure|okay|ok|open it|do it)[.!?]?", clause_lower):
            return {"tool": "confirm_yes", "args": {}, "text": clause, "domain": "confirmation"}
        if re.fullmatch(r"(?:no|nope|cancel|stop)[.!?]?", clause_lower):
            return {"tool": "confirm_no", "args": {}, "text": clause, "domain": "confirmation"}
        return None

    def _extract_count(self, text):
        match = re.search(r"\b(\d+)\s+(?:times?|steps?|levels?)\b", text)
        if match:
            return max(1, int(match.group(1)))
        return 1

    def _extract_volume_percent(self, clause_lower, context):
        patterns = (
            r"\b(?:set|change|make|turn|put)\s+(?:the\s+|my\s+)?volume\s+(?:to|at|on)\s+(\d{1,3})(?:\s*(?:percent|%))?\b",
            r"\bvolume\s+(?:to|at|on)\s+(\d{1,3})(?:\s*(?:percent|%))?\b",
            # Bare "volume 50" / "volume 50%".
            r"\bvolume\s+(\d{1,3})\s*(?:percent|%)\b",
            r"\bvolume\s+(\d{1,3})\b(?!\s*(?:hour|minute|second|step|level))",
        )
        for pattern in patterns:
            match = re.search(pattern, clause_lower)
            if match:
                return max(0, min(100, int(match.group(1))))

        # Spoken cardinals: "set volume to fifty", "put the volume on full".
        if re.search(r"\bvolume\b.*\b(?:to|at|on)\b", clause_lower):
            cardinals = {
                "zero": 0, "ten": 10, "fifteen": 15, "twenty": 20, "twenty five": 25,
                "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
                "seventy": 70, "seventy five": 75, "eighty": 80, "ninety": 90,
                "hundred": 100, "one hundred": 100, "max": 100, "full": 100,
                "mute": None,  # handled elsewhere
            }
            for word, val in sorted(cardinals.items(), key=lambda x: -len(x[0])):
                if val is None:
                    continue
                if re.search(rf"\b{re.escape(word)}\b\s*(?:%|percent)?", clause_lower):
                    return val

        if context.get("domain") == "volume":
            match = re.fullmatch(r"(?:to\s+)?(\d{1,3})(?:\s*(?:percent|%))?", clause_lower.strip())
            if match:
                return max(0, min(100, int(match.group(1))))
        return None

    def _active_browser_workflow(self):
        store = getattr(self.router, "context_store", None)
        session_id = getattr(self.router, "session_id", None)
        if not store or not session_id:
            return None
        return store.get_active_workflow(session_id, workflow_name="browser_media")

    def _default_browser_platform(self, query, active_browser):
        if active_browser and active_browser.get("platform") in {"youtube", "youtube_music"}:
            return active_browser["platform"]
        if re.search(r"\b(?:song|music|album|playlist)\b", query):
            return "youtube_music"
        return "youtube"

    def _should_recover_file_reference(self, clause_lower, context):
        normalized = clause_lower.strip(" .!?")
        if not normalized:
            return False
        if context.get("domain") != "files":
            return False
        if re.search(
            r"\b(?:open|launch|start|play|take|capture|find|search|locate|set|save|write|append|add|read|show|list|get|check|tell|what|summarize|summary|remind|enable|disable|turn|mute|unmute|increase|decrease|lower|raise|stop|pause)\b",
            normalized,
        ):
            return False
        tokens = normalized.split()
        if len(tokens) > 8:
            return False
        disallowed = {
            "a", "an", "the", "in", "on", "at", "to", "for", "with", "from", "within",
            "inside", "outside", "is", "are", "was", "were", "be", "being", "been",
            "please", "can", "could", "would", "should", "will", "not",
            "yes", "yeah", "yep", "sure", "okay", "ok", "no", "nope", "cancel", "stop",
        }
        if any(token in disallowed for token in tokens):
            return False
        return bool(re.fullmatch(r"[a-z0-9][a-z0-9 ._\-]*", normalized))

    def _active_file_reference(self):
        dialog_state = getattr(self.router, "dialog_state", None)
        selected_file = getattr(dialog_state, "selected_file", None) if dialog_state else None
        if selected_file:
            filename = os.path.basename(selected_file).lower()
            return {"filename": filename, "stem": os.path.splitext(filename)[0]}

        store = getattr(self.router, "context_store", None)
        session_id = getattr(self.router, "session_id", None)
        if not store or not session_id:
            return None
        workflow = store.get_active_workflow(session_id, workflow_name="file_workflow") or {}
        target = workflow.get("target") or {}
        filename = os.path.basename(target.get("path", "") or target.get("filename", "")).lower()
        if not filename:
            return None
        return {"filename": filename, "stem": os.path.splitext(filename)[0]}
