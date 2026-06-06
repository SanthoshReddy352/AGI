import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";

export const metadata = {
  title: "Capabilities",
  description: "Everything FRIDAY can do, grouped by domain.",
};

const groups = [
  {
    title: "Voice & conversation",
    items: [
      ["Wake word", "“Hey Friday” via Porcupine, with a configurable session timeout."],
      ["Speech-to-text", "faster-whisper (base.en, int8) with adaptive VAD profiles and barge-in."],
      ["Text-to-speech", "Piper neural TTS; falls back gracefully across audio backends."],
      ["Natural chat", "Local chat model, session-aware turns, custom personas, three-tier memory."],
    ],
  },
  {
    title: "System control",
    items: [
      ["Brightness & volume", "Set, raise, lower — with spoken cardinals (“fifty”, “max”)."],
      ["Screen lock / unlock", "Confirmation-gated; explicit /lock slash bypasses the guard."],
      ["Screenshots", "Capture and (with vision) explain what's on screen."],
      ["App launch & windows", "Fuzzy app matching, launch, window queries, clipboard."],
      ["System info", "CPU / RAM / battery status (status-framed to avoid false triggers)."],
    ],
  },
  {
    title: "Knowledge & vision",
    items: [
      ["Document intelligence", "Index PDFs / Office / Markdown and ask questions via local RAG."],
      ["Screenshot explainer", "Describe, summarize, or OCR the current screen with a local VLM."],
      ["UI-element finder", "Locate elements on screen; debug code from a screenshot."],
      ["Memory recall", "“What do you remember about me?” routes to deterministic recall."],
    ],
  },
  {
    title: "Online skills (opt-in)",
    items: [
      ["Web & quick-answer search", "DuckDuckGo + arXiv parallel search with LLM summarisation."],
      ["Browser automation", "YouTube, YouTube Music, Google via Playwright / Selenium."],
      ["News & world monitor", "Categorised feeds and world events."],
      ["Weather", "Current conditions for a named location."],
    ],
  },
  {
    title: "Productivity",
    items: [
      ["Reminders & calendar", "Local reminders; Google Calendar via the workspace path."],
      ["Notes & dictation", "Capture notes and long-form memos to your Documents folder."],
      ["Tasks & goals", "Track goals with progress; multi-step task workflows."],
      ["Focus sessions", "Pomodoro with notification muting."],
    ],
  },
  {
    title: "Remote control & commands",
    items: [
      ["Telegram bot (two-way)", "Drive the whole assistant from your phone — chat, shell, slash commands, file Q&A, voice notes."],
      ["Slash commands", "13 built-ins (/new, /deep, /web, /lock…) dispatched before the router, with Telegram autocomplete."],
      ["Interactive ! shell", "PTY-backed shell with > stdin follow-ups for sudo / prompts; venv-aware, screen-lock gated."],
      ["Approval gates", "Human-in-the-loop yes/no for sensitive workflows; refuse-by-default when offline."],
      ["Proactive push", "Reminders, goal check-ins, and triggers pushed to Telegram / Discord."],
    ],
  },
  {
    title: "Privacy & safety",
    items: [
      ["Online consent gate", "Ask-before-online; every network reach is logged to a local audit."],
      ["Scoped security tooling", "Lab-mode security utilities, gated and scoped."],
      ["Local audit log", "A record of permissioned actions you can inspect."],
    ],
  },
];

export default function Capabilities() {
  return (
    <>
      <DocHeader
        eyebrow="Concepts"
        title="Capabilities"
        intro="FRIDAY ships 28 capability modules. Each is a self-contained capability in the registry, and each common phrasing has a deterministic intent pattern so it routes instantly and reliably."
      />

      {groups.map((g) => (
        <section key={g.title}>
          <h2 id={g.title.toLowerCase().replace(/[^a-z]+/g, "-")}>{g.title}</h2>
          <div className="my-5 grid gap-3 sm:grid-cols-2">
            {g.items.map(([t, d]) => (
              <div key={t} className="rounded-xl border border-line bg-ink-700/40 p-4">
                <div className="text-sm font-semibold text-white">{t}</div>
                <div className="mt-1 text-sm text-white/55">{d}</div>
              </div>
            ))}
          </div>
        </section>
      ))}

      <Callout tone="note" title="Every capability has an intent pattern">
        A capability without a deterministic regex pattern is at the mercy of the small chat model.
        That&apos;s why adding a tool always means adding its phrasings too — see{" "}
        <Link href="/docs/adding-tools">Add a new tool</Link>.
      </Callout>

      <PrevNext current="/docs/capabilities" />
    </>
  );
}
