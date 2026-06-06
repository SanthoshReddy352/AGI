"use client";

// Futuristic "voice core" artwork: concentric orbital rings, an inner
// gradient core, and a live waveform — the visual signature of FRIDAY.
export default function VoiceOrb({ className = "" }) {
  const bars = [0.4, 0.7, 1, 0.55, 0.85, 0.35, 0.95, 0.6, 0.45, 0.8, 0.5];
  return (
    <div className={`relative mx-auto aspect-square w-full max-w-[280px] sm:max-w-[400px] lg:max-w-[460px] ${className}`}>
      {/* expanding pulse rings */}
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="absolute h-1/2 w-1/2 rounded-full border border-glow-cyan/40 animate-pulse-ring" />
        <span
          className="absolute h-1/2 w-1/2 rounded-full border border-glow-violet/40 animate-pulse-ring"
          style={{ animationDelay: "1s" }}
        />
        <span
          className="absolute h-1/2 w-1/2 rounded-full border border-glow-blue/40 animate-pulse-ring"
          style={{ animationDelay: "2s" }}
        />
      </div>

      <svg viewBox="0 0 460 460" className="absolute inset-0 h-full w-full">
        <defs>
          <radialGradient id="core" cx="50%" cy="45%" r="55%">
            <stop offset="0%" stopColor="#bff3ff" />
            <stop offset="35%" stopColor="#37e6ff" />
            <stop offset="75%" stopColor="#4f7bff" />
            <stop offset="100%" stopColor="#8b5cff" />
          </radialGradient>
          <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#37e6ff" stopOpacity="0.9" />
            <stop offset="50%" stopColor="#4f7bff" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#8b5cff" stopOpacity="0.9" />
          </linearGradient>
          <filter id="soft" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" />
          </filter>
        </defs>

        {/* outer dashed orbit */}
        <g className="origin-center animate-spin-slow" style={{ transformBox: "fill-box" }}>
          <circle cx="230" cy="230" r="210" fill="none" stroke="url(#ring)" strokeWidth="1" strokeDasharray="2 10" opacity="0.6" />
        </g>
        {/* mid orbit */}
        <g className="origin-center animate-spin-reverse" style={{ transformBox: "fill-box" }}>
          <circle cx="230" cy="230" r="168" fill="none" stroke="url(#ring)" strokeWidth="1.4" strokeDasharray="60 26" opacity="0.7" />
          <circle cx="62" cy="230" r="4" fill="#37e6ff" />
          <circle cx="398" cy="230" r="3" fill="#8b5cff" />
        </g>
        {/* inner orbit */}
        <g className="origin-center animate-spin-slow" style={{ transformBox: "fill-box", animationDuration: "26s" }}>
          <circle cx="230" cy="230" r="126" fill="none" stroke="url(#ring)" strokeWidth="1" opacity="0.5" />
          <circle cx="230" cy="104" r="3.5" fill="#bff3ff" />
        </g>

        {/* glowing core */}
        <circle cx="230" cy="230" r="92" fill="url(#core)" opacity="0.18" filter="url(#soft)" />
        <circle cx="230" cy="230" r="74" fill="none" stroke="url(#core)" strokeWidth="1.5" opacity="0.55" />
      </svg>

      {/* center waveform */}
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="flex h-20 items-center gap-[5px]">
          {bars.map((h, i) => (
            <span
              key={i}
              className="wavebar"
              style={{
                height: `${h * 100}%`,
                animationDelay: `${i * 0.08}s`,
                animationDuration: `${0.9 + (i % 3) * 0.25}s`,
              }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
