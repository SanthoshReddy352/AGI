import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Commands & shell",
  description: "FRIDAY's input prefix grammar — slash commands, the ! interactive shell, and > stdin follow-ups.",
};

const slash = [
  ["/new", "Reset the conversation and start a new session"],
  ["/clear", "Alias for /new"],
  ["/web <query>", "Web search — returns result links"],
  ["/quick <question>", "Instant web-backed answer in chat, nothing saved"],
  ["/fast <topic>", "Fast research — ~2-minute latest-info summary"],
  ["/deep <topic>", "Deep research — heavy multi-source briefing, saved to disk"],
  ["/research <topic>", "Hand off to the research agent"],
  ["/fetch <url>", "Fetch a URL as plain text"],
  ["/crawl <url> [what to look for]", "Crawl a URL with instructions"],
  ["/screenshot", "Take a full-screen screenshot"],
  ["/voice on|off|status", "Toggle voice mode"],
  ["/lock", "Lock the computer screen (OS session lock)"],
  ["/unlock", "How to unlock the screen / shell PIN gate"],
  ["/help", "List every slash command"],
];

export default function Commands() {
  return (
    <>
      <DocHeader
        eyebrow="Control"
        title="Commands & shell"
        intro="Every input surface — the terminal UI, the HUD, and the Telegram bot — understands the same prefix grammar. The first character of your message decides how it's handled, before the router ever runs."
      />

      <h2 id="grammar">The prefix grammar</h2>
      <p>
        FRIDAY short-circuits four input shapes in <code>_maybe_handle_input_prefix()</code> before
        the turn orchestrator. This keeps commands deterministic and the LLM out of the hot path.
      </p>
      <CodeBlock label="four prefixes">{`(no prefix)   set brightness to 60        → deterministic router (voice or text)
/            /deep RISC-V vs ARM         → slash dispatcher (direct to capability)
!            !sudo systemctl restart x   → interactive PTY shell
>            > my-password               → stdin to the running shell command`}</CodeBlock>

      <h2 id="slash">Slash commands</h2>
      <p>
        A <code>/command</code> is dispatched directly by <code>core/slash_commands.py</code> — no
        intent recognition, no planner. On Telegram these populate the native{" "}
        <code>/</code>-autocomplete menu (pushed via <code>setMyCommands</code>), so the registry is
        the single source of truth.
      </p>
      <div className="code-scroll my-6 overflow-x-auto rounded-xl border border-line">
        <table className="w-full min-w-[420px] text-left text-sm">
          <thead className="bg-ink-700/50 text-white/50">
            <tr>
              <th className="px-4 py-2.5 font-mono text-xs font-medium">command</th>
              <th className="px-4 py-2.5 font-medium">what it does</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {slash.map(([c, d]) => (
              <tr key={c} className="hover:bg-white/[0.02]">
                <td className="whitespace-nowrap px-4 py-2.5 font-mono text-[13px] text-glow-cyan">{c}</td>
                <td className="px-4 py-2.5 text-white/65">{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Callout tone="note" title="Pure-state slashes always work">
        <code>/new</code>, <code>/help</code>, <code>/lock</code>, and <code>/unlock</code> run even
        when the screen is locked, because they have to. Slash commands that hit a capability are
        still gated by the executor&apos;s lock + consent checks.
      </Callout>

      <h2 id="shell">The <code>!</code> interactive shell</h2>
      <p>
        Prefix any line with <code>!</code> to run it as a real shell command. On Linux/macOS it runs
        under a <strong>pseudo-terminal (PTY)</strong>, so commands that need a TTY — <code>sudo</code>{" "}
        password prompts, <code>ssh</code>, <code>read</code>, <code>passwd</code> — actually work.
      </p>
      <ul>
        <li><strong>Bash by default</strong> — uses <code>/bin/bash</code> (not dash), so <code>source</code>, <code>[[ ]]</code>, arrays, and process substitution work.</li>
        <li><strong>venv-aware</strong> — if the project has a <code>.venv/</code>, it&apos;s on <code>PATH</code> automatically, so <code>!python script.py</code> uses the project interpreter.</li>
        <li><strong>Bounded</strong> — a 5-minute wall-clock cap per command and an output cap prevent runaway buffering.</li>
        <li><strong>Windows</strong> — PTYs are POSIX-only; Windows degrades to a non-interactive run and rejects <code>&gt;</code> follow-ups with a clear message.</li>
      </ul>

      <h2 id="followups">Interactive follow-ups with <code>&gt;</code></h2>
      <p>
        When a command is waiting on input, FRIDAY tells you and keeps the process alive. Reply with a{" "}
        <code>&gt;</code>-prefixed line to pipe it to the command&apos;s stdin:
      </p>
      <CodeBlock label="interactive shell session">{`!sudo apt install brightnessctl
  [sudo] password for you:        ← FRIDAY: "Awaiting password — reply with > …"
> ••••••••                        ← piped to stdin (not echoed)
  Do you want to continue? [Y/n]
> y                               ← piped to the apt prompt
  ✓ done · [exit 0]`}</CodeBlock>
      <Callout tone="warn" title="A stray reply cancels — it never leaks to chat">
        While a shell session is alive, any message that does <strong>not</strong> start with{" "}
        <code>&gt;</code> cancels the running command instead of being interpreted by the LLM. That&apos;s
        the safety rule that stops a casual &quot;yes&quot; from being read as a sudo password or a
        chat message.
      </Callout>

      <h2 id="security">Security gating</h2>
      <p>
        The shell is gated by the screen lock — while FRIDAY&apos;s PIN gate is locked,{" "}
        <code>!</code> is refused with <em>&quot;Shell access is locked. Run /unlock &lt;pin&gt; first.&quot;</em>{" "}
        This matters most for the remote case: the same shell is reachable from Telegram, so the lock
        is what keeps a remote session from running arbitrary commands. See{" "}
        <Link href="/docs/telegram">Telegram &amp; remote</Link>.
      </p>

      <PrevNext current="/docs/commands" />
    </>
  );
}
