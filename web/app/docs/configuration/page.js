import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Configuration",
  description: "Tune FRIDAY through config.yaml and .env — routing, models, voice, and consent.",
};

export default function Configuration() {
  return (
    <>
      <DocHeader
        eyebrow="Build"
        title="Configuration"
        intro="Runtime behaviour is driven by config.yaml; secrets and machine overrides live in .env (copied from .env.example at setup). Here are the keys you'll touch most."
      />

      <h2 id="highlights">Highlights</h2>
      <CodeBlock label="config.yaml">{`conversation:
  listening_mode: manual          # or wake-word driven
  online_permission_mode: ask_first

models:
  chat:  { path: models/Qwen3.5-0.8B-Q4_K_M.gguf }
  tool:  { path: models/Qwen3.5-4B-Q4_K_M.gguf }

routing:
  execution_engine: parallel      # ordered | parallel | graph (LangGraph)
  use_replanning: true`}</CodeBlock>

      <h2 id="routing">Routing thresholds</h2>
      <p>
        These tune the confidence bands described in{" "}
        <Link href="/docs/how-it-works">How routing works</Link>. Lower them to dispatch more
        eagerly; raise them to ask more often.
      </p>
      <CodeBlock label="config.yaml · routing">{`routing:
  dispatch_threshold: 0.62   # cosine ≥ this → auto-dispatch
  confirm_low: 0.50          # below dispatch but here → "did you mean…?"
  tie_epsilon: 0.05          # candidates this close → disambiguate
  lexical_threshold: 88      # rapidfuzz score floor
  lexical_margin: 6          # …and must beat runner-up by this
  promote_after: 3           # confirmed this many times → deterministic
  confirm_destructive: true  # guard destructive actions
  disambiguate: true         # ask which one when ambiguous`}</CodeBlock>

      <h2 id="voice">Voice</h2>
      <CodeBlock label="config.yaml · voice">{`voice:
  stt_model: base.en
  stt_compute_type: int8
  stt_cpu_threads: 8
conversation:
  wake_session_timeout_s: 12`}</CodeBlock>

      <h2 id="consent">Online consent</h2>
      <p>
        Local-first means the network is opt-in. <code>online_permission_mode</code> governs how
        FRIDAY asks before any capability reaches the internet.
      </p>
      <ul>
        <li><code>ask_first</code> — prompt for consent before each online action (default).</li>
        <li><code>always</code> — allow online capabilities without prompting.</li>
        <li><code>never</code> — block online capabilities entirely.</li>
      </ul>

      <h2 id="env">Useful env vars</h2>
      <CodeBlock label=".env">{`FRIDAY_PORCUPINE_KEY=...          # wake word access key (required both OSes)
FRIDAY_CHAT_MODEL_URL=...         # override chat model download
FRIDAY_TOOL_MODEL_URL=...         # override tool/planner model download
FRIDAY_DISABLE_EMBED_ROUTER=1     # skip the embedding layer (faster cold start)`}</CodeBlock>

      <Callout tone="note" title="Full reference">
        Every key is documented in <code>docs/config_reference.md</code> in the repository. Edits to{" "}
        <code>config.yaml</code> take effect on next launch.
      </Callout>

      <PrevNext current="/docs/configuration" />
    </>
  );
}
