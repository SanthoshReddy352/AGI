// The deterministic routing pipeline — FRIDAY's core differentiator.
// Cheapest, most-certain layers first; the LLM is the last resort.
const layers = [
  {
    tag: "L1",
    name: "Intent Recognizer",
    detail: "Deterministic regex parsers — first match wins",
    band: "confidence 1.0",
    accent: "from-glow-cyan/80 to-glow-cyan/20",
    dot: "#37e6ff",
  },
  {
    tag: "L2",
    name: "Route Scorer",
    detail: "Alias / pattern / context-term score (min 80)",
    band: "score ≥ 80",
    accent: "from-glow-blue/80 to-glow-blue/20",
    dot: "#4f7bff",
  },
  {
    tag: "L2b",
    name: "Lexical Router",
    detail: "rapidfuzz token-set ratio — catches STT slips & typos",
    band: "fuzzy ≥ 88",
    accent: "from-glow-blue/70 to-glow-violet/20",
    dot: "#6a6bff",
  },
  {
    tag: "L3",
    name: "Embedding Router",
    detail: "Cosine similarity over capability embeddings",
    band: "cosine band + confirm",
    accent: "from-glow-violet/80 to-glow-violet/20",
    dot: "#8b5cff",
  },
  {
    tag: "L4",
    name: "Local Planner (4B)",
    detail: "On-device LLM synthesises a tool plan",
    band: "generative",
    accent: "from-glow-amber/70 to-glow-amber/15",
    dot: "#ffb267",
  },
  {
    tag: "L5",
    name: "Chat Fallback",
    detail: "Conversational reply when nothing routes",
    band: "chat",
    accent: "from-white/30 to-white/5",
    dot: "#9aa6b8",
  },
];

export default function RouterPipeline() {
  return (
    <div className="panel relative overflow-hidden p-6 sm:p-8">
      <div className="grid-backdrop pointer-events-none absolute inset-0 opacity-60" />
      <div className="relative">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-line bg-ink-700/60 px-3 py-1 text-xs font-medium text-glow-cyan">
            <span className="h-1.5 w-1.5 rounded-full bg-glow-cyan" />
            voice / text in
          </div>
          <span className="font-mono text-xs text-white/40">cheapest layer that resolves wins →</span>
        </div>

        <div className="space-y-2.5">
          {layers.map((l, i) => (
            <div
              key={l.tag}
              className="group flex items-center gap-4 rounded-xl border border-line bg-ink-700/40 px-4 py-3.5 transition-colors hover:border-white/15"
            >
              <div className="flex w-12 shrink-0 items-center justify-center">
                <span
                  className="rounded-md px-2 py-1 font-mono text-[11px] font-semibold text-ink-900"
                  style={{ background: l.dot }}
                >
                  {l.tag}
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-sm font-semibold text-white">{l.name}</span>
                  <span className="font-mono text-[11px] text-white/40">{l.band}</span>
                </div>
                <p className="truncate text-xs text-white/55">{l.detail}</p>
              </div>
              <div className={`hidden h-1.5 w-20 rounded-full bg-gradient-to-r sm:block ${l.accent}`} />
            </div>
          ))}
        </div>

        <div className="mt-6 flex items-center gap-3 rounded-xl border border-glow-cyan/20 bg-glow-cyan/5 px-4 py-3">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className="shrink-0">
            <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z" fill="#37e6ff" />
          </svg>
          <p className="text-xs text-white/70">
            A regex hit at <span className="font-mono text-glow-cyan">L1</span> short-circuits the entire stack —
            the common phrasings never wake the model, and the model never gets the chance to invent a result.
          </p>
        </div>
      </div>
    </div>
  );
}
