// Small reusable icon set, one line family, 2px stroke, matching Vellum.
const s = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };

export const LogoMark = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <g stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M12 12 L6.5 7" /><path d="M12 12 L18 8.5" /><path d="M12 12 L9.5 18.5" />
    </g>
    <g fill="currentColor">
      <circle cx="12" cy="12" r="2.6" /><circle cx="6.5" cy="7" r="1.7" /><circle cx="18" cy="8.5" r="1.7" /><circle cx="9.5" cy="18.5" r="1.7" />
    </g>
  </svg>
);

export const Arrow = ({ size = 16 }) => (
  <svg className="arrow" width={size} height={size} viewBox="0 0 24 24" {...s}><path d="M5 12h14M13 6l6 6-6 6" /></svg>
);
export const Check = ({ size = 16 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M5 13l4 4L19 7" /></svg>
);
export const Search = ({ size = 15 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4-4" /></svg>
);
export const Caret = ({ size = 16, cls = "caret" }) => (
  <svg className={cls} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 9l6 6 6-6" /></svg>
);
export const Sun = () => (
  <svg className="sun" viewBox="0 0 24 24" {...s}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
);
export const Moon = () => (
  <svg className="moon" viewBox="0 0 24 24" {...s}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
);
export const Lines = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><path d="M4 7h16M4 12h16M4 17h10" /></svg>
);
export const Brain = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><path d="M12 3a4 4 0 0 0-4 4 4 4 0 0 0 0 8 4 4 0 0 0 8 0 4 4 0 0 0 0-8 4 4 0 0 0-4-4z" /></svg>
);
export const Graph = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><circle cx="6" cy="7" r="2.5" /><circle cx="18" cy="9" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8 8l8 1.4M7 9l4.5 7M16.5 11l-4 6" /></svg>
);
export const Cap = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><path d="M3 7l9-4 9 4-9 4-9-4zM7 10v5c0 1 2.2 2.5 5 2.5s5-1.5 5-2.5v-5" /></svg>
);
export const Chat = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><path d="M4 4h16v12H7l-3 3z" /></svg>
);
export const Doc = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...s}><path d="M4 5h16v14H4zM4 9h16M9 5v14" /></svg>
);
export const GitHub = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.7c-2.8.6-3.4-1.3-3.4-1.3-.4-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.7.3-1.1.6-1.4-2.2-.2-4.6-1.1-4.6-5 0-1.1.4-2 1-2.7-.1-.3-.4-1.3.1-2.6 0 0 .8-.3 2.7 1a9.4 9.4 0 0 1 5 0c1.9-1.3 2.7-1 2.7-1 .5 1.3.2 2.3.1 2.6.6.7 1 1.6 1 2.7 0 3.9-2.4 4.7-4.6 5 .3.3.7.9.7 1.9v2.8c0 .3.2.6.7.5A10 10 0 0 0 12 2z" /></svg>
);
export const Telegram = ({ size = 17 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor"><path d="M21.9 4.3 18.5 20c-.2 1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.3-4.9 9-8.1c.4-.4-.1-.6-.6-.2L6 14 1.4 12.5c-1-.3-1-1 .2-1.5L20.6 3c.8-.3 1.5.2 1.3 1.3z" /></svg>
);
