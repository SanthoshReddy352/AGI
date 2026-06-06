import Link from "next/link";
import { docsOrder } from "./docs-nav";

export function DocHeader({ eyebrow, title, intro }) {
  return (
    <header className="mb-10 border-b border-line pb-8">
      {eyebrow && (
        <div className="mb-3 font-mono text-xs uppercase tracking-[0.2em] text-glow-cyan">{eyebrow}</div>
      )}
      <h1 className="text-balance text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
      {intro && <p className="mt-4 max-w-2xl text-base leading-relaxed text-white/60 sm:text-lg">{intro}</p>}
    </header>
  );
}

const tones = {
  note: { ring: "border-glow-cyan/25", bg: "bg-glow-cyan/[0.06]", dot: "text-glow-cyan", label: "Note" },
  warn: { ring: "border-glow-amber/25", bg: "bg-glow-amber/[0.06]", dot: "text-glow-amber", label: "Heads up" },
  tip: { ring: "border-glow-violet/25", bg: "bg-glow-violet/[0.06]", dot: "text-glow-violet", label: "Tip" },
};

export function Callout({ tone = "note", title, children }) {
  const t = tones[tone] || tones.note;
  return (
    <div className={`my-6 rounded-xl border ${t.ring} ${t.bg} p-5`}>
      <div className={`mb-1.5 flex items-center gap-2 text-sm font-semibold ${t.dot}`}>
        <span className="inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        {title || t.label}
      </div>
      <div className="text-sm leading-relaxed text-white/70">{children}</div>
    </div>
  );
}

export function PrevNext({ current }) {
  const idx = docsOrder.findIndex((d) => d.href === current);
  const prev = idx > 0 ? docsOrder[idx - 1] : null;
  const next = idx >= 0 && idx < docsOrder.length - 1 ? docsOrder[idx + 1] : null;
  return (
    <div className="mt-14 grid gap-4 border-t border-line pt-8 sm:grid-cols-2">
      {prev ? (
        <Link href={prev.href} className="panel panel-hover group p-4">
          <div className="text-xs text-white/40">← Previous</div>
          <div className="mt-1 text-sm font-medium text-white group-hover:text-glow-cyan">{prev.label}</div>
        </Link>
      ) : (
        <span />
      )}
      {next && (
        <Link href={next.href} className="panel panel-hover group p-4 text-right sm:col-start-2">
          <div className="text-xs text-white/40">Next →</div>
          <div className="mt-1 text-sm font-medium text-white group-hover:text-glow-cyan">{next.label}</div>
        </Link>
      )}
    </div>
  );
}

// Small labelled grid used on concept pages.
export function FactGrid({ items }) {
  return (
    <div className="my-6 grid gap-3 sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k} className="rounded-xl border border-line bg-ink-700/40 p-4">
          <div className="font-mono text-xs uppercase tracking-wider text-glow-cyan/80">{k}</div>
          <div className="mt-1.5 text-sm text-white/70">{v}</div>
        </div>
      ))}
    </div>
  );
}
