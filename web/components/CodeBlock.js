"use client";

import { useState } from "react";

// Minimal terminal-style code block with a copy button.
export default function CodeBlock({ children, label, lang = "bash" }) {
  const [copied, setCopied] = useState(false);
  const text = typeof children === "string" ? children : String(children ?? "");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text.trim());
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="group relative my-5 overflow-hidden rounded-xl border border-line bg-ink-800/80">
      <div className="flex items-center justify-between border-b border-line bg-ink-700/50 px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="h-2.5 w-2.5 rounded-full bg-white/15" />
          <span className="ml-2 font-mono text-[11px] text-white/40">{label || lang}</span>
        </div>
        <button
          onClick={copy}
          className="rounded-md px-2 py-1 font-mono text-[11px] text-white/50 transition-colors hover:bg-white/5 hover:text-white"
        >
          {copied ? "copied ✓" : "copy"}
        </button>
      </div>
      <pre className="code-scroll overflow-x-auto px-4 py-4 text-[13px] leading-relaxed">
        <code className="font-mono text-white/85">{text.trim()}</code>
      </pre>
    </div>
  );
}
