import Link from "next/link";
import Logo from "./Logo";

const GITHUB = "https://github.com/SanthoshReddy352/Friday_Linux";

export default function Footer() {
  return (
    <footer className="relative border-t border-line">
      <div className="mx-auto max-w-container px-5 py-14 sm:px-8">
        <div className="flex flex-col justify-between gap-10 md:flex-row">
          <div className="max-w-sm">
            <Logo />
            <p className="mt-4 text-sm leading-relaxed text-white/50">
              A local-first, voice-driven AI assistant for Linux &amp; Windows. Reasoning,
              voice, and memory run on your machine — online only when you ask.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-10 sm:grid-cols-3">
            <FooterCol
              title="Product"
              items={[
                { label: "Capabilities", href: "/#capabilities" },
                { label: "How it routes", href: "/#router" },
                { label: "Local-first", href: "/#local-first" },
              ]}
            />
            <FooterCol
              title="Docs"
              items={[
                { label: "Getting started", href: "/docs/getting-started" },
                { label: "Installation", href: "/docs/installation" },
                { label: "Telegram & remote", href: "/docs/telegram" },
                { label: "Add a tool", href: "/docs/adding-tools" },
              ]}
            />
            <FooterCol
              title="Project"
              items={[
                { label: "GitHub", href: GITHUB, external: true },
                { label: "Issues", href: `${GITHUB}/issues`, external: true },
                { label: "License (MIT)", href: `${GITHUB}/blob/main/LICENSE`, external: true },
              ]}
            />
          </div>
        </div>

        <div className="hairline my-10" />

        <div className="flex flex-col items-center justify-between gap-3 text-xs text-white/40 sm:flex-row">
          <p>© {new Date().getFullYear()} FRIDAY contributors · MIT Licensed</p>
          <p className="font-mono">Local-first. Voice-native. Yours.</p>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, items }) {
  return (
    <div>
      <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-white/40">{title}</h4>
      <ul className="space-y-2.5">
        {items.map((it) => (
          <li key={it.label}>
            {it.external ? (
              <a href={it.href} target="_blank" rel="noreferrer" className="text-sm text-white/60 transition-colors hover:text-white">
                {it.label}
              </a>
            ) : (
              <Link href={it.href} className="text-sm text-white/60 transition-colors hover:text-white">
                {it.label}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
