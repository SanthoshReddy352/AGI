"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { docsNav } from "./docs-nav";

export default function DocSidebar({ onNavigate }) {
  const pathname = usePathname();
  return (
    <nav className="space-y-7">
      {docsNav.map((section) => (
        <div key={section.title}>
          <div className="mb-2.5 px-3 text-xs font-semibold uppercase tracking-wider text-white/35">
            {section.title}
          </div>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const active = pathname === item.href;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    className={`block rounded-lg px-3 py-1.5 text-sm transition-colors ${
                      active
                        ? "bg-glow-cyan/10 font-medium text-glow-cyan"
                        : "text-white/55 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
