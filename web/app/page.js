import Link from "next/link";
import Nav from "@/components/Nav";
import Footer from "@/components/Footer";
import VoiceOrb from "@/components/VoiceOrb";
import RouterPipeline from "@/components/RouterPipeline";
import TelegramShowcase from "@/components/TelegramShowcase";
import CodeBlock from "@/components/CodeBlock";

const GITHUB = "https://github.com/SanthoshReddy352/Friday_Linux";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <Marquee />
        <GapStory />
        <RouterSection />
        <TradeoffNote />
        <LocalFirst />
        <Capabilities />
        <RemoteControl />
        <CTA />
      </main>
      <Footer />
    </>
  );
}

/* ------------------------------------------------------------------ Hero */

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="grid-backdrop pointer-events-none absolute inset-0" />
      <div className="mx-auto grid max-w-container grid-cols-1 items-center gap-12 px-5 pb-20 pt-16 sm:px-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] lg:pb-28 lg:pt-24">
        <div className="min-w-0 animate-fade-up">
          <div className="inline-flex items-center gap-2 rounded-full border border-line bg-ink-700/50 px-3.5 py-1.5 text-xs text-white/70">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-glow-cyan opacity-70" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-glow-cyan" />
            </span>
            Local-first · voice-native · open source
          </div>

          <h1 className="mt-6 text-balance text-[2.5rem] font-semibold leading-[1.05] tracking-tight xs:text-5xl sm:text-6xl">
            <span className="text-gradient">The assistant that</span>
            <br className="hidden sm:block" />{" "}
            <span className="text-gradient-cyan">stays on your machine.</span>
          </h1>

          <p className="mt-6 max-w-xl text-base leading-relaxed text-white/65 sm:text-lg">
            FRIDAY listens, reasons, and acts entirely on-device. Speech-to-text, the
            conversational model, planning, vision, and memory all run on your hardware —
            it reaches the internet only when you ask. Say <span className="text-white">"Hey Friday"</span> and
            it gets to work, narrating progress out loud.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/docs/getting-started"
              className="group inline-flex items-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-semibold text-ink-900 transition-transform hover:scale-[1.03]"
            >
              Get started
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="transition-transform group-hover:translate-x-0.5">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
            <a
              href={GITHUB}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-xl border border-line bg-ink-700/40 px-5 py-3 text-sm font-medium text-white/80 transition-colors hover:border-white/25 hover:text-white"
            >
              <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.58 2 12.25c0 4.53 2.87 8.37 6.84 9.73.5.1.68-.22.68-.48l-.01-1.7c-2.78.62-3.37-1.37-3.37-1.37-.46-1.18-1.11-1.49-1.11-1.49-.91-.64.07-.62.07-.62 1 .07 1.53 1.06 1.53 1.06.9 1.57 2.36 1.12 2.94.85.09-.66.35-1.12.63-1.38-2.22-.26-4.55-1.14-4.55-5.05 0-1.12.39-2.03 1.03-2.74-.1-.26-.45-1.3.1-2.71 0 0 .84-.27 2.75 1.05A9.36 9.36 0 0 1 12 6.84c.85 0 1.71.12 2.51.34 1.91-1.32 2.75-1.05 2.75-1.05.55 1.41.2 2.45.1 2.71.64.71 1.03 1.62 1.03 2.74 0 3.92-2.34 4.78-4.57 5.03.36.32.68.94.68 1.9l-.01 2.81c0 .27.18.59.69.48A10.02 10.02 0 0 0 22 12.25C22 6.58 17.52 2 12 2Z" />
              </svg>
              Star on GitHub
            </a>
          </div>

          <div className="mt-8 max-w-md">
            <CodeBlock label="install · linux">{`git clone ${GITHUB}.git
cd Friday_Linux && ./setup.sh
python main.py`}</CodeBlock>
          </div>
        </div>

        <div className="relative flex min-w-0 items-center justify-center lg:justify-end">
          <div className="absolute -inset-10 rounded-full bg-glow-blue/10 blur-3xl" />
          <VoiceOrb className="relative animate-float" />
        </div>
      </div>

      {/* spoken example chips */}
      <div className="mx-auto -mt-4 max-w-container px-5 pb-8 sm:px-8">
        <div className="flex flex-wrap gap-2.5">
          {[
            "Hey Friday — set brightness to 60",
            "What's on my calendar today?",
            "Find the file design final report",
            "/deep RISC-V vs ARM in 2026",
            "!sudo systemctl restart nginx",
            "Summarize this PDF",
            "Take a screenshot and explain it",
          ].map((p) => (
            <span
              key={p}
              className="rounded-full border border-line bg-ink-700/40 px-3.5 py-1.5 font-mono text-xs text-white/55"
            >
              {p}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- Marquee */

function Marquee() {
  const stats = [
    ["100%", "on-device reasoning"],
    ["28", "capability modules"],
    ["6-layer", "routing pipeline"],
    ["13", "slash commands"],
    ["Telegram", "+ Discord remote"],
    ["0", "accounts · 0 telemetry"],
  ];
  return (
    <section className="border-y border-line bg-ink-800/40">
      <div className="mx-auto grid max-w-container grid-cols-2 gap-px overflow-hidden sm:grid-cols-3 lg:grid-cols-6">
        {stats.map(([n, l]) => (
          <div key={l} className="bg-ink-900/30 px-5 py-7 text-center">
            <div className="text-2xl font-semibold text-gradient-cyan">{n}</div>
            <div className="mt-1 text-xs text-white/45">{l}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- Gap story */

function GapStory() {
  return (
    <section className="relative py-16 sm:py-24">
      <div className="mx-auto max-w-container px-5 sm:px-8">
        <SectionLabel>The problem with local-first agents</SectionLabel>
        <h2 className="mt-4 max-w-3xl text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl lg:text-[2.75rem]">
          Cloud agents are smart because the model is smart.
          <span className="text-white/45"> Take the cloud away and the harness falls apart.</span>
        </h2>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-white/60">
          The current wave of agent harnesses — the loops that read your request, pick a tool,
          and fill its arguments — lean entirely on a frontier model to understand intent and
          route correctly. Run that same harness on a model small enough to live on your laptop
          and it breaks: small models miss the intent, call the wrong tool, or worse —
        </p>

        <div className="mt-10 grid grid-cols-1 gap-5 lg:grid-cols-2">
          <div className="panel panel-hover p-7">
            <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-red-500/10 text-red-300">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 9v4m0 4h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0Z" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-white">Small models hallucinate success</h3>
            <p className="mt-2 text-sm leading-relaxed text-white/55">
              Ask a 0.8B chat model to set your brightness and — with no tool actually wired —
              it will cheerfully reply <span className="font-mono text-red-200/80">"Brightness set to 60."</span>
              {" "}Nothing happened. The model fabricated a plausible-sounding result because that's
              what language models do when they can't really act.
            </p>
          </div>

          <div className="panel panel-hover p-7">
            <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-glow-cyan/10 text-glow-cyan">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>
            <h3 className="text-lg font-semibold text-white">FRIDAY bridges the gap in the harness</h3>
            <p className="mt-2 text-sm leading-relaxed text-white/55">
              Instead of trusting a small model to route, FRIDAY adds a{" "}
              <span className="text-white">deterministic router</span> in front of it: regex intent
              matching, fuzzy + embedding similarity, and explicit confidence bands. Known phrasings
              hit a real tool with certainty. The model never gets to invent a result for an action
              it didn't perform.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- Router section */

function RouterSection() {
  return (
    <section id="router" className="relative scroll-mt-20 py-16 sm:py-24">
      <div className="mx-auto max-w-container px-5 sm:px-8">
        <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          <div className="lg:sticky lg:top-28">
            <SectionLabel>How FRIDAY routes</SectionLabel>
            <h2 className="mt-4 text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
              A deterministic router, <span className="text-gradient-cyan">cheapest layer first.</span>
            </h2>
            <p className="mt-6 text-lg leading-relaxed text-white/60">
              Every request walks an ordered chain and returns at the first layer that produces a
              confident plan. The common things you say resolve instantly with regex — no model
              call, no latency, no chance to hallucinate. Only the genuinely novel falls through
              to the on-device planner.
            </p>

            <ul className="mt-8 space-y-4">
              {[
                ["Regex intent matching", "First-match parsers turn known phrasings straight into a tool call at confidence 1.0."],
                ["Similarity, not guesswork", "Fuzzy (rapidfuzz) and embedding (cosine) layers catch STT slips and paraphrases."],
                ["Confidence bands", "Near-misses ask “did you mean…?” instead of silently picking the wrong tool."],
                ["Learns your phrasing", "A wording you confirm a few times is promoted to deterministic dispatch."],
              ].map(([t, d]) => (
                <li key={t} className="flex gap-3.5">
                  <span className="mt-1.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-glow-cyan/15">
                    <span className="h-1.5 w-1.5 rounded-full bg-glow-cyan" />
                  </span>
                  <div>
                    <div className="text-sm font-semibold text-white">{t}</div>
                    <div className="text-sm text-white/55">{d}</div>
                  </div>
                </li>
              ))}
            </ul>

            <Link href="/docs/how-it-works" className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-glow-cyan hover:underline">
              Read how routing works
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
          </div>

          <RouterPipeline />
        </div>
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- Tradeoff note */

function TradeoffNote() {
  return (
    <section className="py-6">
      <div className="mx-auto max-w-container px-5 sm:px-8">
        <div className="panel relative overflow-hidden p-8 sm:p-10">
          <div className="absolute right-0 top-0 h-40 w-40 rounded-full bg-glow-amber/10 blur-3xl" />
          <div className="relative flex flex-col gap-6 sm:flex-row sm:items-start">
            <div className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-glow-amber/12 text-glow-amber">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 3a9 9 0 1 0 9 9M12 7v5l3 2" />
              </svg>
            </div>
            <div>
              <h3 className="text-xl font-semibold text-white">The honest tradeoff</h3>
              <p className="mt-3 max-w-3xl leading-relaxed text-white/60">
                Determinism is a deal, not magic. A regex router only fires for phrasings it was
                taught — give FRIDAY a complex command it has never seen and the deterministic layers
                won't catch it; it falls back to the local planner, which is far weaker than a
                frontier model. This is the price of local-first:{" "}
                <span className="text-white/85">every tool we build, we also teach FRIDAY the words that drive it.</span>{" "}
                The upside is reliability, privacy, and zero cloud dependence for everything it
                <em> does</em> know — and it learns new phrasings as you use it.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------- Local first */

function LocalFirst() {
  const points = [
    {
      title: "Nothing leaves by default",
      body: "STT, chat, planner, vision, and embeddings are all local GGUF / ONNX models. No account, no cloud inference, no telemetry.",
      icon: (
        <path d="M12 2 4 5v6c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V5l-8-3Z" />
      ),
    },
    {
      title: "Online is opt-in & consented",
      body: "Web search and browser automation exist — but a consent gate asks before any capability reaches the network, and it's logged.",
      icon: <path d="M12 2v20M2 12h20M5 5l14 14M19 5 5 19" />,
    },
    {
      title: "Your memory, on your disk",
      body: "A three-tier memory (episodic, semantic, procedural) lives in local SQLite + a Chroma vector index. It's yours to inspect, export, or wipe.",
      icon: <path d="M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7" />,
    },
    {
      title: "Runs on modest hardware",
      body: "8 GB RAM gets you going; CUDA is auto-used when present. Quantized models keep the whole stack on a laptop.",
      icon: <path d="M4 4h16v12H4zM2 20h20M9 16v4M15 16v4" />,
    },
  ];
  return (
    <section id="local-first" className="relative scroll-mt-20 overflow-hidden border-t border-line py-16 sm:py-24">
      <div className="grid-backdrop pointer-events-none absolute inset-0 opacity-50" />
      <div className="relative mx-auto max-w-container px-5 sm:px-8">
        <div className="max-w-2xl">
          <SectionLabel>Local-first, in full</SectionLabel>
          <h2 className="mt-4 text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Privacy isn't a setting. <span className="text-gradient-cyan">It's the architecture.</span>
          </h2>
          <p className="mt-6 text-lg leading-relaxed text-white/60">
            Most assistants ship your voice and your context to someone else's servers. FRIDAY
            inverts that: the machine in front of you is the whole system. The network is an
            opt-in peripheral, not the brain.
          </p>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {points.map((p) => (
            <div key={p.title} className="panel panel-hover p-6">
              <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-glow-cyan/10 text-glow-cyan">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                  {p.icon}
                </svg>
              </div>
              <h3 className="text-base font-semibold text-white">{p.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{p.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------ Capabilities */

const CAPS = [
  { t: "Voice I/O", d: "“Hey Friday” wake word, faster-whisper STT, Piper neural TTS with barge-in. Falls back to text chat.", k: "voice" },
  { t: "Natural conversation", d: "Local chat model with session-aware turns, custom personas, and three-tier memory.", k: "chat" },
  { t: "System control", d: "Brightness, volume, screen lock/unlock, screenshots, app launch, window queries, clipboard.", k: "system" },
  { t: "Document intelligence", d: "Index and ask questions over your PDFs, Office docs & Markdown via local RAG.", k: "docs" },
  { t: "Vision (VLM)", d: "Screenshot explainer, OCR, screen summarizer, UI-element finder, code debugger — local SmolVLM2.", k: "vision" },
  { t: "Online skills (opt-in)", d: "Browser automation, web & quick-answer search, news, world monitoring, weather.", k: "web" },
  { t: "Productivity", d: "Reminders, calendar events, notes, tasks, goals, focus sessions, dictation.", k: "tasks" },
  { t: "Extensible", d: "Add a capability plus an intent pattern; optional external MCP across 28 modules.", k: "ext" },
  { t: "Privacy & safety", d: "Ask-before-online consent, scoped security tooling (lab mode), a local audit log.", k: "safe" },
];

function Capabilities() {
  return (
    <section id="capabilities" className="scroll-mt-20 py-16 sm:py-24">
      <div className="mx-auto max-w-container px-5 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <SectionLabel>What it can do</SectionLabel>
            <h2 className="mt-4 text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
              One assistant. <span className="text-gradient-cyan">Twenty-eight capabilities.</span>
            </h2>
          </div>
          <Link href="/docs/capabilities" className="inline-flex items-center gap-2 text-sm font-medium text-glow-cyan hover:underline">
            Full capability reference
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </Link>
        </div>

        <div className="mt-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {CAPS.map((c) => (
            <div key={c.t} className="panel panel-hover group p-6">
              <div className="flex items-center justify-between">
                <div className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-ink-700/50 text-glow-cyan">
                  <CapIcon k={c.k} />
                </div>
                <span className="font-mono text-[10px] uppercase tracking-wider text-white/25">{c.k}</span>
              </div>
              <h3 className="mt-4 text-base font-semibold text-white">{c.t}</h3>
              <p className="mt-2 text-sm leading-relaxed text-white/55">{c.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CapIcon({ k }) {
  const paths = {
    voice: <path d="M12 3v10m-4-7v4m8-4v4M5 9v2m14-2v2M9 17h6M12 17v4" />,
    chat: <path d="M21 12a8 8 0 0 1-11.5 7.2L3 21l1.8-6.5A8 8 0 1 1 21 12Z" />,
    system: <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-3a8 8 0 0 1-.1 1l2 1.5-2 3.5-2.4-1a8 8 0 0 1-1.7 1l-.4 2.6h-4l-.4-2.6a8 8 0 0 1-1.7-1l-2.4 1-2-3.5L4.1 13a8 8 0 0 1 0-2L2 9.5l2-3.5 2.4 1a8 8 0 0 1 1.7-1L8.5 3.4h4l.4 2.6a8 8 0 0 1 1.7 1l2.4-1 2 3.5-2 1.5c.1.3.1.6.1 1Z" />,
    docs: <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Zm0 0v6h6M8 13h8M8 17h8" />,
    vision: <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z" />,
    web: <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 0c3 3 3 17 0 20M2 12h20" />,
    tasks: <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />,
    ext: <path d="M14 7h3a2 2 0 0 1 2 2v3m-5 8H7a2 2 0 0 1-2-2v-3m0-6V6a2 2 0 0 1 2-2h3M9 9h.01M15 15h.01" />,
    safe: <path d="M12 2 4 5v6c0 5 3.4 8.5 8 10 4.6-1.5 8-5 8-10V5l-8-3Zm-1 9 1.5 1.5L16 9" />,
  };
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {paths[k]}
    </svg>
  );
}

/* -------------------------------------------------------- Remote control */

const PREFIXES = [
  {
    sym: "·",
    color: "#37e6ff",
    name: "Plain text",
    ex: "set brightness to 60",
    d: "Runs through the deterministic router — voice or typed, same path.",
  },
  {
    sym: "/",
    color: "#8b5cff",
    name: "Slash command",
    ex: "/deep RISC-V vs ARM",
    d: "Pre-routing dispatch straight to a capability — no LLM in the loop.",
  },
  {
    sym: "!",
    color: "#ffb267",
    name: "Shell command",
    ex: "!sudo systemctl restart nginx",
    d: "A PTY-backed interactive shell. venv-aware, screen-lock gated.",
  },
  {
    sym: ">",
    color: "#5fd4ff",
    name: "Shell follow-up",
    ex: "> your-password",
    d: "Pipes stdin to the running command — sudo prompts, y/n, read.",
  },
];

const REMOTE = [
  ["Drive the full assistant", "Message the bot and the entire turn pipeline runs on your machine, replying in the chat."],
  ["Shell from your phone", "! commands and > follow-ups work remotely — restart a service, run a script, answer a sudo prompt."],
  ["13 slash commands", "/new /web /quick /fast /deep /research /fetch /crawl /screenshot /voice /lock /unlock /help — with Telegram autocomplete."],
  ["Upload a document", "Drop a PDF / DOCX / XLSX / MD into the chat; it loads into RAG and you ask questions about it."],
  ["Send a voice note", "Transcribed by the same local Whisper STT, then processed as a normal turn."],
  ["Approval gates", "Security workflows send a yes/no prompt and block until you approve — refuse-by-default if you're offline."],
  ["Proactive push", "Reminders, goal check-ins, and triggers reach you on Telegram or Discord when you're away."],
  ["Live, in-place replies", "A typing indicator and a 💭 bubble that morphs into the answer; long replies auto-chunked."],
];

function RemoteControl() {
  return (
    <section id="control" className="relative scroll-mt-20 overflow-hidden border-t border-line py-16 sm:py-24">
      <div className="grid-backdrop pointer-events-none absolute inset-0 opacity-50" />
      <div className="relative mx-auto max-w-container px-5 sm:px-8">
        <div className="max-w-2xl">
          <SectionLabel>Command it from anywhere</SectionLabel>
          <h2 className="mt-4 text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            One prompt box. <span className="text-gradient-cyan">Three ways to drive it.</span>
          </h2>
          <p className="mt-6 text-lg leading-relaxed text-white/60">
            Every input surface — terminal, HUD, and the Telegram bot — understands the same prefix
            grammar. Talk to it, slash a capability, or drop into a real shell, all from the same
            line.
          </p>
        </div>

        {/* prefix grammar */}
        <div className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PREFIXES.map((p) => (
            <div key={p.name} className="panel panel-hover p-5">
              <div className="flex items-center gap-3">
                <span
                  className="flex h-9 w-9 items-center justify-center rounded-lg font-mono text-lg font-bold"
                  style={{ background: `${p.color}1f`, color: p.color }}
                >
                  {p.sym}
                </span>
                <span className="text-sm font-semibold text-white">{p.name}</span>
              </div>
              <div className="mt-3 rounded-lg border border-line bg-ink-800/70 px-3 py-2 font-mono text-[12px] text-white/70">
                {p.ex}
              </div>
              <p className="mt-3 text-sm leading-relaxed text-white/55">{p.d}</p>
            </div>
          ))}
        </div>

        {/* telegram remote */}
        <div className="mt-16 grid grid-cols-1 items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)]">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-line bg-ink-700/50 px-3.5 py-1.5 text-xs text-white/70">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="#37e6ff">
                <path d="M21.9 4.3 2.6 11.6c-1 .4-1 1.8.1 2.1l4.9 1.5 1.9 6c.3.8 1.3 1 1.9.4l2.7-2.5 5 3.7c.7.5 1.7.1 1.9-.7L23.9 5.5c.2-1-.8-1.6-2-1.2Z" />
              </svg>
              Telegram &amp; Discord
            </div>
            <h3 className="mt-5 text-2xl font-semibold text-white">
              Your machine, in your pocket.
            </h3>
            <p className="mt-3 leading-relaxed text-white/60">
              Connect a Telegram bot and FRIDAY becomes fully remote-controllable — not just chat,
              but the whole control surface: shell, slash commands, file Q&amp;A, voice notes, and
              human-in-the-loop approvals for anything sensitive.
            </p>

            <div className="mt-7 grid gap-x-6 gap-y-4 sm:grid-cols-2">
              {REMOTE.map(([t, d]) => (
                <div key={t} className="flex gap-3">
                  <span className="mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded bg-glow-cyan/15">
                    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#37e6ff" strokeWidth="3">
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  </span>
                  <div>
                    <div className="text-sm font-semibold text-white">{t}</div>
                    <div className="text-[13px] leading-relaxed text-white/55">{d}</div>
                  </div>
                </div>
              ))}
            </div>

            <Link href="/docs/telegram" className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-glow-cyan hover:underline">
              Set up remote control
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </Link>
          </div>

          <TelegramShowcase />
        </div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------- CTA */

function CTA() {
  return (
    <section className="relative border-t border-line py-16 sm:py-24">
      <div className="mx-auto max-w-container px-5 sm:px-8">
        <div className="panel relative overflow-hidden p-8 text-center sm:p-16">
          <div className="absolute left-1/2 top-0 h-64 w-64 -translate-x-1/2 rounded-full bg-glow-blue/15 blur-3xl" />
          <div className="relative">
            <h2 className="mx-auto max-w-2xl text-balance text-3xl font-semibold leading-tight tracking-tight sm:text-5xl">
              Bring the assistant <span className="text-gradient-cyan">home.</span>
            </h2>
            <p className="mx-auto mt-5 max-w-xl text-lg text-white/60">
              Clone it, run one setup script, and say hello. Linux and Windows, MIT licensed,
              no sign-up.
            </p>
            <div className="mx-auto mt-8 flex max-w-md flex-col items-stretch gap-3 sm:flex-row sm:justify-center">
              <Link
                href="/docs/installation"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-semibold text-ink-900 transition-transform hover:scale-[1.03]"
              >
                Install FRIDAY
              </Link>
              <a
                href={GITHUB}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-line bg-ink-700/40 px-6 py-3 text-sm font-medium text-white/80 transition-colors hover:border-white/25 hover:text-white"
              >
                View source
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- helpers */

function SectionLabel({ children }) {
  return (
    <div className="inline-flex items-center gap-2.5 font-mono text-xs uppercase tracking-[0.2em] text-glow-cyan">
      <span className="h-px w-6 bg-glow-cyan/50" />
      {children}
    </div>
  );
}
