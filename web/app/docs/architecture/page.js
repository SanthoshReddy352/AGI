import Link from "next/link";
import { DocHeader, Callout, PrevNext, FactGrid } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Architecture",
  description: "FRIDAY's turn pipeline, routing layers, memory tiers, and domain stores.",
};

export default function Architecture() {
  return (
    <>
      <DocHeader
        eyebrow="Concepts"
        title="Architecture"
        intro="FRIDAY runs a modular plugin architecture with a capability registry, a v2 turn-orchestration pipeline, and a three-tier memory system. Every turn — voice or text — flows through one pipeline."
      />

      <h2 id="turn-lifecycle">The turn lifecycle</h2>
      <p>
        A turn enters as voice or text and is handled by the <code>TurnOrchestrator</code>, which
        owns the lifecycle. It builds a context bundle (persona + session summary + memory recall),
        runs the router, executes the chosen capability, styles the response through the active
        persona, speaks it, and curates the turn into memory.
      </p>
      <CodeBlock label="turn pipeline">{`voice / text in
      │
   STTEngine ──► TurnOrchestrator (v2, core/planning/)
                     │
            _build_context_bundle()   (persona + session summary + recall)
                     │
              PlannerEngine.plan()  ◄── the 6-layer router
                     │
                 ToolPlan  (mode: tool | planner | chat | reply)
                     │
        OrderedToolExecutor  ⇄  TaskGraphExecutor (parallel, opt-in)
                     │
            CapabilityExecutor ──► capability handler (28 plugin modules)
                     │
            ResponseFinalizer ──► persona styling ──► TTS / GUI / channel
                     │
       MemoryCuratorAgent.curate()  (writes the turn to stores + Chroma)`}</CodeBlock>

      <Callout tone="note" title="Who owns what">
        <code>TurnOrchestrator</code> owns the lifecycle, <code>PlannerEngine</code> owns route
        selection, and <code>CapabilityExecutor</code> enforces the lock gate and online-consent
        gate before any handler runs.
      </Callout>

      <h2 id="routing">The routing pipeline</h2>
      <p>
        <code>PlannerEngine.plan()</code> walks an ordered chain and returns at the first layer that
        produces a plan. Each layer is more expensive than the last, so common phrasings never pay
        for the LLM. This is the heart of what makes FRIDAY work on small local models — covered in
        depth in <Link href="/docs/how-it-works">How routing works</Link>.
      </p>
      <CodeBlock label="6 layers · cheapest first">{`L1  IntentRecognizer   deterministic regex parsers (first-match wins)   conf 1.0
L2  RouteScorer        alias / pattern / context-term score (min 80)
L2a Learned dispatch   a phrasing confirmed promote_after times
L2b LexicalRouter      rapidfuzz token_set_ratio (catches STT / typos)
L3  EmbeddingRouter    cosine over capability embeddings (+ confirm band)
L4  QwenPlanner        local 4B planner (LLM tool / plan synthesis)
L5  llm_chat           conversational fallback`}</CodeBlock>

      <h2 id="workflows">Workflow state machine</h2>
      <p>
        Anything that can&apos;t resolve in one turn runs as a <strong>workflow</strong> through{" "}
        <code>WorkflowOrchestrator</code>. A workflow persists its state so the next turn resumes
        mid-flow. Three reusable, composable mechanisms — all pure session-state + regex, gated by
        config — cover the common multi-turn shapes:
      </p>
      <ul>
        <li><strong>ConfirmationGuard</strong> — “shall I go ahead?” before a destructive action (lock screen, delete goal, forget memory…).</li>
        <li><strong>DisambiguationGuard</strong> — “which one did you mean?” when a request resolves to more than one candidate (file search, app launch, document query).</li>
        <li><strong>Slot-fill templates</strong> — declarative YAML driven by <code>SlotFiller</code> with cheapest-first precedence: caller-known → extractor → LLM → default.</li>
      </ul>

      <h2 id="memory">Three-tier memory</h2>
      <p>FRIDAY keeps memory across turns and sessions, all on local disk, written by a single curator:</p>
      <FactGrid
        items={[
          ["episodic", "Every turn → SQLite turns table → session summaries"],
          ["semantic", "Facts + memory items → Chroma vector index (semantic recall)"],
          ["procedural", "Capability success rates (Thompson sampling) → best-tool hints"],
          ["profile", "Slug-keyed user facts (name, preferences) injected into prompts"],
        ]}
      />

      <h2 id="stores">Persistence — domain stores</h2>
      <p>
        Storage is decomposed into six domain stores under <code>core/stores/</code>, each owning
        its own tables and migration SQL. A transitional <code>ContextStore</code> facade delegates
        to them. Write-ownership is strict (each store writes only its own tables); reads may cross
        stores via raw SQL on the shared <code>data/friday.db</code> (WAL mode).
      </p>
      <FactGrid
        items={[
          ["session_store", "sessions, turns, personas, conversation_sessions"],
          ["memory_store", "facts, memory_items (+ the Chroma index)"],
          ["knowledge_graph_store", "entities, entity_facts, entity_relationships"],
          ["audit_store", "audit_events, online_permission_events, agent_messages"],
          ["goal_store", "goals, goal_progress"],
          ["workflow_store", "workflows"],
        ]}
      />

      <h2 id="cross-platform">Cross-platform model</h2>
      <p>One codebase, two first-class platforms. Platform-specific behaviour is guarded throughout:</p>
      <FactGrid
        items={[
          ["process spawn", "start_new_session (Linux) · DETACHED_PROCESS (Windows)"],
          ["app launch", "shutil.which + Popen · os.startfile then Popen"],
          ["wake autostart", "systemd --user unit · .bat in Startup folder"],
          ["screenshot", "mutter→grim→scrot chain · pyautogui"],
        ]}
      />

      <Callout tone="tip" title="Go deeper">
        The repository ships a full architectural reference (<code>docs/ARCHITECTURE.md</code>) and a
        pre-built knowledge graph of the codebase with god-nodes and community detection.
      </Callout>

      <PrevNext current="/docs/architecture" />
    </>
  );
}
