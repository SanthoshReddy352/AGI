"""MemoryBroker — builds context bundles for each turn.

Phase 7: Upgraded to use the three typed memory stores (episodic, semantic,
procedural) from core.memory, while remaining backward-compatible with the
existing ContextStore interface.
"""
from __future__ import annotations

from core.memory.episodic import EpisodicMemory
from core.memory.facade import MemoryFacade
from core.memory.graph import EntityExtractor
from core.memory.procedural import ProceduralMemory
from core.memory.semantic import SemanticMemory


class MemoryBroker:
    def __init__(self, context_store, persona_manager, plan_archive=None):
        self.context_store = context_store
        self.persona_manager = persona_manager
        self.episodic = EpisodicMemory(context_store)
        self.semantic = SemanticMemory(context_store)
        self.procedural = ProceduralMemory(context_store)
        # Track 2.0 (Consolidation Direction): canonical writer/reader
        # for session facts. Wraps SemanticMemory with normalization +
        # reconciliation. Future Track 2.x commits move PersonaManager
        # and entity-graph writes through this facade too.
        self.facts = MemoryFacade(context_store, semantic=self.semantic)
        # Track 2.2c: typed knowledge-graph extractor. Activated in
        # `curate` so every completed turn populates the entity tables
        # AND routes first-party user facts (`my name is X`) through
        # the canonical facade. Constructed against `context_store`
        # directly so it works in test apps that don't wire memory_service.
        self.entity_extractor = EntityExtractor(context_store)
        # Phase 8: optional plan archive for few-shot retrieval.
        self.plan_archive = plan_archive

    def build_context_bundle(self, query: str, session_id: str) -> dict:
        """Build a rich context bundle for capability planning.

        Returns a dict consumed by CapabilityBroker and ConversationAgent.
        Keys are stable — adding new keys here is non-breaking.
        """
        persona = self.persona_manager.get_active_persona(session_id)
        persona_id = persona.get("persona_id") if persona else ""

        return {
            "persona": persona or {},
            "session_summary": self.context_store.summarize_session(session_id, limit=8),
            "active_workflow": self.context_store.get_workflow_summary(session_id),
            "semantic_recall": self.context_store.semantic_recall(query, session_id, limit=4),
            "durable_memories": self.context_store.recent_memory_items(session_id, limit=6, persona_id=persona_id),
            "session_state": self.context_store.get_session_state(session_id) or {},
            # Phase 7 additions
            "top_capabilities": self.procedural.top_capabilities(limit=3),
            # Phase 8: top-k similar prior approved plans, formatted as
            # few-shot exemplars (task, workflow, slots, plan_shape, outcome).
            "retrieved_examples": self._retrieved_examples(query),
            # Track 2.0: facts surfaced via the canonical MemoryFacade so
            # the chat prompt's `<USER_FACTS>` block (Track 1.1) and any
            # future plugin reader see the SAME normalized values — no
            # more "Nellore" / "Nolo-re" drift between consumers.
            "user_facts": self.facts.render_user_facts(session_id, persona_id=persona_id),
        }

    def _retrieved_examples(self, query: str) -> list[dict]:
        if self.plan_archive is None or not query:
            return []
        try:
            records = self.plan_archive.retrieve_similar(query, top_k=3)
        except Exception:
            return []
        return [r.to_exemplar() for r in records]

    def curate(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        persona_id: str = "",
    ) -> None:
        # Track 2.2c: run the typed-graph extractor first so entities
        # land in the graph regardless of whether the inline patterns
        # below match. The extractor also surfaces first-party user
        # facts (name / location / role) that flow through the
        # canonical facade — same normalization + user_profile mirror
        # the inline `REMEMBER_PATTERNS` use.
        try:
            self.entity_extractor.process_turn(user_text, assistant_text, session_id)
        except Exception:
            pass
        try:
            user_facts = self.entity_extractor.extract_user_facts(user_text)
        except Exception:
            user_facts = {}
        for key, value in (user_facts or {}).items():
            try:
                self.facts.remember(
                    session_id, key, value,
                    source="extracted", confidence=0.8,
                    persona_id=persona_id,
                )
            except Exception:
                pass
        """Extract and store memories from a completed turn.

        Track 2.2b: writes flow through the canonical `MemoryFacade` so the
        same normalization + reconciliation that `record_personal_fact`
        uses also applies to ambient extraction. The patterns below catch
        user-fact phrasing the deterministic `_parse_personal_fact` intent
        path didn't fire on (e.g. inside a longer sentence, "I'm a builder
        and my name is Tricky" — the intent parser requires a clean
        `<key> is <value>` head; this fallback catches it from inside the
        sentence).

        Keys are mapped to the canonical facade vocabulary
        (`name`, `location`, `role`, `preferences`) so the dual-write into
        `user_profile` (Track 2.2) fires correctly. Phase 9 will upgrade
        this to an LLM-driven extraction.
        """
        import re

        # (pattern, key, value_group). When `value_group` is 1 the regex's
        # first capture IS the canonical value. The patterns are tested in
        # order; first match wins per sentence.
        #
        # Values stop at conjunctions / punctuation so a sentence like
        # "I live in Nellore and I prefer X" yields key=location value=Nellore
        # (not "Nellore and I prefer X"). The role/preferences patterns are
        # looser because those values naturally include phrases.
        # Single-word capture for name/location stops at the first space —
        # multi-word values ("New York", "Pat Smith") are rare in casual
        # speech and ambient extraction can't reliably know when a place
        # name ends versus the rest of the sentence begins. Users with
        # multi-word values can use the explicit `record_personal_fact`
        # intent ("my location is New York") which has stricter parsing.
        # role/preferences are looser because those values naturally
        # include phrases.
        _STOP = r"(?:\s+(?:and|but|or|because|so|then|while|since|actually|today|now|though)\b|[,.!?;:]|$)"
        REMEMBER_PATTERNS: tuple[tuple[str, str, int], ...] = (
            (rf"\b(?:my name is|i am called|call me)\s+([a-zA-Z][a-zA-Z\-]{{0,30}})(?={_STOP})", "name", 1),
            (rf"\b(?:my\s+location\s+is|i'?m\s+based\s+in|i\s+live\s+in|i'?m\s+from)\s+([a-zA-Z][a-zA-Z\-]{{1,40}})(?={_STOP})", "location", 1),
            (rf"\bi\s+work\s+as\s+(?:an?\s+)?([a-zA-Z][a-zA-Z\s\-]{{1,40}}?)(?={_STOP})", "role", 1),
            (rf"\bi\s+(?:prefer|like|love)\s+(.+?)(?={_STOP})", "preferences", 1),
        )
        for sentence in re.split(r"[.!?]\s+", user_text):
            for pattern, key, group in REMEMBER_PATTERNS:
                m = re.search(pattern, sentence.strip(), re.IGNORECASE)
                if m:
                    value = m.group(group).strip().rstrip(" .,!?")
                    if value:
                        self.facts.remember(
                            session_id, key, value,
                            source="curated", confidence=0.85,
                            persona_id=persona_id,
                        )
                    break

    def record_capability_outcome(self, capability_name: str, context_features: dict | None, success: bool) -> None:
        """Delegate to ProceduralMemory for bandit-style success tracking."""
        self.procedural.record_outcome(capability_name, context_features, success)
