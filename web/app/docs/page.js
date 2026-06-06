import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";

export const metadata = {
  title: "Documentation",
  description: "FRIDAY documentation — install, architecture, routing, and building new tools.",
};

const cards = [
  { href: "/docs/getting-started", t: "Getting started", d: "From clone to your first spoken command in a few minutes." },
  { href: "/docs/installation", t: "Installation", d: "Linux & Windows setup, models, requirements, troubleshooting." },
  { href: "/docs/architecture", t: "Architecture", d: "The turn pipeline, stores, memory, and how the pieces connect." },
  { href: "/docs/how-it-works", t: "How routing works", d: "The deterministic 6-layer router and its confidence bands." },
  { href: "/docs/capabilities", t: "Capabilities", d: "Everything FRIDAY can do, grouped by domain." },
  { href: "/docs/commands", t: "Commands & shell", d: "The / slash, ! shell, and > follow-up prefix grammar." },
  { href: "/docs/telegram", t: "Telegram & remote", d: "Drive the full control surface from your phone." },
  { href: "/docs/adding-tools", t: "Add a new tool", d: "Register a capability and wire its intent pattern + tests." },
];

export default function DocsHome() {
  return (
    <>
      <DocHeader
        eyebrow="Documentation"
        title="Build, run, and extend FRIDAY"
        intro="FRIDAY is a local-first, voice-driven AI assistant for Linux and Windows. These docs take you from a fresh clone to writing your own capabilities."
      />

      <Callout tone="note" title="New here?">
        Start with <Link href="/docs/getting-started">Getting started</Link>, then read{" "}
        <Link href="/docs/how-it-works">How routing works</Link> to understand what makes a
        local-first agent actually reliable.
      </Callout>

      <div className="my-8 grid gap-4 sm:grid-cols-2">
        {cards.map((c) => (
          <Link key={c.href} href={c.href} className="panel panel-hover group block p-5">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-white group-hover:text-glow-cyan">{c.t}</h3>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-white/30 transition-transform group-hover:translate-x-0.5 group-hover:text-glow-cyan">
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </div>
            <p className="mt-1.5 text-sm text-white/55">{c.d}</p>
          </Link>
        ))}
      </div>

      <h2>What FRIDAY is</h2>
      <p>
        Say <strong>“Hey Friday”</strong> and ask it to set your brightness, find a file,
        summarize a PDF, look something up, or run a multi-step workflow — and it does the work
        on your machine, narrating progress out loud. It is built around three ideas:
      </p>
      <ul>
        <li>
          <strong>Local-first.</strong> Speech-to-text, the conversational model, the planning
          model, vision, and embeddings all run on your hardware. No account, no cloud inference,
          no telemetry. Online skills are opt-in and ask for consent.
        </li>
        <li>
          <strong>Capability-driven.</strong> Every skill is a self-contained capability in an
          MCP-compatible registry. A deterministic intent layer routes common phrasings instantly;
          anything else falls through to a local planning model.
        </li>
        <li>
          <strong>Cross-platform.</strong> One codebase runs on Linux and Windows, with
          platform-specific paths guarded throughout.
        </li>
      </ul>

      <Callout tone="warn" title="Early-stage project (v0.1)">
        Expect rough edges. If you hit one,{" "}
        <a href="https://github.com/SanthoshReddy352/Friday_Linux/issues" target="_blank" rel="noreferrer">
          open an issue
        </a>
        .
      </Callout>

      <PrevNext current="/docs" />
    </>
  );
}
