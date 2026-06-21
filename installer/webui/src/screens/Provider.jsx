import React, { useEffect, useMemo, useRef, useState } from "react";
import { Spark } from "../components/Logo.jsx";

// Custom dropdown — a native <select>'s popup list is unreliable inside WebView2
// (the engine pywebview uses on Windows), so we render our own list of divs which
// always shows.
function Dropdown({ options, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const current = options.find((o) => o.id === value);

  useEffect(() => {
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        className="field flex items-center justify-between text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <span>{current ? current.label : "Select…"}</span>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" className={"transition " + (open ? "rotate-180" : "")}>
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <ul className="absolute z-20 mt-2 max-h-64 w-full overflow-y-auto scroll-thin rounded-xl border border-line bg-white py-1 shadow-card">
          {options.map((o) => (
            <li key={o.id}>
              <button
                type="button"
                className={
                  "flex w-full items-center justify-between px-4 py-2.5 text-left text-[15px] transition hover:bg-brand-wash " +
                  (o.id === value ? "text-brand" : "text-ink")
                }
                onClick={() => {
                  onChange(o.id);
                  setOpen(false);
                }}
              >
                {o.label}
                {o.id === value && (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Provider({ providers, onSave, busy }) {
  const [pid, setPid] = useState(providers[0]?.id || "anthropic");
  const current = useMemo(() => providers.find((p) => p.id === pid) || providers[0], [providers, pid]);
  const [model, setModel] = useState(current?.model || "");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(current?.base_url || "");

  // When providers arrive (async), seed the first one's model/base URL.
  useEffect(() => {
    if (providers.length && !providers.find((p) => p.id === pid)) {
      const first = providers[0];
      setPid(first.id);
      setModel(first.model || "");
      setBaseUrl(first.base_url || "");
    }
  }, [providers]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (id) => {
    const p = providers.find((x) => x.id === id);
    setPid(id);
    setModel(p?.model || "");
    setBaseUrl(p?.base_url || "");
    setApiKey("");
  };

  const isCompat = pid === "openai_compat";

  const save = () => {
    const provider = { type: pid, model: model.trim() };
    if (apiKey.trim()) provider.api_key = apiKey.trim();
    if (isCompat && baseUrl.trim()) provider.base_url = baseUrl.trim();
    onSave(provider);
  };

  // Defaults still loading — show a gentle placeholder instead of an empty list.
  if (!providers.length) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-ink-soft animate-fade">
        <Spark size={26} className="animate-pulse text-brand" />
        <p className="text-[15px]">Loading providers…</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-lg flex-col justify-center px-10 py-8 animate-rise">
      <div className="flex items-center gap-2.5">
        <Spark size={22} className="text-brand" />
        <h2 className="text-[24px] font-semibold text-ink">Choose your AI provider</h2>
      </div>
      <p className="mt-1.5 text-[14px] text-ink-soft">
        The &ldquo;brain&rdquo; behind Namma Agent. You can change this later in Settings.
      </p>

      <div className="mt-6 space-y-4">
        <div>
          <label className="label">Provider</label>
          <Dropdown options={providers} value={pid} onChange={pick} />
        </div>

        <div>
          <label className="label">Model</label>
          <input className="field" value={model} onChange={(e) => setModel(e.target.value)} placeholder="model name" />
        </div>

        {current?.needs_key && (
          <div>
            <label className="label">API key</label>
            <input
              className="field font-mono"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Paste your key — stored locally in .env"
            />
            <p className="mt-1 text-[12px] text-ink-faint">
              Stays on this computer. Leave blank for local providers (Ollama, LM Studio).
            </p>
          </div>
        )}

        {isCompat && (
          <div>
            <label className="label">Base URL</label>
            <input
              className="field font-mono"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </div>
        )}
      </div>

      <div className="mt-8 flex justify-end gap-2">
        <button className="btn-ghost px-5 py-3" onClick={() => onSave(null)} disabled={busy}>
          Skip for now
        </button>
        <button className="btn-primary px-7" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Continue"}
        </button>
      </div>
    </div>
  );
}
