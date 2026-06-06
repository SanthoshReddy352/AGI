"use client";

import Link from "next/link";
import { useState } from "react";
import Logo from "@/components/Logo";
import DocSidebar from "@/components/DocSidebar";

const GITHUB = "https://github.com/SanthoshReddy352/Friday_Linux";

export default function DocsLayout({ children }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-screen">
      {/* top bar */}
      <header className="sticky top-0 z-50 border-b border-line bg-ink-900/75 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1320px] items-center justify-between px-5 sm:px-8">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setOpen((v) => !v)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line text-white/70 lg:hidden"
              aria-label="Toggle docs menu"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                {open ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
              </svg>
            </button>
            <Link href="/" className="transition-opacity hover:opacity-80">
              <Logo />
            </Link>
            <span className="ml-1 rounded-md border border-line px-2 py-0.5 font-mono text-[11px] text-white/40">docs</span>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/" className="hidden text-sm text-white/60 hover:text-white sm:block">
              ← Home
            </Link>
            <a
              href={GITHUB}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-sm text-white/70 transition-colors hover:border-white/25 hover:text-white"
            >
              GitHub
            </a>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-[1320px] gap-10 px-5 sm:px-8">
        {/* sidebar — desktop */}
        <aside className="hidden w-60 shrink-0 py-10 lg:block">
          <div className="sticky top-24">
            <DocSidebar />
          </div>
        </aside>

        {/* sidebar — mobile drawer */}
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-ink-900/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
            <div className="absolute left-0 top-16 bottom-0 w-72 overflow-y-auto border-r border-line bg-ink-800 p-5">
              <DocSidebar onNavigate={() => setOpen(false)} />
            </div>
          </div>
        )}

        {/* content */}
        <main className="min-w-0 flex-1 py-10 lg:py-12">
          <article className="prose-friday max-w-prose">{children}</article>
        </main>
      </div>
    </div>
  );
}
