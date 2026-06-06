import copy
import os
import re

from core.assistant_context import AssistantContext
from core.bootstrap import LifecycleManager
from core.capability_broker import CapabilityBroker
from core.kernel import ConsentService, PermissionService
from core.capability_registry import CapabilityExecutor, CapabilityRegistry
from core.config import ConfigManager
from core.stores import ContextStore
from core.conversation_agent import ConversationAgent
from core.delegation import DelegationManager
from core.dialogue_manager import DialogueManager
from core.dialog_state import DialogState
from core.event_bus import EventBus
from core.memory_broker import MemoryBroker
from core.memory_service import MemoryService
from core.persona_manager import PersonaManager
from core.reasoning import ModelRouter, GraphCompiler
from core.reasoning.route_scorer import RouteScorer
from core.result_cache import ResultCache
from core.speech_coordinator import SpeechCoordinator
from core.system_capabilities import SystemCapabilities
from core.planning import (
    IntentEngine,
    PlannerEngine,
    TurnOrchestrator,
    WorkflowCoordinator,
)
from core.task_graph_executor import TaskGraphExecutor
from core.tool_execution import OrderedToolExecutor
from core.tracing import configure_trace_export
from core.resource_monitor import ResourceMonitor
from core.session_rag import SessionRAG
from core.turn_feedback import RuntimeMetrics, TurnFeedbackRuntime
from core.turn_manager import TurnManager
from core.task_runner import TaskRunner
from core.workflow_orchestrator import WorkflowOrchestrator
from core.router import CommandRouter
from core.extensions.loader import ExtensionLoader
from core.routing_state import RoutingState
from core.response_finalizer import ResponseFinalizer
from core.model_output import strip_model_artifacts
from core.logger import logger


class FridayApp:
    def _apply_embedding_config(self) -> None:
        """Push memory.embedding config into the env vars the embedding
        layer reads, before any store is constructed. Keeps a single source
        of truth in config.yaml while the embedder stays config-agnostic."""
        emb = (self.config.get("memory.embedding") or {})
        mapping = {
            "model": "FRIDAY_EMBED_MODEL",
            "cache_size": "FRIDAY_EMBED_CACHE",
            "recency_half_life_days": "FRIDAY_RECALL_HALFLIFE_DAYS",
            "rerank_model": "FRIDAY_RERANK_MODEL",
        }
        for key, env in mapping.items():
            val = emb.get(key)
            if val not in (None, ""):
                os.environ.setdefault(env, str(val))

    def __init__(self):
        self.config = ConfigManager()
        self._apply_embedding_config()
        self.event_bus = EventBus()
        self.dialog_state = DialogState()
        # Batch 3 / Issue 3: any user-initiated cancel ("stop", "enough",
        # "Friday cancel", wake-word barge-in) fires through the global
        # InterruptBus. DialogState clears every pending-* field on signal
        # so the next turn starts clean.
        from core.interrupt_bus import get_interrupt_bus  # noqa: PLC0415
        self._interrupt_bus = get_interrupt_bus()
        self._interrupt_bus.subscribe(
            "all",
            lambda sig: self.dialog_state.reset_pending(sig.reason),
        )
        self.assistant_context = AssistantContext()
        self.context_store = ContextStore()
        # Track 5.1a/b/c/d: expose all five domain stores directly. Same
        # instances as the delegators inside ContextStore, so writes
        # through either path land in the same SQLite tables (and same
        # Chroma collection for MemoryStore). After the 5.1e caller
        # sweep, `self.context_store` goes away and only these remain.
        self.session_store = self.context_store._session_store
        self.audit_store = self.context_store._audit_store
        self.workflow_store = self.context_store._workflow_store
        self.memory_store = self.context_store._memory_store
        self.knowledge_graph_store = self.context_store._knowledge_graph_store
        self.goal_store = self.context_store._goal_store
        # Track 6.1/6.2: environmental-awareness stores. AppIndexStore
        # persists SystemCapabilities.desktop_apps so the .desktop /
        # Start-Menu / Registry walk doesn't run on every boot.
        # FileIndexStore holds the background filesystem index keyed on
        # user directories.
        from core.stores import AppIndexStore, FileIndexStore  # noqa: PLC0415
        self.app_index_store = AppIndexStore(self.context_store.db_path)
        self.file_index_store = FileIndexStore(self.context_store.db_path)
        self.file_indexer = None  # built lazily in initialize()
        # Adaptive Intent Recognition (Phase 1): persists every routing
        # decision + the per-user learned-phrase ledger + usage profile.
        # Standalone like the Track 6 stores (not part of the ContextStore
        # facade — it's new and write-isolated to its own three tables).
        from core.stores import IntentLearningStore  # noqa: PLC0415
        self.intent_learning_store = IntentLearningStore(
            self.context_store.db_path,
            promote_after=int(self.config.get("routing.promote_after", 3) or 3),
        )
        # Track 6.3 (2026-05-23): lightweight screen lock. Tools route
        # through CapabilityExecutor's lock gate; chat stays available.
        from core.screen_lock import ScreenLock  # noqa: PLC0415
        self.screen_lock = ScreenLock()
        self.session_id = self.context_store.start_session({"entrypoint": "FridayApp"})
        # memory_service is created further below; bind now without it and
        # rebind once it exists so assistant_context can surface Mem0 facts
        # in chat prompts.
        self.assistant_context.bind_context_store(self.context_store, self.session_id)
        self.session_rag = SessionRAG()
        self.assistant_context.session_rag = self.session_rag
        self.capability_registry = CapabilityRegistry()
        self.capability_executor = CapabilityExecutor(self.capability_registry)
        # Track 6.3: wire the lock gate. Bypassed when screen_lock is
        # unconfigured (no env var) so behaviour is identical to the
        # pre-Track-6.3 build for users who don't set a PIN.
        self.capability_executor.screen_lock = self.screen_lock
        self.runtime_metrics = RuntimeMetrics()
        self.turn_feedback = TurnFeedbackRuntime(self.event_bus, config=self.config, metrics=self.runtime_metrics)
        self.persona_manager = PersonaManager(self.context_store)
        self.context_store.set_active_persona(self.session_id, self.persona_manager.DEFAULT_PERSONA_ID)
        # Phase 8: procedural plan archive. Shares the existing friday.db so
        # there's no new file to manage. Embedder is resolved lazily on first
        # save() so startup is fast even when sentence-transformers needs to
        # download the BGE model.
        try:
            from core.memory.plan_archive import PlanArchive  # noqa: PLC0415
            self.plan_archive = PlanArchive(self.context_store.db_path)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[app] PlanArchive unavailable: %s", exc)
            self.plan_archive = None
        self.memory_broker = MemoryBroker(
            self.context_store, self.persona_manager,
            plan_archive=self.plan_archive,
        )
        # Phase 2 (v2): unified memory facade. Hides ContextStore/MemoryBroker
        # behind one read/write surface so the storage layer can evolve
        # without touching every caller. New code targets app.memory_service;
        # legacy app.context_store access remains valid during the migration.
        # Phase 6: Mem0 components wired in after server probe (see further below)
        self.memory_service = MemoryService(self.context_store, self.memory_broker)
        # Port #3: audit trail — every capability execution is logged here.
        from core.audit_trail import AuditTrail  # noqa: PLC0415
        self.audit_trail = AuditTrail(self.memory_service, session_id=self.session_id)
        self.capability_executor.audit_trail = self.audit_trail
        # Phase 3: kernel services — stateless, injected into broker/agent
        self.consent_service = ConsentService(self.config)
        self.permission_service = PermissionService()
        # Phase 1: shared routing services — router writes, executors read
        self.routing_state = RoutingState()
        self.response_finalizer = ResponseFinalizer(self)
        self.router = CommandRouter(self.event_bus)
        # Start the sentence-transformers warmup the instant we have a
        # router. Earlier we tried this from initialize() but by then
        # plugin loading + persona load have already consumed ~1.5s; if
        # the user spoke a fast first prompt the warmup hadn't completed
        # yet and the "Loading weights 199/199" tqdm bar interleaved
        # with the turn. Kicking off here gives the warmup the maximum
        # head-start (it runs in parallel with the rest of __init__ +
        # extension_loader.load_all()).
        _embed_router = getattr(self.router, "embedding_router", None)
        if _embed_router is not None and hasattr(_embed_router, "_get_model"):
            import threading as _threading  # noqa: PLC0415
            _threading.Thread(
                target=_embed_router._get_model,
                name="embed-router-warmup",
                daemon=True,
            ).start()
        self.router.capability_registry = self.capability_registry
        self.router.routing_state = self.routing_state
        self.router.response_finalizer = self.response_finalizer
        self.router.dialog_state = self.dialog_state
        self.router.assistant_context = self.assistant_context
        self.router.context_store = self.context_store
        self.router.session_id = self.session_id
        self.workflow_orchestrator = WorkflowOrchestrator(self)
        self.router.workflow_orchestrator = self.workflow_orchestrator
        # Phase 3: reusable confirm-before-destructive-action guard. Wired
        # here (after router + executor exist) so destructive handlers can
        # arm a confirmation turn via `app.confirmation_guard`. The generic
        # confirm/cancel capabilities are routed by the IntentRecognizer's
        # `_parse_pending_destructive` interceptor.
        from core.workflows.confirmation import ConfirmationGuard  # noqa: PLC0415
        self.confirmation_guard = ConfirmationGuard(self)
        self.register_capability(
            {
                "name": "confirm_pending_action",
                "description": "Execute the destructive action awaiting confirmation.",
                "context_terms": [],
            },
            lambda raw_text, args: self.confirmation_guard.confirm(raw_text),
        )
        self.register_capability(
            {
                "name": "cancel_pending_action",
                "description": "Cancel the destructive action awaiting confirmation.",
                "context_terms": [],
            },
            lambda raw_text, args: self.confirmation_guard.cancel(),
        )
        # Phase 3 (checkpoint 4): reusable "which one did you mean?" guard.
        # Sibling of the confirmation guard — a capability that resolves a
        # request to >1 candidate arms a pick via `app.disambiguation_guard`;
        # the generic pick/cancel capabilities are routed by the
        # IntentRecognizer's `_parse_pending_pick` interceptor.
        from core.workflows.disambiguation import DisambiguationGuard  # noqa: PLC0415
        self.disambiguation_guard = DisambiguationGuard(self)
        self.register_capability(
            {
                "name": "pick_pending_candidate",
                "description": "Resolve the selection for the pending disambiguation pick.",
                "context_terms": [],
            },
            lambda raw_text, args: self.disambiguation_guard.pick(raw_text),
        )
        self.register_capability(
            {
                "name": "cancel_pending_pick",
                "description": "Cancel the pending disambiguation pick.",
                "context_terms": [],
            },
            lambda raw_text, args: self.disambiguation_guard.cancel(),
        )
        # Start model loading as early as possible — before initialize()
        # even runs. Gives models ~1s head start before HUD appears.
        import threading as _threading
        if hasattr(self.router, "model_manager"):
            _threading.Thread(
                target=self.router.model_manager.preload_requested_models,
                daemon=True,
            ).start()
        # Track 3.1 (Consolidation Direction): Gemma shadow router deleted.
        # Was trained on 49 tools but the runtime had ~56+; every turn
        # paid 130-1500ms for predictions nothing consumed. Removing it
        # also collapses the parallel-router count to 1, which is the
        # contract the v2 dispatch chain (intent → resolver → execute)
        # enforces. Attributes kept as None for one-release backward
        # compatibility with any out-of-tree caller doing
        # `getattr(app, "gemma_router", None)`.
        self.gemma_router = None
        self._gemma_trained_tools: set[str] = set()
        # Port #6: multi-agent hierarchy
        from core.agent_hierarchy import AgentHierarchy, AgentTaskManager, AgentNode  # noqa: PLC0415
        self.agent_hierarchy = AgentHierarchy()
        self.agent_task_manager = AgentTaskManager(self.agent_hierarchy, self.memory_service)
        # Register primary FRIDAY node
        self.agent_hierarchy.add_agent(AgentNode(
            agent_id="friday",
            name="FRIDAY",
            role="primary",
            authority_level=10,
        ))
        self.delegation_manager = DelegationManager(self)
        self.capability_broker = CapabilityBroker(self)
        self.ordered_tool_executor = OrderedToolExecutor(self)
        # Phase 4 (v2): DAG-based parallel executor. Selected via the
        # `routing.execution_engine: "parallel"` config flag (default
        # "ordered" stays current behavior). Single-step plans always
        # forward to ordered to skip pool overhead.
        self.task_graph_executor = TaskGraphExecutor(self)
        # Phase 3 (v2): WorkflowCoordinator + PlannerEngine can be built
        # now (their deps already exist). IntentEngine and TurnOrchestrator
        # need route_scorer / intent_recognizer which are constructed a
        # few lines below — wired further down.
        self.planner_engine = PlannerEngine(self.capability_broker)
        self.workflow_coordinator = WorkflowCoordinator(
            self.workflow_orchestrator, self.context_store
        )
        self.intent_engine = None
        self.turn_orchestrator = None
        self.conversation_agent = ConversationAgent(self)
        self.turn_manager = TurnManager(self, self.conversation_agent)
        self.speech_coordinator = SpeechCoordinator(self)
        self.capabilities = SystemCapabilities(self.config)
        self.extension_loader = ExtensionLoader(self)
        # Phase 5: expose IntentRecognizer directly (avoids going through router)
        self.intent_recognizer = self.router.intent_recognizer
        # Port #8: cloud LLM fallback chain (opt-in, respects local-first stance).
        from core.llm_providers.fallback_chain import FallbackChain  # noqa: PLC0415
        self.llm_fallback_chain = FallbackChain.from_config(self.config)
        if self.llm_fallback_chain.enabled:
            logger.info("[app] Cloud LLM fallback chain enabled.")
        # Phase 5: RouteScorer searches both router tools AND capability_registry
        # The lambda is evaluated at route-time so newly-registered extensions are visible.
        self.route_scorer = RouteScorer(lambda: self.router.tools + self._registry_routes())
        # Track 4.1b: give CommandRouter a back-reference to the canonical
        # scorer so `_find_best_route` can delegate. The router still owns
        # `register_tool` and the per-tool alias/pattern compilation;
        # SCORING (the cross-cutting "which tool best matches this text"
        # decision) lives on RouteScorer. When every pattern-matching
        # consumer migrates to `app.route_scorer.find_best_route(...)`,
        # the router's duplicated `_find_best_route` / `_score_route`
        # delete entirely.
        self.router.route_scorer = self.route_scorer
        # Phase 3 (v2): now that intent_recognizer + route_scorer exist,
        # build the IntentEngine adapter and the TurnOrchestrator.
        self.intent_engine = IntentEngine(self.intent_recognizer, self.route_scorer)
        self.turn_orchestrator = TurnOrchestrator(
            self,
            intent_engine=self.intent_engine,
            planner_engine=self.planner_engine,
            workflow_coordinator=self.workflow_coordinator,
            memory_broker=self.memory_broker,
        )
        # Phase 5 (v2): expose model_manager directly so callers (research,
        # planner, future extensions) can fetch per-domain inference locks
        # without depending on CommandRouter as a back-channel.
        self.model_manager = self.router.model_manager
        # Phase 5: ModelRouter for LLM-based tool selection
        self.model_router = ModelRouter(
            self.router.model_manager,
            timeout_ms=self.router.tool_timeout_ms,
            max_tokens=self.router.tool_max_tokens,
            target_max_tokens=self.router.tool_target_max_tokens,
            top_p=self.router.tool_top_p,
            json_response=self.router.tool_json_response,
        )
        # Kali planner Phase 3: optional structured-output planner used by
        # workflow selection / slot fill / observation summary / replan.
        # Default-off until Phase 4 lands the plan validator; when enabled
        # the broker (Phase 4+) routes ambiguous workflow intents through it.
        self.qwen_planner = None
        if (self.config.get("routing.use_qwen_planner") or False):
            try:
                from core.planning import QwenPlanner  # noqa: PLC0415
                self.qwen_planner = QwenPlanner(
                    self.router.model_manager,
                    timeout_ms=int(self.config.get("routing.qwen_planner_timeout_ms") or 12000),
                    max_tokens=int(self.config.get("routing.qwen_planner_max_tokens") or 512),
                    top_p=float(self.config.get("routing.qwen_planner_top_p") or 0.2),
                )
                logger.info("[app] QwenPlanner attached (routing.use_qwen_planner=true)")
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("[app] QwenPlanner unavailable: %s", exc)

        # Kali planner Phase 6: bounded replan controller. Wired regardless
        # of routing.use_replanning so callers can opt in per-call. The
        # controller is a stateless decision oracle; per-run state lives in
        # WorkflowRunState constructed by the workflow runner.
        try:
            from core.planning.replan_controller import (  # noqa: PLC0415
                ReplanController,
                DEFAULT_MAX_STEP_RETRIES,
                DEFAULT_MAX_WORKFLOW_STEPS,
                DEFAULT_WORKFLOW_TIMEOUT_SEC,
            )
            self.replan_controller = ReplanController(
                max_workflow_steps=int(
                    self.config.get("routing.max_workflow_steps") or DEFAULT_MAX_WORKFLOW_STEPS
                ),
                max_step_retries=int(
                    self.config.get("routing.max_step_retries") or DEFAULT_MAX_STEP_RETRIES
                ),
                workflow_total_timeout_sec=int(
                    self.config.get("routing.workflow_total_timeout_sec") or DEFAULT_WORKFLOW_TIMEOUT_SEC
                ),
                qwen_planner=self.qwen_planner,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[app] ReplanController unavailable: %s", exc)
            self.replan_controller = None
        # Phase 6: GraphCompiler for LangGraph-based execution (falls back to ordered)
        self.graph_compiler = GraphCompiler(self)
        # Phase 9: DialogueManager for contextual acks and tone adaptation
        self.dialogue_manager = DialogueManager(self.config)
        # Phase 10: ResultCache for TTL-based capability result caching
        self.result_cache = ResultCache()
        # Task runner: each voice command runs in a daemon thread so the STT
        # listen-loop is never blocked and commands can be cancelled.
        self.task_runner = TaskRunner(self)
        # Phase 2: lifecycle manager owns ordered teardown
        self.lifecycle = LifecycleManager()
        self.gui_callback = None
        self.is_speaking = False
        # TTS reference — set by VoiceIOPlugin after it constructs TextToSpeech
        self.tts = None
        self.stt = None
        self.media_control_mode = False
        self._active_turn_record = None
        # Phase 1 (v2): unified per-turn ephemeral state. Set by TurnManager
        # at turn start, cleared in the finally branch.
        self.current_turn_context = None
        self._last_turn_speech_managed = False
        self._shutdown_requested = False
        self._turn_lock = __import__("threading").Lock()
        self.resource_monitor = ResourceMonitor()

        # Track 2.3 (Consolidation Direction): Mem0 deleted. Canonical
        # fact writer/reader is `self.memory_broker.facts` (MemoryFacade).
        # Ambient extraction runs synchronously via MemoryBroker.curate.
        # The mem0_client / mem0_extractor attributes are retained as None
        # so any out-of-tree caller doing `getattr(app, "_mem0_extractor")`
        # gets a benign None instead of AttributeError.
        self._mem0_client = None
        self._mem0_extractor = None
        self.memory_service = MemoryService(
            self.context_store,
            self.memory_broker,
        )
        # Now that memory_service exists, give assistant_context a handle so
        # build_chat_messages can inject user_facts into the chat prompt.
        try:
            self.assistant_context.memory_service = self.memory_service
        except Exception:
            pass

        # P3.9: routine scheduler. Reads config/routines.yaml. Starts
        # lazily in initialize() so tests that build FridayApp without
        # calling initialize() don't spawn a background thread.
        self.scheduler = None

        # P3.5: end-of-turn memory nudger. Cheap regex pass over the user's
        # message catches durable personal facts (employer, location,
        # preferences) the explicit `remember` intent missed.
        # Writes through MemoryFacade so both memory_items and facts tables
        # stay in sync — fixes the "Who am I?" recall bug where facts
        # written by the nudger were invisible to recall_personal_fact.
        try:
            from core.memory_nudger import make_nudger  # noqa: PLC0415
            mm_facade = getattr(self.memory_broker, "facts", None)
            self.memory_nudger = make_nudger(mm_facade, llm=None)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[app] MemoryNudger unavailable: %s", exc)
            self.memory_nudger = None

        # P3.4: attach a ContextCompressor so long sessions stay under the
        # model's context window. The LLM-backed summary path activates
        # lazily when the chat model is loaded; until then the compressor
        # falls back to drop-oldest trimming.
        try:
            from core.context_compressor import make_compressor  # noqa: PLC0415
            max_ctx = int(self.config.get("llm.max_context_tokens") or 4096)
            # Trigger at 80% per Hermes design; leaves headroom for response.
            budget = max(512, int(max_ctx * 0.8))
            self.context_compressor = make_compressor(max_tokens=budget, llm=None)
            self.assistant_context.context_compressor = self.context_compressor
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[app] ContextCompressor unavailable: %s", exc)
            self.context_compressor = None

    def initialize(self):
        logger.info("Initializing FRIDAY...")
        self.config.load()
        self.capabilities.probe()
        try:
            from modules.system_control.app_launcher import configure_app_registry  # noqa: PLC0415
            configure_app_registry(self.capabilities)
        except Exception as e:
            logger.warning("App registry configuration failed: %s", e)
        try:
            self._persist_app_index()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[app] App index persistence failed: %s", e)
        try:
            self._start_file_indexer()
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[app] File indexer startup failed: %s", e)
        if hasattr(self.router, "refresh_runtime_settings"):
            self.router.refresh_runtime_settings()
        self.extension_loader.load_all()
        # Phase 10: configure trace export path
        _data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
        configure_trace_export(os.path.join(_data_dir, "traces.jsonl"))

        # Embedding router warmup is now kicked off in __init__ right
        # after the router is built (see "embed-router-warmup" thread
        # there). By the time we reach initialize() the warmup has
        # usually finished; the second-kick here is a defensive no-op
        # because `_get_model()` short-circuits when the model is loaded.

        # P3.9: start the routine scheduler (no-op when routines.yaml is empty).
        try:
            from core.scheduler import make_scheduler_from_config  # noqa: PLC0415
            project_root = os.path.dirname(os.path.dirname(__file__))
            routines_path = os.path.join(project_root, "config", "routines.yaml")
            self.scheduler = make_scheduler_from_config(
                routines_path,
                dispatch=lambda cmd: self.process_input(cmd, source="scheduler"),
            )
            if self.scheduler._routines:
                self.scheduler.start()
                self.lifecycle.register(self.scheduler, name="scheduler")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[app] Scheduler unavailable: %s", exc)

        # 2026-05-24 — cross-check the catalog against the live tool
        # registry once all plugins are loaded. Warns about catalog
        # entries that point at unregistered tools (stale) and registered
        # tools that lack a catalog entry (missing). Never blocks boot.
        try:
            from core.tool_catalog import get_catalog  # noqa: PLC0415
            catalog = get_catalog()
            # 2026-05-24 — capabilities can be registered via the router
            # (`_tools_by_name`) OR via the newer `capability_registry`.
            # Pass the UNION so we don't false-alarm on entries that
            # exist only in the registry (16+ rows including ha_*,
            # get_calendar_*, daily_briefing, …).
            tools_by_name = dict(getattr(self.router, "_tools_by_name", {}) or {})
            cap_reg = getattr(self, "capability_registry", None)
            if cap_reg is not None and hasattr(cap_reg, "list_capabilities"):
                try:
                    for cap in cap_reg.list_capabilities():
                        name = getattr(cap, "name", None) or (
                            cap.get("name") if isinstance(cap, dict) else None
                        )
                        if name and name not in tools_by_name:
                            tools_by_name[name] = cap
                except Exception:
                    pass
            catalog.bind_registry(tools_by_name)
        except Exception as exc:
            logger.debug("[app] catalog cross-check skipped: %s", exc)

        # Adaptive Intent Phase 6: apply config-tuned routing thresholds, then
        # Phase 4: replay learned phrasings into the embedding router so
        # day-by-day adaptation survives restarts (the lexical router picks up
        # promoted phrasings lazily via _promoted_phrase_pairs).
        self._apply_routing_thresholds()
        self._load_learned_phrases()

        # Mirror the real OS screen-lock state into the capability gate and
        # notify the user over Telegram on every lock/unlock. Started here
        # (after the comms plugin has loaded so `self.comms` exists).
        try:
            from core.lock_monitor import LockStateMonitor  # noqa: PLC0415
            self.lock_monitor = LockStateMonitor(self, self.screen_lock)
            self.lock_monitor.start()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[app] lock monitor not started: %s", exc)
            self.lock_monitor = None

        logger.info("FRIDAY initialized successfully.")

    def _apply_routing_thresholds(self) -> None:
        """Push config-tuned thresholds onto the live routers (Phase 6).

        The defaults are validated by `core/routing_tuner.py`; these keys let
        them be re-tuned from config without editing source. Read at route
        time, so setting them post-construction is safe."""
        cfg = getattr(self, "config", None)
        if cfg is None or not hasattr(cfg, "get"):
            return
        router = getattr(self, "router", None)
        embed = getattr(router, "embedding_router", None) if router else None
        lex = getattr(router, "lexical_router", None) if router else None

        def _f(key, default):
            try:
                return float(cfg.get(key, default))
            except (TypeError, ValueError):
                return default

        if embed is not None:
            embed.dispatch_threshold = _f("routing.dispatch_threshold", embed.dispatch_threshold)
            embed.confirm_low = _f("routing.confirm_low", embed.confirm_low)
            embed.tie_epsilon = _f("routing.tie_epsilon", embed.tie_epsilon)
        if lex is not None:
            lex.threshold = _f("routing.lexical_threshold", lex.threshold)
            lex.margin = _f("routing.lexical_margin", lex.margin)
        logger.info("[app] Routing thresholds applied from config.")

    def _load_learned_phrases(self) -> None:
        """Register non-blocked learned phrasings into the embedding router."""
        store = getattr(self, "intent_learning_store", None)
        router = getattr(self, "router", None)
        embed = getattr(router, "embedding_router", None) if router else None
        if store is None or embed is None or not hasattr(embed, "add_phrase"):
            return
        try:
            phrases = store.active_phrases()
        except Exception:
            logger.debug("[app] learned-phrase load skipped", exc_info=True)
            return
        loaded = 0
        for row in phrases:
            raw = row.get("raw") or row.get("normalized") or ""
            tool = row.get("tool") or ""
            if raw and tool and embed.add_phrase(raw, tool):
                loaded += 1
        if loaded:
            logger.info("[app] Replayed %d learned phrasing(s) into the router.", loaded)
        # Phase 5: inject the profile tie-breaker so near-tied embedding
        # candidates resolve toward the tool the user actually uses.
        if hasattr(embed, "set_tie_breaker"):
            def _tie_breaker(candidates, _store=store):
                scored = [(t, _store.profile_score(t)) for t, _ in candidates]
                best_tool, best_score = max(scored, key=lambda ts: ts[1])
                return best_tool if best_score > 0 else None
            try:
                embed.set_tie_breaker(_tie_breaker)
            except Exception:
                logger.debug("[app] tie-breaker wiring skipped", exc_info=True)

    def _maybe_handle_input_prefix(self, text: str, source: str):
        """Track 6.3 — short-circuit `/cmd`, `!cmd`, and `>` follow-ups.

        Returns the response string when *text* is handled here; returns
        None to let the normal turn-orchestrator path run.

        Shell session rules (added 2026-05-23):
        * A `>` prefixed message goes to the active shell session's
          stdin. If no session is alive, it's a hard error (never falls
          through to chat).
        * While a shell session is alive, ANY non-`>` message cancels
          the session and is then handled normally. This is the rule
          that prevents a stray "yes" from being interpreted by the LLM
          while sudo is waiting on a password.
        """
        from core import shell_prefix as _shell  # noqa: PLC0415
        from core import slash_commands as _slash  # noqa: PLC0415

        stripped = (text or "").lstrip()

        # ── `>` follow-up to a running shell session ──────────────────
        if _shell.is_shell_followup(stripped):
            self.emit_message("user", text, source=source)
            if _shell.has_active_session():
                response = _shell.feed_followup(stripped)
            else:
                response = "No active shell command. Start one with `!<cmd>` first."
            self.emit_assistant_message(response, source="friday", speak=False)
            return response

        # ── While a shell session is alive, intercept everything ──────
        # else so a stray "yes" / "1234" doesn't leak to chat mode.
        if _shell.has_active_session() and not _slash.is_slash_command(stripped):
            cancel_note = _shell.cancel_active_session(reason="user input")
            self.emit_message("user", text, source=source)
            warning = (
                "Cancelled the running shell command — your message wasn't "
                "piped to its stdin because it didn't start with `> `. Use "
                "`> <text>` next time to send input. The command output so "
                "far is above."
            )
            response = f"{cancel_note or ''}\n\n{warning}".strip()
            self.emit_assistant_message(response, source="friday", speak=False)
            return response

        if _slash.is_slash_command(stripped):
            self.emit_message("user", text, source=source)
            response = _slash.dispatch(self, stripped) or ""
            self.emit_assistant_message(response, source="friday", speak=(source != "telegram"))
            return response

        if _shell.is_shell_command(stripped):
            self.emit_message("user", text, source=source)
            lock = getattr(self, "screen_lock", None)
            if lock is not None and lock.is_locked():
                response = "Shell access is locked. Run /unlock <pin> first."
            else:
                response = _shell.run_shell(stripped)
            self.emit_assistant_message(response, source="friday", speak=False)
            return response
        return None

    def _start_file_indexer(self) -> None:
        """Track 6.2 — instantiate the FileIndexer and kick off a scan.

        Background scan runs in a daemon thread so initialize() returns
        immediately. If watchdog is installed, also attach a live
        observer; otherwise the index updates only on explicit
        `refresh_file_index` calls.
        """
        from modules.system_control.file_indexer import FileIndexer  # noqa: PLC0415
        self.file_indexer = FileIndexer(self.file_index_store)
        # Hold the initial filesystem walk back so it doesn't contend with
        # model loading + the first user turns at startup. Tunable via
        # `file_index.initial_delay_s` (default 20s).
        delay = 20.0
        cfg = getattr(self, "config", None)
        if cfg is not None and hasattr(cfg, "get"):
            try:
                delay = float(cfg.get("file_index.initial_delay_s", 20.0) or 20.0)
            except (TypeError, ValueError):
                delay = 20.0
        self.file_indexer.start_background_scan(initial_delay=delay)
        try:
            self.file_indexer.start_watcher()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[app] file indexer watcher failed: %s", exc)

    def _persist_app_index(self) -> None:
        """Track 6.1 — write SystemCapabilities.desktop_apps to AppIndexStore.

        Called from `initialize()` after `capabilities.probe()`. Idempotent
        (upserts on canonical) so subsequent calls overwrite rather than
        duplicate. Used by the `refresh_app_index` capability too.
        """
        apps = getattr(self.capabilities, "desktop_apps", {}) or {}
        rows = []
        for key, app in apps.items():
            canonical = key
            aliases = set(getattr(app, "aliases", set()) or set())
            aliases.add(canonical)
            rows.append({
                "canonical": canonical,
                "name": getattr(app, "name", canonical) or canonical,
                "command": getattr(app, "command", ""),
                "exec_line": getattr(app, "exec_line", ""),
                "desktop_id": getattr(app, "desktop_id", ""),
                "source": getattr(app, "source", "desktop"),
                "aliases": aliases,
                "categories": getattr(app, "categories", []) or [],
            })
        # Replace contents wholesale so apps uninstalled since last boot
        # don't leak forward as stale rows.
        self.app_index_store.clear_all()
        n = self.app_index_store.bulk_upsert(rows)
        logger.info("[app] AppIndexStore persisted %d desktop apps", n)

    # Wall-clock cap on the *graceful* shutdown phase. After this, the
    # caller (`closeEvent` / signal handler) is expected to force-exit
    # the process. The number is empirical: STT close, TTS drain, and
    # Playwright tear-down all complete in well under a second on a
    # warm cache. Anything slower than 2.5s is almost always
    # `_snapshot_session_on_exit` waiting on a chat-LLM round-trip,
    # which we now run with its own deadline below.
    _GRACEFUL_SHUTDOWN_DEADLINE_S = 2.5
    _SNAPSHOT_DEADLINE_S = 1.5

    def shutdown(self, *, deadline_s: float | None = None) -> None:
        """Perform cleanup for a graceful exit, BOUNDED by *deadline_s*.

        2026-05-24 — exit was laggy and sometimes triggered the Qt
        "force quit" dialog because:
          (a) `_snapshot_session_on_exit` makes an LLM call (~5-30s).
          (b) `lifecycle.stop_all` called each service's `stop()`
              serially, with no per-service timeout.
        The new shape:
          • Snapshot runs in a daemon thread with its own deadline; if
            it doesn't finish in time, we let the process die with the
            transcript unflushed (a few episodic rows lost, never a hung
            UI).
          • Lifecycle stop runs in a daemon thread; the main shutdown
            thread joins with `deadline_s` then returns.
          • Caller is still responsible for `sys.exit()` /
            `os._exit()` — we do not call them here so the Qt event
            loop can exit cleanly when it can.
        """
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        import threading as _threading  # noqa: PLC0415
        import time as _time  # noqa: PLC0415

        # Notify Telegram before we tear anything down so the message
        # reaches the user before the process exits.
        try:
            if (getattr(self, "comms", None) and
                    getattr(self.comms, "telegram", None) and
                    hasattr(self.comms.telegram, "send")):
                self.comms.telegram.send("FRIDAY is going offline.")
        except Exception:
            logger.debug("[shutdown] Telegram notification skipped")

        started = _time.monotonic()
        deadline = float(deadline_s if deadline_s is not None else self._GRACEFUL_SHUTDOWN_DEADLINE_S)
        logger.info("FRIDAY: Performing graceful shutdown (deadline=%.1fs)...", deadline)

        # Fast, blocking steps — STT + TTS both return in tens of ms.
        if self.stt and hasattr(self.stt, "shutdown"):
            try:
                self.stt.shutdown()
            except Exception:
                logger.exception("[shutdown] STT shutdown error")

        if self.tts and hasattr(self.tts, "stop"):
            try:
                self.tts.stop()
            except Exception:
                logger.exception("[shutdown] TTS stop error")

        # Background snapshot — own deadline.
        snap_thread = _threading.Thread(
            target=self._snapshot_session_on_exit_safe,
            name="friday-shutdown-snapshot",
            daemon=True,
        )
        snap_thread.start()
        snap_thread.join(timeout=self._SNAPSHOT_DEADLINE_S)
        if snap_thread.is_alive():
            logger.warning(
                "[shutdown] session snapshot still running after %.1fs — abandoning",
                self._SNAPSHOT_DEADLINE_S,
            )

        # Background lifecycle stop — own deadline derived from the
        # remaining budget so total wall-clock stays ≤ `deadline`.
        remaining = max(0.3, deadline - (_time.monotonic() - started))
        stop_thread = _threading.Thread(
            target=self._lifecycle_stop_safe,
            name="friday-shutdown-lifecycle",
            daemon=True,
        )
        stop_thread.start()
        stop_thread.join(timeout=remaining)
        if stop_thread.is_alive():
            logger.warning(
                "[shutdown] lifecycle stop still running after %.1fs — abandoning",
                remaining,
            )

        elapsed = _time.monotonic() - started
        logger.info("FRIDAY: Cleanup complete in %.2fs.", elapsed)

    def _snapshot_session_on_exit_safe(self) -> None:
        try:
            self._snapshot_session_on_exit()
        except Exception as exc:
            logger.warning("[shutdown] session snapshot skipped: %s", exc)

    def _lifecycle_stop_safe(self) -> None:
        try:
            self.lifecycle.stop_all()
        except Exception as exc:
            logger.warning("[shutdown] lifecycle stop_all error: %s", exc)

    def _snapshot_session_on_exit(self) -> None:
        if not self.session_id:
            return
        from core.session_summarizer import make_summarizer  # noqa: PLC0415
        llm = None
        mm = getattr(self.router, "model_manager", None)
        if mm is not None:
            try:
                llm = mm.get_chat_model() if hasattr(mm, "get_chat_model") else None
            except Exception:
                llm = None
        summarizer = make_summarizer(
            self.session_store, llm=llm, memory_store=self.memory_store,
        )
        summarizer.on_session_switch(self.session_id)

    def gemma_predict(self, text: str) -> "tuple[str | None, float]":
        """Track 3.1: no-op kept as the legacy symbol for one release so any
        out-of-tree caller doesn't crash. Returns (None, 0.0). The Gemma
        shadow router was deleted (see Track 3.1 in STATUS.md)."""
        return None, 0.0

    def dispatch_sub_text(self, text: str) -> str:
        """Track 3.2b: dispatch a piece of text and return its response,
        WITHOUT entering a new TurnManager turn.

        Used by sub-dispatchers that are already inside an active turn —
        delegation agents, file-workspace pending-clarification redispatch,
        etc. — and want a `text → response` round-trip via the v2 stack
        (intent → execute) without triggering nested-turn side effects
        (router-fire counter, span recording, turn locks).

        Behavior:
          1. Run `intent_recognizer.plan(text)` to find a tool action.
             If found, dispatch via `capability_executor.execute(...)`.
          2. If no action, fall back to `llm_chat` directly via the
             capability executor.

        Returns the response string. On any unexpected failure, falls
        back to the legacy `router.process_text` so existing behaviour
        is preserved during the migration.
        """
        executor = getattr(self, "capability_executor", None)
        if executor is None:
            return self.router.process_text(text)
        try:
            actions = self.router.intent_recognizer.plan(text)
        except Exception:
            actions = []
        for action in (actions or []):
            tool = action.get("tool") or ""
            args = dict(action.get("args") or {})
            raw_text = action.get("text") or text
            if not tool:
                continue
            try:
                result = executor.execute(tool, raw_text, args)
            except Exception:
                continue
            if result.ok and (result.output or "").strip():
                return result.output
        # No deterministic action matched — fall back to llm_chat.
        if self.capability_registry.has_capability("llm_chat"):
            try:
                result = executor.execute("llm_chat", text, {"query": text})
                if result.ok:
                    return result.output or ""
            except Exception:
                pass
        # Legacy last-resort.
        return self.router.process_text(text)

    def _shadow_route_with_gemma(self, text: str) -> None:
        """Track 3.1: no-op kept as the legacy symbol for one release so any
        out-of-tree caller doesn't crash. The Gemma shadow router was
        deleted (see Track 3.1 in STATUS.md)."""
        return None

    def register_capability(self, spec: dict, handler, metadata: dict | None = None):
        """Track 4.1b (Consolidation Direction): canonical entry point for
        plugins to register a capability.

        Internally calls `self.router.register_tool(spec, handler,
        capability_meta=metadata)`, which already populates BOTH the
        router's pattern-match tables AND the `capability_registry`
        descriptor store — so the migration target is "use this method"
        and nothing else changes structurally.

        Plugins should migrate from `app.router.register_tool(spec, cb,
        capability_meta=meta)` → `app.register_capability(spec, cb,
        metadata=meta)`. Both end-states populate the same stores;
        the migration is a NAMING unification.

        When every plugin has migrated, `app.router.register_tool` can
        be repurposed as a private routing helper (or deleted entirely
        if Track 4.1b's pattern-matching extraction also lands).
        """
        return self.router.register_tool(spec, handler, capability_meta=metadata)

    _RAG_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".html", ".csv"}

    def _resolve_rag_file_path(self, text: str) -> "str | None":
        """Return a local file path if *text* looks like a supported document, else None."""
        from urllib.parse import urlparse, unquote
        t = (text or "").strip()
        candidates = []
        if t.startswith("file://"):
            try:
                candidates.append(unquote(urlparse(t).path))
            except Exception:
                pass
        if t.startswith("/"):
            candidates.append(t)
        for path in candidates:
            path = path.strip()
            if os.path.isfile(path) and os.path.splitext(path)[1].lower() in self._RAG_EXTENSIONS:
                return path
        return None

    def process_input(self, text, source="user"):
        """Process user input.

        Voice commands are dispatched to TaskRunner so the STT listen-loop
        returns immediately and is never blocked for the duration of a turn.
        Text/GUI commands run synchronously as before.
        """
        # Intercept file paths (dropped, typed, or pasted) before routing to LLM.
        file_path = self._resolve_rag_file_path(text)
        if file_path:
            import threading
            name = os.path.basename(file_path)
            self.emit_message("user", f"[Load file: {name}]", source=source)

            def _load():
                msg = self.load_session_rag_file(file_path)
                self.emit_assistant_message(msg, speak=True)

            threading.Thread(target=_load, daemon=True).start()
            return ""

        # Track 6.3 (2026-05-23): / and ! prefixes are pre-routing
        # short-circuits that work the same way in the GUI input box and
        # over Telegram. Voice is excluded — STT can't reliably produce
        # leading punctuation, so this would just be dead code there.
        if source != "voice":
            prefix_response = self._maybe_handle_input_prefix(text, source)
            if prefix_response is not None:
                return prefix_response

        if source != "voice" and self.is_speaking:
            tts = getattr(self, "tts", None)
            if tts:
                tts.stop()

        self.routing_state.clear_voice_spoken()
        self.emit_message("user", text, source=source)

        # Shadow-run the optional LoRA-tuned Gemma router for visibility.
        # No-op when FRIDAY_USE_GEMMA_ROUTER is unset (gemma_router is None).
        self._shadow_route_with_gemma(text)

        if source in ("voice", "gui"):
            if source == "voice":
                # Mute the mic button immediately so the GUI shows "idle/processing"
                # while the turn runs. The post-turn finally block will re-emit the
                # correct state (True for persistent/wake_word, False for on_demand).
                self.event_bus.publish("gui_toggle_mic", False)
                # Keep mic open so the user can barge in by saying "Friday [command]"
                # while the task is running. The reactor shows "processing" via
                # set_processing_state; stop_listening() is intentionally not called.
                if self.stt and hasattr(self.stt, "set_processing_state"):
                    self.stt.set_processing_state(True)
            self.task_runner.submit(text, source)
            return ""

        return self._execute_turn(text, source)

    def load_session_rag_file(self, path: str) -> str:
        """Load a file into the session RAG context. Returns a status message."""
        from core.logger import logger as _log
        try:
            msg = self.session_rag.load_file(path)
            # Drop the previous document's Q&A from history so the chat model
            # answers about the newly loaded file, not the one before it
            # (2026-05-29 cross-document bleed fix).
            ac = getattr(self, "assistant_context", None)
            if ac is not None and hasattr(ac, "prune_document_turns"):
                ac.prune_document_turns()
            _log.info("[session_rag] %s", msg)
            return msg
        except Exception as exc:
            _log.warning("[session_rag] Failed to load %s: %s", path, exc)
            return f"Could not load file: {exc}"

    def _execute_turn(self, text, source="user", cancel_event=None):
        """Synchronous turn processing — called directly (text/GUI) or via TaskRunner (voice)."""
        self._current_cancel_event = cancel_event
        route_text = text
        if self.assistant_context and hasattr(self.assistant_context, "clean_user_text"):
            cleaned = self.assistant_context.clean_user_text(text, source=source)
            if cleaned:
                route_text = cleaned

        # Strip the GUI's [Re: filename] attachment prefix before routing.
        # The file was already loaded into session_rag; the prefix only causes
        # the intent recognizer to misroute the question to open_file/read_file.
        _stripped = re.sub(r'^\[Re:[^\]]+\]\s*', '', route_text, flags=re.IGNORECASE).strip()
        if _stripped and _stripped != route_text:
            route_text = _stripped

        try:
            self._last_turn_speech_managed = False
            response = self.turn_manager.handle_turn(route_text, source=source)

            decision = self.routing_state.last_decision
            if decision:
                if decision.tool_name in ("play_youtube", "play_youtube_music", "browser_media_control"):
                    if not self.media_control_mode:
                        logger.info("[app] Entering Restricted Media Control Mode.")
                        self.media_control_mode = True
                        self.event_bus.publish("media_control_mode_changed", {"active": True})

                if decision.tool_name == "enable_voice" and decision.args.get("wake_up"):
                    if self.media_control_mode:
                        logger.info("[app] Exiting Restricted Media Control Mode.")
                        self.media_control_mode = False
                        self.event_bus.publish("media_control_mode_changed", {"active": False})
                        response = "I'm awake! How can I help you?"

            if response:
                self.emit_assistant_message(
                    response,
                    source="friday",
                    speak=not getattr(self, "_last_turn_speech_managed", False),
                )
                # Track 2.3: Mem0 extraction queue deleted. Ambient fact
                # extraction now runs synchronously through
                # MemoryBroker.curate via the canonical MemoryFacade.
                try:
                    broker = getattr(self, "memory_broker", None)
                    if broker is not None and self.session_id:
                        broker.curate(self.session_id, route_text, response)
                except Exception as e:
                    logger.warning("MemoryBroker.curate failed: %s", e)
                # P3.5: nudger — cheap regex over the user's message, then
                # optional LLM confirm. Silent on save (no extra TTS).
                try:
                    nudger = getattr(self, "memory_nudger", None)
                    if nudger is not None and self.session_id:
                        nudger.observe(route_text, self.session_id)
                except Exception as e:
                    logger.warning("MemoryNudger.observe failed: %s", e)
            return response
        finally:
            if source == "voice":
                if self.stt and hasattr(self.stt, "set_processing_state"):
                    self.stt.set_processing_state(False)
                self.event_bus.publish("gui_toggle_mic", self.should_resume_voice_after_turn())

    def cancel_current_task(self, announce: bool = True) -> bool:
        """Cancel any running voice task. Returns True if something was running."""
        # Signal the interrupt bus so research, workflow orchestrator, and
        # dialog-state all reset before we cancel the task-runner thread.
        try:
            self._interrupt_bus.signal("user_cancel", scope="all")
        except Exception:
            pass
        return self.task_runner.cancel_current(announce=announce)

    def _registry_routes(self) -> list:
        """Expose capability_registry entries as route dicts for RouteScorer."""
        from core.reasoning.route_scorer import RouteScorer  # noqa: PLC0415
        routes = []
        try:
            caps = self.capability_registry.list_capabilities()
        except Exception:
            return routes
        for cap in caps:
            spec = {
                "name": cap.name,
                "description": getattr(cap, "description", "") or "",
                "parameters": {},
            }
            routes.append(RouteScorer.build_route_entry(spec, None))
        return routes

    def get_listening_mode(self):
        mode = ""
        if self.config and hasattr(self.config, "get"):
            mode = str(self.config.get("conversation.listening_mode", "persistent") or "").strip().lower().replace("-", "_")
        if mode not in {"persistent", "wake_word", "on_demand", "manual"}:
            mode = "persistent"
        return mode

    def set_listening_mode(self, mode):
        mode = str(mode or "").strip().lower().replace("-", "_")
        aliases = {
            "ondemand": "on_demand",
            "on demand": "on_demand",
            "always_on": "persistent",
            "always on": "persistent",
            "wakeword": "wake_word",
            "wake word": "wake_word",
            "wake": "wake_word",
            "off": "manual",
        }
        mode = aliases.get(mode, mode)
        if mode not in {"persistent", "wake_word", "on_demand", "manual"}:
            return self.get_listening_mode()

        if self.config and hasattr(self.config, "set"):
            self.config.set("conversation.listening_mode", mode)
            if hasattr(self.config, "save"):
                self.config.save()
        else:
            config_payload = getattr(self.config, "config", None)
            if isinstance(config_payload, dict):
                next_config = copy.deepcopy(config_payload)
                next_config.setdefault("conversation", {})["listening_mode"] = mode
                self.config.config = next_config

        self.event_bus.publish("listening_mode_changed", {"mode": mode})
        if mode in {"persistent", "wake_word"}:
            self.event_bus.publish("gui_toggle_mic", True)
        else:
            self.event_bus.publish("gui_toggle_mic", False)
        return mode

    def should_auto_start_voice(self):
        return self.get_listening_mode() in {"persistent", "wake_word"}

    def should_resume_voice_after_turn(self):
        return self.get_listening_mode() in {"persistent", "wake_word"}

    def set_gui_callback(self, callback):
        """Allows GUI to register a callback to receive conversation payloads."""
        self.gui_callback = callback

    def emit_message(self, role, text, source=None):
        if role == "assistant":
            text = strip_model_artifacts(text)
        payload = {
            "role": role,
            "text": text,
            "source": source or role,
        }
        logger.info(f"[{role.upper()}]: {text}")
        self.assistant_context.record_message(role, text, source=payload["source"])
        if getattr(self, "context_store", None) and getattr(self, "session_id", None):
            self.context_store.append_turn(self.session_id, role, text, source=payload["source"])
        if self.gui_callback:
            self.gui_callback(payload)
        self.event_bus.publish("conversation_message", payload)
        return payload

    def emit_assistant_message(self, text, source="friday", speak=True, spoken_text=None):
        self.emit_message("assistant", text, source=source)
        if speak and not self.routing_state.voice_already_spoken:
            self.event_bus.publish("voice_response", spoken_text if spoken_text is not None else text)
        self.routing_state.clear_voice_spoken()
