function Dot({ state }) {
  const color =
    state === "running" ? "bg-brand animate-pulse"
    : state === "ok" ? "bg-emerald-500"
    : state === "fail" ? "bg-red-500"
    : "bg-ink-faint";
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />;
}

// Live "what FRIDAY is doing" panel during a turn (preambles + tool steps).
export default function Timeline({ items }) {
  if (!items.length) return null;
  return (
    <div className="flex gap-3 animate-rise">
      <div className="h-7 w-7 shrink-0" />
      <div className="flex-1 rounded-xl border border-line dark:border-night-line bg-paper-soft dark:bg-night-soft px-3.5 py-2.5">
        <div className="text-[10px] uppercase tracking-wider text-ink-faint dark:text-night-faint mb-1.5">working</div>
        <ul className="space-y-1">
          {items.map((it, i) => (
            <li key={i} className="flex items-start gap-2 text-[13px]">
              {it.kind === "preamble" ? (
                <span className="italic text-ink-soft dark:text-night-faint">“{it.text}”</span>
              ) : (
                <>
                  <span className="mt-1.5"><Dot state={it.state} /></span>
                  <span className="font-mono text-[12.5px] text-ink-soft dark:text-night-ink">
                    {it.tool}
                    {it.summary && <span className="ml-1.5 text-ink-faint dark:text-night-faint">— {it.summary}</span>}
                  </span>
                </>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
