import { useEffect, useState } from "react";
import { clearMemory, fetchModels, fetchProviders, fetchSettings, saveSettings } from "../api.js";

const get = (o, path, d) => path.split(".").reduce((x, k) => (x == null ? x : x[k]), o) ?? d;
function nest(path, value) {
  const out = {}; let cur = out; const ks = path.split(".");
  ks.forEach((k, i) => { if (i === ks.length - 1) cur[k] = value; else cur = cur[k] = {}; });
  return out;
}
function deepMerge(a, b) {
  for (const k in b) {
    if (b[k] && typeof b[k] === "object" && !Array.isArray(b[k])) a[k] = deepMerge(a[k] || {}, b[k]);
    else a[k] = b[k];
  }
  return a;
}

const TABS = ["Provider", "Behavior", "Persona", "Browser", "Voice", "Telegram", "Appearance", "Memory"];

export default function Settings({ onClose, theme, onThemeToggle, onMemoryCleared }) {
  const [tab, setTab] = useState("Provider");
  const [data, setData] = useState(null);
  const [providers, setProviders] = useState([]);
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [cfg, setCfg] = useState({});
  const [env, setEnv] = useState({});
  const [saved, setSaved] = useState(false);
  const [cleared, setCleared] = useState("");

  useEffect(() => { fetchSettings().then(setData); fetchProviders().then((p) => setProviders(p?.providers || [])); }, []);

  const cur = (path, d) => {
    const pending = path.split(".").reduce((x, k) => (x == null ? x : x[k]), cfg);
    return pending !== undefined ? pending : get(data?.config, path, d);
  };
  const setC = (path, value) => setCfg((c) => deepMerge({ ...c }, nest(path, value)));

  const activeType = cur("provider.type", "");
  const activeBase = cur("provider.base_url", "");

  async function loadModels(type, base) {
    if (!type) return;
    setLoadingModels(true);
    const r = await fetchModels(type, base || "");
    setModels(r?.models || []);
    setLoadingModels(false);
  }
  useEffect(() => { if (data) loadModels(activeType, activeBase); /* eslint-disable-next-line */ }, [data, activeType]);

  function selectProvider(p) {
    setC("provider.type", p.type);
    setC("provider.api_key_env", p.key_env || "");
    setC("provider.base_url", p.base_url || "");
    setModels([]);
    loadModels(p.type, p.base_url || "");
  }

  async function save() { await saveSettings(cfg, env); setSaved(true); setTimeout(() => setSaved(false), 2500); }
  async function wipe(scope) { await clearMemory(scope); setCleared(scope); onMemoryCleared?.(); setTimeout(() => setCleared(""), 2500); }

  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()}
           className="w-[820px] max-w-full h-[86vh] flex flex-col rounded-2xl bg-paper-panel dark:bg-night-panel border border-line dark:border-night-line shadow-pop overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-line dark:border-night-line">
          <h2 className="font-serif text-lg">Settings</h2>
          <button onClick={onClose} className="text-ink-faint hover:text-ink text-xl leading-none">×</button>
        </div>

        <div className="flex-1 flex min-h-0">
          {/* Left tab nav */}
          <nav className="w-40 shrink-0 border-r border-line dark:border-night-line p-2 space-y-0.5 overflow-y-auto">
            {TABS.map((t) => (
              <button key={t} onClick={() => setTab(t)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-[13.5px] transition ${tab === t ? "bg-brand-wash dark:bg-night-soft text-brand-deep dark:text-night-ink font-medium" : "text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft"}`}>
                {t}
              </button>
            ))}
          </nav>

          {/* Right content */}
          <div className="flex-1 overflow-y-auto p-5 text-sm">
            {!data ? <div className="text-ink-faint">Loading…</div> : (
              <>
                {tab === "Provider" && (
                  <div className="space-y-5">
                    <Section title="Choose a provider" hint="Pick the brain. Keys are stored in .env; changes take effect on restart.">
                      <div className="grid grid-cols-1 gap-2">
                        {providers.map((p) => (
                          <ProviderCard key={p.type} p={p} active={activeType === p.type}
                                        onSelect={() => selectProvider(p)}
                                        keyValue={env[p.key_env] ?? ""}
                                        onKey={(v) => p.key_env && setEnv((e) => ({ ...e, [p.key_env]: v }))} />
                        ))}
                      </div>
                    </Section>

                    <Section title="Active provider" hint="Settings for the selected provider.">
                      <Field label="Base URL (OpenAI-compatible)">
                        <Input value={cur("provider.base_url", "")} onChange={(v) => setC("provider.base_url", v)} placeholder="https://…/v1" />
                      </Field>
                      <Field label="Model">
                        <div className="flex gap-2">
                          <select value={models.includes(cur("provider.model", "")) ? cur("provider.model", "") : ""}
                                  onChange={(e) => setC("provider.model", e.target.value)}
                                  className="flex-1 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2 py-1.5 outline-none focus:border-brand">
                            <option value="">{loadingModels ? "fetching models…" : (models.length ? "— choose —" : "no models found")}</option>
                            {models.map((m) => <option key={m} value={m}>{m}</option>)}
                          </select>
                          <button onClick={() => loadModels(activeType, cur("provider.base_url", ""))}
                                  title="Refresh models" className="px-2.5 rounded-lg border border-line dark:border-night-line hover:bg-paper-soft dark:hover:bg-night-soft">↻</button>
                        </div>
                      </Field>
                      <Field label="…or type a model">
                        <Input value={cur("provider.model", "")} onChange={(v) => setC("provider.model", v)} placeholder="model id" />
                      </Field>
                      <Field label="Max tokens"><Input type="number" value={cur("provider.max_tokens", 4096)} onChange={(v) => setC("provider.max_tokens", parseInt(v || "0", 10))} /></Field>
                      <Field label={`Temperature (${cur("provider.temperature", 0.3)})`}>
                        <input type="range" min="0" max="1" step="0.05" value={cur("provider.temperature", 0.3)}
                               onChange={(e) => setC("provider.temperature", parseFloat(e.target.value))} className="w-full" />
                      </Field>
                      <Field label="Timeout (s)"><Input type="number" value={cur("provider.timeout_s", 60)} onChange={(v) => setC("provider.timeout_s", parseInt(v || "0", 10))} /></Field>
                    </Section>
                  </div>
                )}

                {tab === "Behavior" && (
                  <Section title="Behavior">
                    <Field label="Default mode"><Select value={cur("conversation.default_mode", "agent")} onChange={(v) => setC("conversation.default_mode", v)} options={["agent", "chat"]} /></Field>
                    <Toggle label="Auto mode — run tools (incl. shell) without asking" checked={!!cur("conversation.auto_approve", false)} onChange={(v) => setC("conversation.auto_approve", v)} />
                    <Field label="Tool step limit (0 = unlimited)"><Input type="number" value={cur("conversation.tool_loop_limit", 0)} onChange={(v) => setC("conversation.tool_loop_limit", parseInt(v || "0", 10))} /></Field>
                    <Field label="Memory nudge every N turns (0 = off)"><Input type="number" value={cur("conversation.memory_nudge_every", 6)} onChange={(v) => setC("conversation.memory_nudge_every", parseInt(v || "0", 10))} /></Field>
                    <Field label="History turns kept"><Input type="number" value={cur("conversation.max_history_turns", 12)} onChange={(v) => setC("conversation.max_history_turns", parseInt(v || "0", 10))} /></Field>
                  </Section>
                )}

                {tab === "Persona" && (
                  <Section title="Persona" hint="Which personality FRIDAY loads from personas/<id>.yaml.">
                    <Field label="Persona"><Input value={cur("persona", "friday_core")} onChange={(v) => setC("persona", v)} /></Field>
                  </Section>
                )}

                {tab === "Browser" && (
                  <Section title="Browser & media">
                    <Field label="Preferred browser"><Select value={cur("browser.preferred", "auto")} onChange={(v) => setC("browser.preferred", v)} options={["auto", "chrome", "chromium", "brave", "edge", "vivaldi", "opera", "firefox"]} /></Field>
                    <Toggle label="Reuse my real browser profile (sign-ins)" checked={!!cur("browser.use_system_profile", true)} onChange={(v) => setC("browser.use_system_profile", v)} />
                    <Toggle label="Open videos fullscreen" checked={!!cur("browser.fullscreen", true)} onChange={(v) => setC("browser.fullscreen", v)} />
                    <Toggle label="Headless (no visible window)" checked={!!cur("browser.headless", false)} onChange={(v) => setC("browser.headless", v)} />
                  </Section>
                )}

                {tab === "Voice" && (
                  <Section title="Voice" hint="Server-side Piper TTS / local STT. (The per-message read-aloud button uses your browser's own TTS and is always available.)">
                    <Toggle label="Enable Piper voice" checked={!!cur("voice.enabled", true)} onChange={(v) => setC("voice.enabled", v)} />
                  </Section>
                )}

                {tab === "Telegram" && (
                  <Section title="Telegram" hint="Chat with FRIDAY from your phone. Stored in .env.">
                    <Field label="Bot token"><Input type="password" placeholder={data.env_set?.FRIDAY_TELEGRAM_TOKEN ? "•••••• (set)" : "not set"} value={env.FRIDAY_TELEGRAM_TOKEN ?? ""} onChange={(v) => setEnv((e) => ({ ...e, FRIDAY_TELEGRAM_TOKEN: v }))} /></Field>
                    <Field label="Chat id"><Input placeholder={data.env_set?.FRIDAY_TELEGRAM_CHAT_ID ? "(set)" : "not set"} value={env.FRIDAY_TELEGRAM_CHAT_ID ?? ""} onChange={(v) => setEnv((e) => ({ ...e, FRIDAY_TELEGRAM_CHAT_ID: v }))} /></Field>
                    <Toggle label="Reply to inbound Telegram messages" checked={!!cur("comms.inbound_enabled", true)} onChange={(v) => setC("comms.inbound_enabled", v)} />
                  </Section>
                )}

                {tab === "Appearance" && (
                  <Section title="Appearance & system">
                    <Toggle label="Dark theme" checked={theme === "dark"} onChange={onThemeToggle} />
                    <Field label="Log level"><Select value={cur("logging.level", "info")} onChange={(v) => setC("logging.level", v)} options={["debug", "info", "warning", "error"]} /></Field>
                  </Section>
                )}

                {tab === "Memory" && (
                  <Section title="Memory" hint="Erase stored memory. This cannot be undone.">
                    <div className="flex flex-wrap gap-2">
                      {["facts", "conversations", "notes", "all"].map((s) => (
                        <button key={s} onClick={() => wipe(s)}
                                className="px-3 py-1.5 rounded-lg border border-line dark:border-night-line hover:bg-brand-wash dark:hover:bg-night-soft capitalize">Clear {s}</button>
                      ))}
                    </div>
                    {cleared && <div className="mt-2 text-brand-deep text-[13px]">Cleared {cleared}.</div>}
                  </Section>
                )}
              </>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-line dark:border-night-line">
          {saved && <span className="text-brand-deep text-[13px] mr-auto">Saved — restart to apply provider/key changes.</span>}
          <button onClick={onClose} className="px-4 py-2 rounded-lg text-ink-soft dark:text-night-ink hover:bg-paper-soft dark:hover:bg-night-soft">Close</button>
          <button onClick={save} className="px-4 py-2 rounded-lg bg-brand text-white hover:bg-brand-deep">Save</button>
        </div>
      </div>
    </div>
  );
}

function ProviderCard({ p, active, onSelect, keyValue, onKey }) {
  const badge = p.key_set ? ["Key set", "text-emerald-600 dark:text-emerald-400"]
    : p.needs_key ? ["No key", "text-brand-deep"]
    : ["No key needed", "text-ink-faint dark:text-night-faint"];
  return (
    <div className={`rounded-xl border p-3 transition ${active ? "border-brand bg-brand-wash/50 dark:bg-night-soft" : "border-line dark:border-night-line"}`}>
      <label className="flex items-center gap-2.5 cursor-pointer">
        <input type="radio" checked={active} onChange={onSelect} className="accent-brand" />
        <span className="font-medium">{p.label}</span>
        <span className="text-[11px] font-mono px-1.5 py-0.5 rounded bg-paper-soft dark:bg-night">{p.type}</span>
        <span className={`ml-auto text-[12px] ${badge[1]}`}>● {badge[0]}</span>
      </label>
      {p.key_env && (
        <div className="mt-2 flex items-center gap-2 pl-6">
          <span className="text-[12px] text-ink-faint dark:text-night-faint w-28 truncate" title={p.key_env}>{p.key_env}</span>
          <input type="password" value={keyValue} onChange={(e) => onKey(e.target.value)}
                 placeholder={p.key_set ? "•••••• (set) — type to replace" : "paste API key"}
                 className="flex-1 rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2.5 py-1.5 text-[13px] outline-none focus:border-brand" />
        </div>
      )}
    </div>
  );
}

const Section = ({ title, hint, children }) => (
  <div>
    <div className="font-medium mb-1">{title}</div>
    {hint && <div className="text-[12px] text-ink-faint dark:text-night-faint mb-3">{hint}</div>}
    <div className="space-y-2.5">{children}</div>
  </div>
);
const Field = ({ label, children }) => (
  <label className="flex items-center justify-between gap-3">
    <span className="text-ink-soft dark:text-night-faint">{label}</span>
    <div className="w-1/2">{children}</div>
  </label>
);
const Input = ({ value, onChange, ...p }) => (
  <input {...p} value={value} onChange={(e) => onChange(e.target.value)}
         className="w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-3 py-1.5 outline-none focus:border-brand" />
);
const Select = ({ value, onChange, options }) => (
  <select value={value} onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-lg border border-line dark:border-night-line bg-paper dark:bg-night px-2 py-1.5 outline-none focus:border-brand">
    {options.map((o) => <option key={o} value={o}>{o}</option>)}
  </select>
);
const Toggle = ({ label, checked, onChange }) => (
  <label className="flex items-center justify-between gap-3 cursor-pointer">
    <span className="text-ink-soft dark:text-night-faint">{label}</span>
    <button type="button" onClick={() => onChange(!checked)}
            className={`h-6 w-11 rounded-full transition relative shrink-0 ${checked ? "bg-brand" : "bg-line dark:bg-night-line"}`}>
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition ${checked ? "left-[22px]" : "left-0.5"}`} />
    </button>
  </label>
);
