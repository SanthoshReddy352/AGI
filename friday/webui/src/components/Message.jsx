import Logo from "./Logo.jsx";
import Markdown from "./Markdown.jsx";
import ReadAloud from "./ReadAloud.jsx";

const fmtTime = (at) => {
  if (!at) return "";
  try { return new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
  catch { return ""; }
};

// claude.ai-style: user messages in a soft bubble on the right; assistant
// messages as full-width rich text (no bubble), with an "F" avatar. Each shows time.
export default function Message({ role, content, tools, attachments, at }) {
  const isUser = role === "user";
  const isError = role === "error";
  const time = fmtTime(at);

  if (isUser) {
    return (
      <div className="flex flex-col items-end animate-rise">
        <div className="max-w-[80%] rounded-2xl rounded-br-md bg-brand-wash dark:bg-night-soft border border-line dark:border-night-line px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap">
          {content}
          {attachments?.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {attachments.map((a, i) => (
                <span key={i} className="text-[12px] bg-paper dark:bg-night px-2 py-0.5 rounded-md border border-line dark:border-night-line text-ink-soft dark:text-night-faint">
                  📎 {a.name}
                </span>
              ))}
            </div>
          )}
        </div>
        {time && <div className="text-[10.5px] text-ink-faint dark:text-night-faint mt-1 mr-1">{time}</div>}
      </div>
    );
  }

  return (
    <div className="flex gap-3 animate-rise">
      <div className="mt-0.5 h-7 w-7 shrink-0 grid place-items-center"><Logo size={26} /></div>
      <div className="flex-1 min-w-0">
        {isError ? (
          <div className="text-[15px] text-brand-deep bg-brand-wash border border-brand-soft/50 rounded-xl px-3 py-2">
            {content}
          </div>
        ) : content ? (
          <Markdown>{content}</Markdown>
        ) : (
          <span className="inline-block h-4 w-2 bg-ink-faint animate-blink rounded-sm" />
        )}
        <div className="mt-2 flex items-center gap-2 text-[10.5px] text-ink-faint dark:text-night-faint">
          {content && !isError && <ReadAloud text={content} />}
          {time && <span>{time}</span>}
          {tools?.length > 0 && <span>· used: {tools.join(", ")}</span>}
        </div>
      </div>
    </div>
  );
}
