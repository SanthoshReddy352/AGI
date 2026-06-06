// A stylised Telegram chat showing FRIDAY being driven remotely:
// shell command, slash command, voice note, and a security approval gate.
function Bubble({ side = "in", children, meta }) {
  const inbound = side === "in";
  return (
    <div className={`flex ${inbound ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] leading-relaxed ${
          inbound
            ? "rounded-tl-sm border border-line bg-ink-700/70 text-white/85"
            : "rounded-tr-sm bg-gradient-to-br from-glow-blue/30 to-glow-violet/25 text-white"
        }`}
      >
        {children}
        {meta && <div className="mt-1 text-right text-[10px] text-white/35">{meta}</div>}
      </div>
    </div>
  );
}

export default function TelegramShowcase() {
  return (
    <div className="relative mx-auto w-full max-w-[420px]">
      <div className="absolute -inset-6 rounded-[32px] bg-glow-blue/10 blur-3xl" />
      <div className="relative overflow-hidden rounded-[26px] border border-line bg-ink-800/90 shadow-2xl">
        {/* chat header */}
        <div className="flex items-center gap-3 border-b border-line bg-ink-700/60 px-4 py-3">
          <div className="relative flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-glow-cyan to-glow-violet text-xs font-bold text-ink-900">
            F
            <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-ink-700 bg-emerald-400" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-semibold text-white">FRIDAY</div>
            <div className="text-[11px] text-glow-cyan">online · on your machine</div>
          </div>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-white/30">
            <path d="M21.5 15.5A2 2 0 0 1 19.7 18 18 18 0 0 1 6 4.3 2 2 0 0 1 8.5 2.5l1.5 3-1.3 1.9a14 14 0 0 0 6 6l1.9-1.3 3 1.5Z" />
          </svg>
        </div>

        {/* messages */}
        <div className="space-y-2.5 px-3.5 py-4">
          <Bubble side="out" meta="21:04">
            <span className="font-mono text-glow-cyan">!</span>
            <span className="font-mono">sudo systemctl restart nginx</span>
          </Bubble>
          <Bubble side="in" meta="21:04">
            <div className="font-mono text-[11px] text-white/60">[sudo] password for you:</div>
            <div className="mt-1 text-[11px] text-white/50">Awaiting password — reply with <span className="text-glow-cyan">{"> ••••"}</span></div>
          </Bubble>
          <Bubble side="out" meta="21:04">
            <span className="font-mono text-glow-cyan">{"> "}</span>
            <span className="font-mono text-white/50">••••••••</span>
          </Bubble>
          <Bubble side="in" meta="21:04">
            <div className="font-mono text-[11px] text-emerald-300/90">✓ nginx restarted · [exit 0]</div>
          </Bubble>

          <div className="py-1 text-center text-[10px] uppercase tracking-widest text-white/20">slash command</div>

          <Bubble side="out" meta="21:06">
            <span className="font-mono text-glow-violet">/deep</span>{" "}
            <span className="font-mono">RISC-V vs ARM in 2026</span>
          </Bubble>
          <Bubble side="in" meta="21:06">
            <span className="inline-flex items-center gap-1.5">
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-glow-cyan" />
              Researching across sources… briefing saved to disk.
            </span>
          </Bubble>

          <div className="py-1 text-center text-[10px] uppercase tracking-widest text-white/20">voice note + approval</div>

          <Bubble side="out" meta="21:09">
            <span className="inline-flex items-center gap-2">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" className="text-glow-cyan">
                <path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Zm7 9a7 7 0 0 1-14 0M12 19v3" stroke="currentColor" strokeWidth="2" fill="none" />
              </svg>
              <span className="flex items-end gap-[2px]">
                {[6, 11, 7, 14, 9, 5, 12, 8].map((h, i) => (
                  <span key={i} className="w-[2px] rounded-full bg-white/60" style={{ height: h }} />
                ))}
              </span>
              <span className="text-[11px] text-white/50">0:04</span>
            </span>
          </Bubble>
          <Bubble side="in" meta="21:09">
            Run a port scan on the lab host?
            <div className="mt-2 flex gap-2">
              <span className="rounded-md bg-emerald-500/15 px-2 py-1 text-[11px] text-emerald-300">approve</span>
              <span className="rounded-md bg-red-500/15 px-2 py-1 text-[11px] text-red-300">deny</span>
            </div>
          </Bubble>
        </div>

        {/* input bar */}
        <div className="flex items-center gap-2 border-t border-line bg-ink-700/50 px-3.5 py-3">
          <div className="flex-1 rounded-full border border-line bg-ink-800/80 px-3.5 py-2 text-[12px] text-white/30">
            Message FRIDAY…
          </div>
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-glow-cyan to-glow-violet text-ink-900">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 11 22 2l-9 19-2-8-8-2Z" />
            </svg>
          </div>
        </div>
      </div>
    </div>
  );
}
