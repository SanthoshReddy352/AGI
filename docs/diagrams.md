# FRIDAY AI Assistant — Architectural Graphics and Diagrams Reference

This document serves as the single, unified master graphics reference for the **FRIDAY AI Assistant**. It covers all structural layers, single-turn lifecycles, voice I/O pipelines, parallel task execution engines, unified storage facades, and stateful multi-turn workflow engines.

All diagrams are written in GFM-supported **Mermaid** syntax, checked for semantic correctness, and aligned with the actual **v2 codebase architecture**.

---

## 1. High-Level Core & Bootstrap Layer

### 1.1 High-Level Architecture & Layer Map
This flowchart showcases how individual layers interact, separating deterministic routing from LLM-based parallel task execution, backed by a unified memory facade.

```mermaid
flowchart TB
    subgraph UI ["Interface Layer"]
        VI[VoiceInterface\nSTT & microphone]
        TI[TextInterface\nCLI & GUI HUD]
    end

    subgraph ORCH ["Orchestration & Boot Layer"]
        RK[RuntimeKernel\nServiceContainer DI shell]
        TO[TurnOrchestrator\nSingle entry turn control flow]
        TM[TurnManager\nContext & Feedback runner]
    end

    subgraph PLAN ["Planning & Routing Layer"]
        IE[IntentEngine\nDeterministic fast path]
        PE[PlannerEngine\nLLM tool caller]
        WC[WorkflowCoordinator\nActive workflow check]
        CR[CapabilityRegistry\nMCP Tool descriptors]
    end

    subgraph EXEC ["Execution & Action Layer"]
        TGE[TaskGraphExecutor\nWave-based DAG parallel]
        RC[ResultCache\nTTL outcome caching]
    end

    subgraph MEM ["Unified Memory Layer"]
        MS[MemoryService\nfacade read/write]
        MB[MemoryBroker\nEpisodic/Semantic/Procedural]
        SS[SessionStore\nSQLite storage facade]
        CS[ContextStore\nSQLite & ChromaDB]
    end

    subgraph INFRA ["Infrastructure Layer"]
        EB[EventBus\nAsync pub/sub]
        TR[TurnTracer\nStructured Spans]
        CFG[ConfigService]
    end

    UI --> ORCH
    ORCH --> PLAN
    PLAN --> EXEC
    EXEC --> PLAN
    PLAN --> MEM
    EXEC --> MEM
    ORCH --> INFRA
```

### 1.2 Bootstrap Sequence
This sequence details how `main.py` boots the `RuntimeKernel`, registers all active service dependencies inside the `ServiceContainer`, and links back-compat facades for the underlying `FridayApp`.

```mermaid
sequenceDiagram
    autonumber
    participant User as User / OS
    participant Main as main.py
    participant RK as RuntimeKernel
    participant SC as ServiceContainer
    participant FA as FridayApp
    participant CM as ConfigService
    participant EB as EventBus
    participant LM as LifecycleManager

    User->>Main: python main.py [--gui|--text]
    Main->>RK: boot(app=None)
    RK->>FA: Construct FridayApp()
    FA->>CM: Load config.yaml
    FA->>EB: Initialize EventBus()
    FA->>LM: Initialize LifecycleManager()
    RK->>RK: _populate_container_from_app()
    Note over RK,SC: ServiceContainer registers types lazily:<br/>EventBus, MemoryService, ModelManager, etc.
    RK->>SC: register_instance(RuntimeKernel, self)
    Main->>RK: initialize()
    RK->>FA: initialize() (preload models, load extensions)
    Main->>Main: start CLI or PyQt6 GUI HUD
```

### 1.3 Runtime & Kernel Class Diagram
The structure of the dependency-injection shell that manages lazy registration and lifecycle operations for the services catalog.

```mermaid
classDiagram
    class RuntimeKernel {
        +app: FridayApp
        +container: ServiceContainer
        +lifecycle: LifecycleManager
        +boot(app) RuntimeKernel$
        +initialize() RuntimeKernel
        +shutdown()
        +handle_request(request) TurnResponse
        +get(Type) Service
    }
    class ServiceContainer {
        -inner: Container
        +register(Type, factory, lifecycle)
        +register_instance(Type, instance)
        +get(Type) Service
        +is_registered(Type) bool
    }
    class LifecycleManager {
        -services: list~Startable~
        +register(service)
        +start_all()
        +stop_all()
    }
    class FridayApp {
        +config: ConfigManager
        +event_bus: EventBus
        +turn_orchestrator: TurnOrchestrator
        +task_graph_executor: TaskGraphExecutor
        +memory_service: MemoryService
        +initialize()
        +shutdown()
    }
    RuntimeKernel --> ServiceContainer
    RuntimeKernel --> LifecycleManager
    RuntimeKernel --> FridayApp
    ServiceContainer ..> FridayApp : registers attributes as services
```

---

## 2. Single-Turn Lifecycle & I/O Pipeline

### 2.1 TurnOrchestrator Sequence Flow (Unified Dispatch Path)
This details the single control flow for all turns under the v2 refactor, bypassing fragmented routes and executing tools deterministically or through wave-based DAG graphs.

```mermaid
sequenceDiagram
    autonumber
    participant TM as TurnManager
    participant TO as TurnOrchestrator
    participant MS as MemoryService
    participant WC as WorkflowCoordinator
    participant IE as IntentEngine
    participant PE as PlannerEngine
    participant EX as Executor (Ordered or TaskGraph)
    participant EB as EventBus

    TM->>TO: handle(TurnRequest, ctx)
    TO->>MS: build_context_bundle(session_id, text)
    MS-->>TO: ContextBundle (persona, memories, graph)
    
    TO->>TO: check_pending_confirmation()
    alt confirmation pending
        TO->>EX: execute(pending_plan, text)
        EX-->>TO: response
    else normal flow
        TO->>WC: try_resume(text, session_id, ContextBundle)
        alt workflow active & handled
            WC-->>TO: WorkflowResume(handled=True, response)
        else
            TO->>IE: classify(text, ctx)
            IE-->>TO: IntentResult(tool, args, confidence, source)
            alt confidence >= 0.9 (deterministic fast-path)
                TO->>PE: plan(text, ctx, IntentResult)
                PE-->>TO: deterministic ToolPlan
            else below threshold (slow-path planning)
                TO->>PE: plan(text, ctx, intent=None)
                PE-->>TO: LLM ExecutionPlan (topological graph)
            end
            TO->>TO: ContextResolver & PlanValidator/Repair
            TO->>EX: execute(plan, text)
            EX-->>TO: response
        end
    end
    
    TO->>MS: curate_memory(text, response)
    TO->>EB: publish("turn_completed", TurnEvent)
    TO-->>TM: TurnResponse
```

### 2.2 Voice I/O Pipeline & Barge-In
The full audio loop, detailing microphone capture, openwakeword activation, Whispering, safety layers, and async TTS interruption.

```mermaid
flowchart TD
    A[sounddevice InputStream\n16kHz float32 mono] --> B[STTEngine._listen_loop thread]
    B --> C{Wake armed mode?}
    C -->|armed| D[WakeWordDetector\nopenwakeword hey_friday.onnx]
    D -->|no wake word| B
    D -->|wake word detected| E[Open gate / start session]
    C -->|gate open| F{RMS > threshold?}
    F -->|below| G[silence counter++]
    G --> H{silence > end_silence_frames?}
    H -->|yes| I[_transcribe_buffer]
    F -->|above| J[reset counter\nappend to buffer]
    J --> B
    I --> K[faster-whisper transcription]
    K --> L{empty / noise?}
    L -->|yes| B
    L -->|no| M[_process_voice_text]
    M --> N{Dictation active?}
    N -->|yes| O[dictation.append / control check]
    N -->|no| P{VoiceSafetyLayer.evaluate}
    P -->|block| B
    P -->|pass| Q{fast media command?}
    Q -->|yes| R[browser_media_service.fast_media_command]
    Q -->|no| S[FridayApp.process_input voice]
    
    %% Barge-in path
    T[TTS output playing] -.->|interruption via speech| U[STTEngine VAD/Clap trigger]
    U -.->|EventBus interrupt| V[TextToSpeech.stop]
    V -.->|kills subprocess| W[piper/aplay stop]
```

---

## 3. Planning & Routing Layer

### 3.1 Planning Systems Class Diagram
Illustrates the relationship between the `IntentEngine` (fast path), `PlannerEngine` (slow path), and downstream dependency nodes.

```mermaid
classDiagram
    class IntentEngine {
        -parsers: list~IntentParser~
        -scorer: RouteScorer
        +classify(text, ctx) IntentResult
    }
    class IntentResult {
        +tool: str | None
        +args: dict
        +confidence: float
        +source: str
        +actions: list~dict~
    }
    class PlannerEngine {
        -broker: CapabilityBroker
        -tool_model: ToolModel
        -chat_model: ChatModel
        -consent: ConsentGate
        +plan(text, ctx, intent) ExecutionPlan
    }
    class ExecutionPlan {
        +nodes: list~ToolNode~
        +edges: list~tuple~
        +chat_fallback: bool
        +spoken_ack: str | None
        +mode: str
    }
    class ToolNode {
        +node_id: str
        +tool_name: str
        +args: dict
        +depends_on: list~str~
        +timeout_ms: int
        +retries: int
    }
    class ConsentGate {
        +evaluate(text, descriptor, ctx) ConsentDecision
    }
    IntentEngine --> IntentResult
    PlannerEngine --> ExecutionPlan
    ExecutionPlan --> ToolNode
    PlannerEngine --> ConsentGate
```

---

## 4. Execution Layer & Concurrency

### 4.1 TaskGraphExecutor Topological Wave Parallelism
How sequential actions are compiled into an execution Directed Acyclic Graph (DAG) and run concurrently inside a wave-based thread pool.

```mermaid
flowchart TD
    A[ExecutionPlan\nDAG of ToolNodes] --> B[TopologicalSort]
    B --> C[topological_waves]
    
    subgraph Waves ["Parallel Execution Waves"]
        W0[Wave 0: Nodes with no dependencies]
        W1[Wave 1: Depends only on wave 0]
        Wn[Wave n: Depends only on wave n-1]
        
        W0 -->|ThreadPoolExecutor| P0[Execute Node A] & P1[Execute Node B]
        P0 --> W1
        P1 --> W1
        W1 -->|ThreadPoolExecutor| P2[Execute Node C]
        P2 --> Wn
        Wn -->|ThreadPoolExecutor| P3[Execute Node D]
    end
    
    subgraph PerNode ["Per-Node Execution Loop"]
        E0[1. Inject prior node outputs into args]
        E1[2. Query ResultCache]
        E2[3. Execute Tool Handler with timeout_ms]
        E3[4. Retry on failure up to step.retries]
        E4[5. Cache successful result]
        E0 --> E1 --> E2 --> E3 --> E4
    end
    
    POOL[ThreadPoolExecutor max_workers=4]
    POOL -.-> PerNode
    P0 & P1 & P2 & P3 --> POOL
    
    P3 --> JOIN[Merge & final responses in original order]
    JOIN --> FINAL[ResponseFinalizer.humanize]
    FINAL --> RESP[TurnResponse]
```

### 4.2 Concurrency & Inference Lock Domains
Structure of localized Locks separating conversational/chat requests from heavy background tools execution.

```mermaid
flowchart TD
    subgraph main_loop ["Asyncio Event Loop (Main Thread)"]
        TO[TurnOrchestrator]
        IE[IntentEngine\nno lock needed]
        PE[PlannerEngine]
    end

    subgraph tool_pool ["Tool LLM Execution Pool"]
        QW[Qwen 7B\ntool_inference_lock: asyncio.Lock]
    end

    subgraph chat_pool ["Chat LLM Execution Pool"]
        GM[Gemma 2B\nchat_inference_lock: asyncio.Lock]
    end

    subgraph bg_executors ["Background Pools (Async / Threaded)"]
        RA[ResearchAgent\nresearch_executor\nmax_workers=3]
        GWS[WorkspaceAgent\ngws_executor\nmax_workers=2]
        BMS[BrowserMediaService\nworker thread]
    end

    PE -->|Qwen plan request| QW
    PE -->|Gemma chat response| GM
    PE -.-> bg_executors
    
    note for QW "Separate locks prevent background research from blocking direct voice turn planning."
```

---

## 5. Memory Facade & Storage Architecture

### 5.1 Memory Facade Class Diagram
The single read/write interface wrapping low-level sqlite Context Stores and semantic/episodic Chroma vector indices.

```mermaid
classDiagram
    class MemoryService {
        +context_store: ContextStore
        +memory_broker: MemoryBroker
        +build_context_bundle(session_id, query) dict
        +record_turn(session_id, user_text, assistant_text, trace_id)
        +learn_fact(session_id, key, value, confidence)
        +forget_fact(session_id, item_id)
        +get_active_workflow(session_id, name) dict | None
        +save_workflow_state(session_id, name, state)
        +clear_workflow_state(session_id, name)
        +record_outcome(capability, context, success)
    }
    class MemoryBroker {
        +facts: MemoryFacade
        +episodic: EpisodicMemory
        +semantic: SemanticMemory
        +procedural: ProceduralMemory
        +build_context_bundle(query, session_id) dict
        +curate(session_id, user_text, assistant_text, persona_id)
    }
    class ContextStore {
        <<SQLite Storage>>
        +append_turn(session_id, role, content)
        +store_fact(key, value)
        +get_active_workflow(session_id)
    }
    class MemoryFacade {
        +learn_fact(session_id, key, value)
        +recall_semantic(query)
    }
    MemoryService --> ContextStore
    MemoryService --> MemoryBroker
    MemoryBroker --> MemoryFacade
```

### 5.2 User Profile Paradox (Session Isolation vs. Global Facts)
This details how global profile entries (onboarding name) are synchronized vs. why isolated session databases might return blank results unless bridged.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Onboarding as OnboardingExtension
    participant Greeter as GreeterExtension
    participant Store as MemoryStore / SQLite
    participant Facade as MemoryFacade
    participant Assistant as AssistantContext

    Note over User,Store: Write Path (Onboarding Completion)
    User->>Onboarding: Completes onboarding ("Santhosh")
    Onboarding->>Store: store_fact("name", "Santhosh", namespace="user_profile")
    Note over Store: Write: session_id="" (Global)<br/>Table: facts

    Note over User,Assistant: Read Path A (Greeter Startup)
    Greeter->>Store: get_facts_by_namespace("user_profile")
    Store-->>Greeter: [{"key": "name", "value": "Santhosh"}] (No session isolation)
    Greeter-->>User: "Good morning, Santhosh."

    Note over User,Assistant: Read Path B (LLM Chat Prompt Builder in Session 123)
    User->>Assistant: "What is my name?" (Session: 123)
    Assistant->>Facade: recall(session_id="123")
    Facade->>Store: recent_memory_items(session_id="123")
    Note over Store: Isolated Query: WHERE session_id="123"<br/>Table: memory_items
    Store-->>Facade: [] (No memory items yet in this session)
    Facade-->>Assistant: Empty Context Block
    Assistant-->>User: "I don't know your name yet."
```

---

## 6. Stateful Workflows & Automation Engine

### 6.1 Stateful Workflow Transition State Machine
Visualizes workflow lifecycle phases, transition gates, slot-filling, and cancellation.

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Active : Triggered by keyword / intent
    
    state Active {
        [*] --> SlotFilling
        SlotFilling --> SlotFilling : try_resume() / ask for slot value
        SlotFilling --> Validating : slot filled
        Validating --> SlotFilling : validation fails
        Validating --> Approved : all slots valid & permission granted
    }
    
    Active --> Completed : run() succeeds
    Active --> Cancelled : user cancel / timeout
    Completed --> Idle
    Cancelled --> Idle
```

### 6.2 YAML Template Compilation & Multi-Turn Resume Sequence
This demonstrates how custom automation YAML templates are parsed, validated against capabilities, and executed interactively turn-by-turn.

```mermaid
sequenceDiagram
    autonumber
    participant TO as TurnOrchestrator
    participant WC as WorkflowCoordinator
    participant TL as WorkflowTemplateLoader
    participant TC as WorkflowTemplateCompiler
    participant TW as TemplateWorkflow
    participant REG as CapabilityRegistry

    TO->>WC: try_resume(text, session_id)
    alt no active workflow in store
        WC->>TL: load_file(template_name.yaml)
        TL-->>WC: parsed yaml dict
        WC->>TC: compile(template_dict, registry)
        TC->>REG: check capabilities dependencies
        TC-->>WC: compiled TemplateWorkflow
        WC->>TW: run()
        TW->>TW: enter first unfilled ask step
        TW-->>WC: prompt question for the user
        WC->>TO: park workflow state in SessionStore
    else active workflow resumes
        WC->>TW: resume(text, session_id)
        TW->>TW: extract slot value / validate
        TW-->>WC: next step or final ToolPlan
    end
```
