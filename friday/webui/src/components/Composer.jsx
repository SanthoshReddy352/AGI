import { useRef, useState } from "react";
import { uploadFile } from "../api.js";

const SLASH_COMMANDS = [
  { cmd: "/new", desc: "Start a new chat" },
  { cmd: "/clear", desc: "Wipe FRIDAY's memory" },
  { cmd: "/agent", desc: "Switch to agent mode (tools + skills)" },
  { cmd: "/chat", desc: "Switch to chat mode (talk only)" },
  { cmd: "/help", desc: "Show available commands" },
];
const BANG_HINT = [{ cmd: "!<command>", desc: "Run a shell command, e.g. !df -h" }];

// claude.ai-style composer: rounded card with attach, a textarea, a mode pill,
// and a send button that becomes a stop button while a turn is running.
export default function Composer({ onSend, onStop, busy, mode, setMode, autoFocus, name = "FRIDAY" }) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [recording, setRecording] = useState(false);
  const fileRef = useRef(null);
  const recRef = useRef(null);
  const sttSupported = typeof window !== "undefined" && ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  function submit() {
    if (busy) return;
    if (!text.trim() && attachments.length === 0) return;
    onSend(text, attachments);
    setText("");
    setAttachments([]);
  }

  async function onPick(e) {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setUploading(true);
    for (const f of files) {
      const r = await uploadFile(f);
      if (r?.ok) setAttachments((a) => [...a, { name: r.name, path: r.path }]);
    }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  }

  // Browser-native speech-to-text (Web Speech API) — dictates into the textarea.
  function record() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;
    if (recRef.current) { recRef.current.stop(); return; }
    const rec = new SR();
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => {
      const said = e.results[0][0].transcript;
      setText((v) => (v ? v + " " + said : said));
    };
    rec.onend = () => { setRecording(false); recRef.current = null; };
    rec.onerror = () => { setRecording(false); recRef.current = null; };
    recRef.current = rec;
    setRecording(true);
    rec.start();
  }

  // Command hints: show when the message begins with / or !
  let hints = null;
  if (text.startsWith("/")) {
    hints = SLASH_COMMANDS.filter((c) => c.cmd.startsWith(text.split(" ")[0]));
  } else if (text.startsWith("!")) {
    hints = BANG_HINT;
  }

  return (
    <div className="relative rounded-2xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel shadow-soft">
      {hints && hints.length > 0 && (
        <div className="absolute bottom-full mb-2 left-0 right-0 rounded-xl border border-line dark:border-night-line bg-paper-panel dark:bg-night-panel shadow-pop overflow-hidden">
          {hints.map((h) => (
            <button key={h.cmd} type="button"
                    onClick={() => { if (h.cmd.includes("<")) return; setText(h.cmd + " "); }}
                    className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-paper-soft dark:hover:bg-night-soft">
              <span className="font-mono text-[13px] text-brand-deep">{h.cmd}</span>
              <span className="text-[12.5px] text-ink-soft dark:text-night-faint">{h.desc}</span>
            </button>
          ))}
        </div>
      )}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3 pt-3">
          {attachments.map((a, i) => (
            <span key={i} className="flex items-center gap-1.5 text-[12px] bg-paper-soft dark:bg-night-soft border border-line dark:border-night-line rounded-md px-2 py-1">
              📎 {a.name}
              <button onClick={() => setAttachments((x) => x.filter((_, j) => j !== i))}
                      className="text-ink-faint hover:text-ink">×</button>
            </span>
          ))}
        </div>
      )}
      <div className="flex items-end gap-2 p-2.5">
        <input ref={fileRef} type="file" multiple className="hidden" onChange={onPick} />
        <button title="Attach a document" onClick={() => fileRef.current?.click()}
                className="h-9 w-9 grid place-items-center rounded-lg text-ink-soft dark:text-night-faint hover:bg-paper-soft dark:hover:bg-night-soft">
          {uploading ? <span className="text-xs">…</span> : <PaperclipIcon />}
        </button>
        <textarea
          value={text}
          autoFocus={autoFocus}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          rows={1}
          placeholder={mode === "chat" ? `Chat with ${name}…` : `Ask ${name} to do something…`}
          className="flex-1 resize-none bg-transparent outline-none px-1.5 py-2 text-[15px] placeholder:text-ink-faint dark:placeholder:text-night-faint max-h-44"
        />
        <ModePill mode={mode} setMode={setMode} />
        {sttSupported && (
          <button title={recording ? "Stop dictation" : "Dictate (browser speech-to-text)"} onClick={record}
                  className={`h-9 w-9 grid place-items-center rounded-lg hover:bg-paper-soft dark:hover:bg-night-soft ${recording ? "text-brand animate-pulse" : "text-ink-soft dark:text-night-faint"}`}>
            <MicIcon />
          </button>
        )}
        {busy ? (
          <button title="Stop" onClick={onStop}
                  className="h-9 w-9 grid place-items-center rounded-lg bg-ink dark:bg-night-ink text-paper dark:text-night">
            <StopIcon />
          </button>
        ) : (
          <button title="Send" onClick={submit} disabled={!text.trim() && attachments.length === 0}
                  className="h-9 w-9 grid place-items-center rounded-lg bg-brand text-white disabled:opacity-30 hover:bg-brand-deep transition">
            <SendIcon />
          </button>
        )}
      </div>
    </div>
  );
}

function ModePill({ mode, setMode }) {
  return (
    <div className="flex items-center rounded-lg bg-paper-soft dark:bg-night-soft p-0.5 text-[12px] font-medium">
      {["agent", "chat"].map((m) => (
        <button key={m} onClick={() => setMode(m)}
                className={`px-2.5 py-1 rounded-md capitalize transition ${mode === m ? "bg-paper-panel dark:bg-night-panel text-ink dark:text-night-ink shadow-soft" : "text-ink-faint dark:text-night-faint"}`}>
          {m}
        </button>
      ))}
    </div>
  );
}

const PaperclipIcon = () => (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>);
const MicIcon = () => (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" /></svg>);
const SendIcon = () => (<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m22 2-7 20-4-9-9-4Z" /><path d="M22 2 11 13" /></svg>);
const StopIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>);
