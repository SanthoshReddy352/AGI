import Link from "next/link";
import { DocHeader, Callout, PrevNext, FactGrid } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Telegram & remote control",
  description: "Drive FRIDAY's full control surface from your phone — chat, shell, slash commands, file Q&A, voice notes, and approval gates.",
};

export default function Telegram() {
  return (
    <>
      <DocHeader
        eyebrow="Control"
        title="Telegram & remote control"
        intro="Connect a Telegram bot and FRIDAY becomes fully remote-controllable. Not just chat — the entire control surface: the deterministic router, slash commands, the interactive shell, document Q&A, voice notes, and human-in-the-loop approvals."
      />

      <h2 id="setup">Setup</h2>
      <p>Tokens live in OS environment variables, never in <code>config.yaml</code>.</p>
      <ol>
        <li>Create a bot with <a href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a> and copy the token.</li>
        <li>Message your new bot once, then read your chat id (any “get my id” bot works, or check <code>getUpdates</code>).</li>
        <li>Set the two environment variables and restart FRIDAY.</li>
      </ol>
      <CodeBlock label=".env">{`FRIDAY_TELEGRAM_TOKEN=123456:ABC-your-bot-token
FRIDAY_TELEGRAM_CHAT_ID=987654321

# Optional outbound-only notifications channel
FRIDAY_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...`}</CodeBlock>
      <p>
        On boot you&apos;ll get a <em>“FRIDAY is online and ready.”</em> message, and the bot starts
        long-polling for your messages. Only your configured chat id is accepted — messages from any
        other chat are ignored.
      </p>

      <h2 id="surface">What you can do remotely</h2>
      <p>
        Inbound messages run through <code>app.process_input(text, source="telegram")</code> — the
        exact same pipeline as the terminal, so the full prefix grammar from{" "}
        <Link href="/docs/commands">Commands &amp; shell</Link> works from your phone:
      </p>
      <FactGrid
        items={[
          ["plain text", "Full turn pipeline — router, capabilities, memory — replies in chat"],
          ["/ slash commands", "All 13, with native Telegram autocomplete via setMyCommands"],
          ["! shell commands", "Run real commands on your machine, remotely"],
          ["> follow-ups", "Answer sudo / y-n prompts from the chat"],
          ["document upload", "PDF · DOCX · PPTX · XLSX · MD · TXT · HTML · CSV → RAG"],
          ["voice notes", "Transcribed by the local Whisper STT, then processed"],
        ]}
      />

      <h2 id="shell-remote">Shell, from your phone</h2>
      <p>
        Because the <code>!</code> shell is just another input prefix, you can drive a full
        interactive session over Telegram — including password prompts, which FRIDAY relays and
        accepts via <code>&gt;</code> (input is not echoed back into the chat):
      </p>
      <CodeBlock label="telegram">{`you  →  !sudo systemctl restart nginx
bot  ←  [sudo] password for you:
        Awaiting password — reply with > <password>
you  →  > ••••••••
bot  ←  ✓ nginx restarted · [exit 0]`}</CodeBlock>
      <Callout tone="warn" title="Lock the gate before you leave">
        Remote shell is powerful. The shell respects FRIDAY&apos;s screen-lock PIN gate — lock it
        and <code>!</code> is refused remotely until you <code>/unlock &lt;pin&gt;</code>. Treat your
        bot token like a key to your machine.
      </Callout>

      <h2 id="files">Documents &amp; voice notes</h2>
      <p>
        Drop a supported file into the chat and FRIDAY downloads it, loads it into session RAG, and
        confirms — then any caption (or your next message) is answered against that document. Send a
        voice note and it&apos;s transcribed through the same local STT used for the wake-word path,
        then handled as a normal turn. No cloud transcription.
      </p>

      <h2 id="approvals">Approval gates</h2>
      <p>
        Sensitive workflows (security tooling, destructive actions) can request a yes/no round-trip.
        FRIDAY sends the question and <strong>blocks</strong> until you reply <code>approve</code> /{" "}
        <code>deny</code> / <code>cancel</code> (or natural equivalents like “yes”, “stop”). The
        reply is intercepted before routing, so a bare “yes” resolves the gate instead of becoming a
        new query.
      </p>
      <Callout tone="note" title="Refuse-by-default">
        If the channel is offline when an approval is requested, the answer is <code>deny</code> —
        security workflows never run unattended. A 3-minute timeout also resolves to no-action.
      </Callout>

      <h2 id="ux">Live chat UX</h2>
      <ul>
        <li><strong>Typing indicator</strong> — the “FRIDAY is typing…” status stays alive while it works.</li>
        <li><strong>In-place answer</strong> — a 💭 placeholder bubble is edited into the final response, so you see it morph rather than getting a second message.</li>
        <li><strong>Auto-chunking</strong> — replies over Telegram&apos;s 4096-char limit are split on sentence boundaries.</li>
        <li><strong>Markdown → Telegram HTML</strong> — <code>**bold**</code>, <code>*italic*</code>, and <code>`code`</code> render natively.</li>
      </ul>

      <h2 id="proactive">Proactive notifications</h2>
      <p>
        Telegram and Discord aren&apos;t only inbound. FRIDAY pushes events to you when you&apos;re
        away — wired through the EventBus in <code>modules/comms/plugin.py</code>:
      </p>
      <FactGrid
        items={[
          ["⏰ reminders", "reminder_fired → a chat ping when a reminder is due"],
          ["🌅 goal check-ins", "morning check-in and evening review prompts"],
          ["⚠️ goal at risk", "a nudge when a tracked goal needs attention"],
          ["🔔 triggers", "automation triggers that opt in with notify_remote"],
        ]}
      />
      <p>
        Discord is outbound-only (a webhook URL — no bot account needed); Telegram is the full
        two-way channel.
      </p>

      <PrevNext current="/docs/telegram" />
    </>
  );
}
