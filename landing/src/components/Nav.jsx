import { Link } from "react-router-dom";
import { LogoMark, Search, Sun, Moon } from "./icons.jsx";

const reduce = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
export function scrollToId(id) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: reduce() ? "auto" : "smooth", block: "start" });
}

// A single configurable premium nav. `items` are either route links (with `to`)
// or in-page section links (with `id`, optionally `spy` for scrollspy).
export default function Nav({ items = [], mega = null, showCmdk = false, cta, mobileItems = [] }) {
  const renderLink = (it, cls = "navx__link") => {
    if (it.href) return <a key={it.label} className={cls} href={it.href} target={it.external ? "_blank" : undefined} rel={it.external ? "noreferrer" : undefined}>{it.label}</a>;
    if (it.to) return <Link key={it.label} className={cls} to={it.to}>{it.label}</Link>;
    return (
      <a
        key={it.label}
        className={cls}
        href={`#${it.id}`}
        {...(it.spy ? { "data-spy": it.id } : {})}
        onClick={(e) => { e.preventDefault(); scrollToId(it.id); }}
      >
        {it.label}
      </a>
    );
  };

  return (
    <>
      <nav className="navx" aria-label="Primary">
        <div className="navx__bar">
          <Link className="navx__brand" to="/">
            <span className="mark" aria-hidden="true"><LogoMark size={16} /></span> Namma Agent
          </Link>
          <div className="navx__nav">
            <span className="navx__pill" aria-hidden="true"></span>
            {items.map((it) => (it.mega ? mega : renderLink(it)))}
          </div>
          <div className="navx__right">
            {showCmdk && (
              <button className="cmdk" data-cmdk-open aria-label="Search">
                <Search /><span className="cmdk__label">Search</span><kbd>⌘K</kbd>
              </button>
            )}
            <button className="icon-btn" data-theme-toggle aria-label="Toggle theme"><Sun /><Moon /></button>
            {cta && (cta.to
              ? <Link to={cta.to} className="btn btn--primary btn--sm" data-magnetic>{cta.label}</Link>
              : <a href={`#${cta.id}`} onClick={(e) => { e.preventDefault(); scrollToId(cta.id); }} className="btn btn--primary btn--sm" data-magnetic>{cta.label}</a>
            )}
            <button className="burger" aria-label="Open menu" aria-expanded="false"><span></span><span></span><span></span></button>
          </div>
        </div>
      </nav>
      <div className="mobilemenu" aria-hidden="true">
        {mobileItems.map((it, i) =>
          it.href
            ? <a key={it.label} href={it.href} style={{ "--i": i }} target={it.external ? "_blank" : undefined} rel={it.external ? "noreferrer" : undefined}>{it.label}</a>
            : it.to
              ? <Link key={it.label} to={it.to} style={{ "--i": i }}>{it.label}</Link>
              : <a key={it.label} href={`#${it.id}`} style={{ "--i": i }} onClick={(e) => { e.preventDefault(); scrollToId(it.id); }}>{it.label}</a>
        )}
        <div className="mm-foot">
          <a href="https://github.com/SanthoshReddy352/Namma-Agent" className="btn btn--secondary">GitHub</a>
          {cta && (cta.to
            ? <Link to={cta.to} className="btn btn--primary">{cta.label}</Link>
            : <a href={`#${cta.id}`} onClick={(e) => { e.preventDefault(); scrollToId(cta.id); }} className="btn btn--primary">{cta.label}</a>)}
        </div>
      </div>
    </>
  );
}
