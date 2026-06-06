import Link from "next/link";
import { DocHeader, Callout, PrevNext } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Getting started",
  description: "Clone, run setup, and say your first command to FRIDAY.",
};

const GITHUB = "https://github.com/SanthoshReddy352/Friday_Linux";

export default function GettingStarted() {
  return (
    <>
      <DocHeader
        eyebrow="Introduction"
        title="Getting started"
        intro="Three steps: clone the repo, run one setup script, and start talking. The setup script installs dependencies, the Piper TTS voice, downloads the default models, and bootstraps your .env."
      />

      <h2 id="requirements">Requirements</h2>
      <ul>
        <li><strong>OS</strong> — Ubuntu 22.04+ / Debian 12+ / Kali, or Windows 10 21H2+ / Windows 11.</li>
        <li><strong>Python</strong> — 3.10 to 3.13 (3.11 recommended).</li>
        <li><strong>RAM</strong> — 8 GB minimum, 16 GB recommended.</li>
        <li><strong>Disk</strong> — about 10 GB for models and cache.</li>
        <li><strong>GPU</strong> — optional. llama.cpp and faster-whisper auto-use CUDA when present.</li>
      </ul>

      <h2 id="install">1. Clone &amp; run setup</h2>
      <p>On Linux:</p>
      <CodeBlock label="bash · linux">{`git clone ${GITHUB}.git
cd Friday_Linux
chmod +x setup.sh
./setup.sh
source .venv/bin/activate
python main.py`}</CodeBlock>

      <p>On Windows (PowerShell):</p>
      <CodeBlock label="powershell · windows">{`git clone ${GITHUB}.git
cd Friday_Linux
.\\setup.ps1
.\\.venv\\Scripts\\Activate.ps1
python main.py`}</CodeBlock>

      <Callout tone="note" title="Idempotent setup">
        The setup scripts skip any step whose output is already on disk, so re-running is safe.
        A failed or blank model download is reported, not fatal. See{" "}
        <Link href="/docs/installation">Installation</Link> for the fully-manual path and
        troubleshooting.
      </Callout>

      <h2 id="first-words">2. Say your first words</h2>
      <p>
        FRIDAY greets you on launch. Trigger it with the wake word or just type in the terminal UI.
        Try these — each maps to a real capability through the deterministic router:
      </p>
      <CodeBlock label="say to friday">{`Hey Friday — set brightness to 60.
What's on my calendar today?
Find the file called design final report.
Summarize this PDF.
Take a screenshot and explain it.
What's the weather in Mumbai?`}</CodeBlock>

      <Callout tone="tip" title="No microphone? No problem.">
        Launch in text mode with <code>python main.py --text</code> and type your commands. Voice
        is optional; the whole routing pipeline works the same either way.
      </Callout>

      <h2 id="modes">3. Choose how you run it</h2>
      <ul>
        <li><code>python main.py</code> — default terminal UI (voice + text).</li>
        <li><code>python main.py --text</code> — force text-only mode.</li>
        <li><code>python main.py --gui</code> — the PyQt6 HUD dashboard.</li>
        <li><code>python main.py --verbose</code> — debug logging.</li>
      </ul>

      <h2 id="next">Where to go next</h2>
      <ul>
        <li><Link href="/docs/how-it-works">How routing works</Link> — why the deterministic router matters.</li>
        <li><Link href="/docs/capabilities">Capabilities</Link> — the full list of what FRIDAY can do.</li>
        <li><Link href="/docs/adding-tools">Add a new tool</Link> — teach FRIDAY a new skill.</li>
      </ul>

      <PrevNext current="/docs/getting-started" />
    </>
  );
}
