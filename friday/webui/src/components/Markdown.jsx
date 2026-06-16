import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";

// Inline diagram/image (render_diagram, fetch_image) — framed, capped, and
// click-to-open full size. A dead link (404 from a failed/fabricated render)
// degrades to a quiet "unavailable" chip instead of the browser's broken icon.
function InlineImage(props) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <span className="inline-flex items-center gap-1.5 my-1 px-2.5 py-1.5 rounded-lg border border-dashed border-line dark:border-night-line text-[12.5px] text-ink-faint dark:text-night-faint">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="9" cy="9" r="2" /><path d="m21 15-3.5-3.5L9 20" /><path d="m2 2 20 20" /></svg>
        {props.alt || "image"} — unavailable
      </span>
    );
  }
  return (
    <a href={props.src} target="_blank" rel="noreferrer noopener" className="block my-2">
      <img {...props} loading="lazy" onError={() => setBroken(true)}
           className="max-w-full max-h-[460px] rounded-xl border border-line dark:border-night-line bg-white" />
    </a>
  );
}

// Renders the model's markdown as clean rich text (no raw * or ### shown).
// Links open in a new tab; code gets syntax highlighting; GFM tables/lists work.
export default function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          a: ({ node, ...props }) => <a target="_blank" rel="noreferrer noopener" {...props} />,
          img: ({ node, ...props }) => <InlineImage {...props} />,
        }}
      >
        {children || ""}
      </ReactMarkdown>
    </div>
  );
}
