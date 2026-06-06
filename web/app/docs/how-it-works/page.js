import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "How routing works",
  description: "The deterministic router — regex intent matching, similarity, and confidence bands — that makes a small local model reliable.",
};

export default function HowItWorks() {
  return (
    <>
      <DocHeader
        eyebrow="Concepts"
        title="How routing works"
        intro="This is the idea at the centre of FRIDAY. Cloud agents route tools well because the model is huge. Strip the cloud away and a small on-device model can't be trusted to pick the right tool — so FRIDAY puts a deterministic router in front of it."
      />

      <h2 id="problem">Why local-first agents are hard</h2>
      <p>
        An agent harness is the loop that reads your request, decides which tool to call, and fills
        that tool&apos;s arguments. Modern harnesses lean entirely on a frontier model to do this.
        Run the same harness on a 0.8B model that fits on a laptop and it breaks down: it misreads
        intent, picks the wrong tool, or — most dangerously —{" "}
        <strong>fabricates a successful-sounding result for an action it never performed.</strong>
      </p>
      <Callout tone="warn" title="The failure mode in one line">
        Ask a small chat model to set your brightness with no tool wired, and it will reply{" "}
        <code>“Brightness set to 60.”</code> Nothing changed. That confident lie is what FRIDAY is
        built to prevent.
      </Callout>

      <h2 id="bridge">The bridge: a deterministic router</h2>
      <p>
        FRIDAY adds a routing layer that doesn&apos;t depend on the model&apos;s intelligence for the
        common cases. It combines three deterministic techniques, each defending a{" "}
        <strong>confidence band</strong> so a near-miss asks rather than guesses:
      </p>
      <ul>
        <li><strong>Regex intent matching</strong> — hand-written parsers turn known phrasings straight into a tool call.</li>
        <li><strong>Similarity</strong> — fuzzy (rapidfuzz) and embedding (cosine) scoring catch paraphrases and speech-to-text slips.</li>
        <li><strong>Confidence rules</strong> — explicit thresholds decide between dispatch, “did you mean…?”, and falling through.</li>
      </ul>

      <h2 id="layers">The six layers, cheapest first</h2>
      <p>
        <code>PlannerEngine.plan()</code> walks the chain and returns at the first layer that
        produces a confident plan. A regex hit at L1 (confidence ≥ 0.90) short-circuits everything
        else — the model is never consulted, so it never gets to invent a result.
      </p>
      <CodeBlock label="routing chain">{`pre-checks   1. pending online confirmation   2. active workflow resume
──────────────────────────────────────────────────────────────────────
L1   IntentRecognizer   deterministic regex parsers (first-match wins)   conf 1.0 / 0.9
L2   RouteScorer        alias / pattern / context-term score (min 80)    "score"
L2a  Learned dispatch   a phrasing confirmed promote_after times          "learned"
L2b  LexicalRouter      rapidfuzz token_set_ratio (catches STT / typos)   fuzzy
L3   EmbeddingRouter    cosine over capability embeddings                 cosine band
L4   QwenPlanner        local 4B planner (LLM tool / plan synthesis)      generative
L5   llm_chat           conversational fallback                           chat`}</CodeBlock>

      <h2 id="bands">Confidence bands</h2>
      <p>
        The fuzzy layers never dispatch on a bare best-match; each defends a band. These are the
        defaults (all tunable under <code>routing.*</code> — see <Link href="/docs/configuration">Configuration</Link>):
      </p>
      <CodeBlock label="thresholds">{`Intent fast-path   HIGH_THRESHOLD     0.90   at/above → bypass planner, build plan from regex
Intent fast-path   MEDIUM_THRESHOLD   0.50   below HIGH but here → keep candidate, still consult planner
Embedding          dispatch_threshold 0.62   cosine ≥ this → auto-dispatch matched capability
Embedding          confirm_low        0.50   in [confirm_low, dispatch) → ask "did you mean…?"
Embedding          tie_epsilon        0.05   two candidates this close → disambiguate
Lexical            lexical_threshold  88     rapidfuzz score must clear this to fire
Lexical            lexical_margin     6      …and beat the runner-up by this margin (never poaches)
Learned            promote_after      3      a phrasing confirmed this many times → deterministic`}</CodeBlock>

      <Callout tone="note" title="The confirm band is the safety property">
        Rather than letting the small model fabricate a plausible success, FRIDAY asks a yes/no
        question when it&apos;s only moderately sure — and that answer becomes the learning signal
        that feeds the <code>promote_after</code> counter. FRIDAY gets more confident about your
        phrasing the more you use it.
      </Callout>

      <h2 id="tradeoff">The tradeoff — read this</h2>
      <p>
        Determinism is a deal, not magic. A regex router only fires for phrasings it was taught.
        Give FRIDAY a complex or novel command it has never seen and the deterministic layers
        won&apos;t catch it — it falls back to the local 4B planner, which is far weaker than a
        frontier model and may not get it right.
      </p>
      <p>
        This is the honest cost of local-first:{" "}
        <strong>for every tool we build, we also teach FRIDAY the words that drive it.</strong> The
        payoff is reliability, privacy, and zero cloud dependence for everything it{" "}
        <em>does</em> know — plus a system that learns new phrasings as you use it. When you add a
        capability, you add its intent pattern too; that&apos;s the subject of{" "}
        <Link href="/docs/adding-tools">Add a new tool</Link>.
      </p>

      <Callout tone="tip" title="Why this is the right call for on-device AI">
        A frontier model in the cloud hides its routing inside a giant network you can&apos;t
        inspect. FRIDAY&apos;s router is explicit, debuggable, and fast — and it degrades to a real
        model only when it has to. You trade a bit of flexibility for a lot of trust.
      </Callout>

      <PrevNext current="/docs/how-it-works" />
    </>
  );
}
