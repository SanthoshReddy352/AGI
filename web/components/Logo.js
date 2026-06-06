// FRIDAY wordmark with a compact voice-core glyph.
export default function Logo({ className = "" }) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <svg width="26" height="26" viewBox="0 0 32 32" fill="none" aria-hidden>
        <defs>
          <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#37e6ff" />
            <stop offset="100%" stopColor="#8b5cff" />
          </linearGradient>
        </defs>
        <circle cx="16" cy="16" r="14" stroke="url(#lg)" strokeWidth="1.4" opacity="0.5" />
        <circle cx="16" cy="16" r="9" stroke="url(#lg)" strokeWidth="1.2" opacity="0.35" />
        <g stroke="url(#lg)" strokeWidth="2.2" strokeLinecap="round">
          <line x1="12" y1="13" x2="12" y2="19" />
          <line x1="16" y1="10" x2="16" y2="22" />
          <line x1="20" y1="14" x2="20" y2="18" />
        </g>
      </svg>
      <span className="text-[15px] font-semibold tracking-[0.18em] text-white">FRIDAY</span>
    </span>
  );
}
