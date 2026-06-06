import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Add a new tool",
  description: "Register a capability and wire its deterministic intent pattern + tests.",
};

export default function AddingTools() {
  return (
    <>
      <DocHeader
        eyebrow="Build"
        title="Add a new tool"
        intro="A new capability in FRIDAY is two things, always together: the capability itself, and the intent pattern that routes to it. Skip the pattern and the small chat model will happily fabricate success for a tool it never called."
      />

      <Callout tone="warn" title="The rule">
        Every capability registered via <code>app.register_capability(...)</code> — new or fixed —{" "}
        <strong>must</strong> also have an intent pattern in <code>core/intent_recognizer.py</code>,
        unless it is intentionally LLM-routed only (rare). <code>context_terms</code>,{" "}
        <code>aliases</code>, and <code>description</code> feed the LLM RouteScorer, not the
        deterministic recogniser.
      </Callout>

      <h2 id="step-1">1. Register the capability</h2>
      <p>
        Inside your module&apos;s <code>setup(app)</code>, register a tool spec, a handler, and
        capability metadata. The handler receives the raw text and a parsed <code>args</code> dict.
      </p>
      <CodeBlock label="python · modules/your_module/plugin.py">{`def setup(app):
    app.register_capability(
        spec={
            "name": "set_brightness",
            "description": "Set the display brightness to a percentage.",
            "parameters": {"level": {"type": "integer"}},
            "aliases": ["brightness", "screen brightness"],
            "context_terms": ["dim", "bright", "display"],
        },
        handler=handle_set_brightness,
        connectivity="local",       # local | online
        side_effect_level="write",  # read | write | critical
    )

def handle_set_brightness(text, args):
    level = int(args.get("level", 50))
    # ...do the work...
    return f"Brightness set to {level}."`}</CodeBlock>

      <h2 id="step-2">2. Add a deterministic intent pattern</h2>
      <p>
        Pick (or add) a <code>_parse_&lt;domain&gt;</code> method in{" "}
        <code>core/intent_recognizer.py</code>, add your regex(es), and return the canonical action
        dict. Always gate on tool presence so the parser is harmless when the capability isn&apos;t
        loaded.
      </p>
      <CodeBlock label="python · core/intent_recognizer.py">{`def _parse_brightness(self, clause: str):
    # Gate: do nothing if the capability isn't registered
    if "set_brightness" not in getattr(self.router, "_tools_by_name", {}):
        return None

    m = re.search(
        r"\\b(?:set|change|make|put|turn)\\b.*\\bbrightness\\b.*?(\\d{1,3}|max|min|fifty)",
        clause, re.I,
    )
    if not m:
        return None

    raw = m.group(1).lower()
    level = {"max": 100, "min": 0, "fifty": 50}.get(raw, None)
    level = level if level is not None else max(0, min(100, int(raw)))

    return {
        "tool": "set_brightness",
        "args": {"level": level},
        "text": clause,
        "domain": "system",
    }`}</CodeBlock>

      <p>Then register the parser in the <code>_parse_clause</code> chain, minding order:</p>
      <CodeBlock label="ordering matters">{`# Narrow / explicit parsers go BEFORE broad catch-alls.
# e.g. _parse_screen_lock before _parse_help so "lock screen"
# never matches a help query.
for parser in (
    self._parse_pending_selection,   # guards always first
    ...
    self._parse_brightness,          # your new parser
    ...
    self._parse_greeting,            # lowest priority
):`}</CodeBlock>

      <h2 id="robust">3. Make the pattern robust</h2>
      <p>Cover at least these axes so real speech actually matches:</p>
      <ul>
        <li><strong>Verb variants</strong> — set / change / make / put / turn.</li>
        <li><strong>Object variants</strong> — “lock screen” / “lock the screen” / “lock yourself”.</li>
        <li><strong>Word order</strong> — “brightness 80” and “set 80 brightness”.</li>
        <li><strong>Spoken cardinals</strong> — “fifty” → 50, “max” → 100, “minimum” → 0.</li>
        <li><strong>Optional argument shapes</strong> — “unlock screen” and “unlock with pin 1234” route to the same tool.</li>
        <li><strong>Filler tolerance</strong> — “Friday rescan my apps” and “rescan apps please”.</li>
      </ul>

      <Callout tone="warn" title="Negative cases matter too">
        Never match on a single common word (<code>battery</code>, <code>volume</code>,{" "}
        <code>screenshot</code>) without a verb anchor — those words appear in unrelated sentences
        (“the battery in my car died”) and cause false-positive routing. Don&apos;t poach phrasings
        that belong to another parser.
      </Callout>

      <h2 id="tests">4. Tests are mandatory</h2>
      <p>
        Add <code>tests/test_&lt;domain&gt;_intent.py</code> following the{" "}
        <code>_make_recognizer(tools=[...])</code> pattern. Parametrize the positive phrasings and
        include at least one negative phrasing that must <strong>not</strong> match.
      </p>
      <CodeBlock label="python · tests/test_brightness_intent.py">{`import pytest
from tests.helpers import _make_recognizer

@pytest.mark.parametrize("phrase,level", [
    ("set brightness to 60", 60),
    ("make the screen brightness fifty", 50),
    ("turn brightness to max", 100),
    ("brightness 80", 80),
])
def test_brightness_matches(phrase, level):
    rec = _make_recognizer(tools=["set_brightness"])
    action = rec.plan(phrase).steps[0]
    assert action.tool == "set_brightness"
    assert action.args["level"] == level

def test_brightness_negative():
    rec = _make_recognizer(tools=["set_brightness"])
    assert rec.plan("the future is bright for us").steps == []`}</CodeBlock>

      <h2 id="docs">5. Update the testing guide</h2>
      <p>
        Add or update the matching <code>T-N.M</code> entry in <code>docs/testing_guide.md</code>.
        Its <strong>You say</strong> field lists the natural phrasings a user can speak — which
        doubles as the live spec of what your parser must accept.
      </p>

      <Callout tone="tip" title="That's the whole loop">
        Capability + intent pattern + robust phrasings + tests + testing-guide entry. Do all five
        and your tool is a first-class citizen of the deterministic router — reliable on a local
        model, with no LLM in the hot path. Revisit{" "}
        <Link href="/docs/how-it-works">How routing works</Link> for why each piece matters.
      </Callout>

      <PrevNext current="/docs/adding-tools" />
    </>
  );
}
