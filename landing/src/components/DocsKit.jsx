import { useState } from "react";

// Code block with a title bar and a copy button.
export function Code({ title = "bash", lang, code }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* clipboard blocked; ignore */ }
  };
  return (
    <div className="codeblock">
      <div className="codeblock__bar">
        <span>{title}</span>
        <span className="lang">{lang || ""}</span>
        <button className="copy-btn" onClick={copy} type="button">{copied ? "copied" : "copy"}</button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

// 4x mermaid diagram figure.
export function Diagram({ src, alt, caption }) {
  return (
    <figure className="diagram" data-reveal="scale">
      <img src={src} alt={alt} loading="lazy" />
      {caption && <figcaption><b>{alt}.</b> {caption}</figcaption>}
    </figure>
  );
}

export function Note({ kind = "", title, children }) {
  return (
    <div className={`note ${kind}`}>
      {title && <b>{title}. </b>}{children}
    </div>
  );
}

export function CfgTable({ rows }) {
  return (
    <div className="cfg-table-wrap">
      <table className="cfg-table">
        <thead><tr><th>Key</th><th>What it does</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r[0]}><td>{r[0]}</td><td>{r[1]}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
