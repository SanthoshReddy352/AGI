import Link from "next/link";
import { DocHeader, Callout, PrevNext, FactGrid } from "@/components/doc-ui";
import CodeBlock from "@/components/CodeBlock";

export const metadata = {
  title: "Installation",
  description: "Install FRIDAY on Linux or Windows — models, requirements, and troubleshooting.",
};

const GITHUB = "https://github.com/SanthoshReddy352/Friday_Linux";

export default function Installation() {
  return (
    <>
      <DocHeader
        eyebrow="Introduction"
        title="Installation"
        intro="FRIDAY ships a setup script for each platform. They install system dependencies, the Piper TTS binary, download the default GGUF / Whisper models, and write a starter .env."
      />

      <h2 id="linux">Linux</h2>
      <CodeBlock label="bash · linux">{`git clone ${GITHUB}.git
cd Friday_Linux
chmod +x setup.sh
./setup.sh            # deps, Piper TTS, default models, .env
source .venv/bin/activate
python main.py`}</CodeBlock>
      <p>
        The Linux script also offers an optional autostart prompt and installs optional screenshot
        / window tools when available (<code>wmctrl</code>, <code>xdotool</code>, <code>grim</code>,{" "}
        <code>spectacle</code>, <code>scrot</code>, <code>maim</code>). Full walkthrough:{" "}
        <a href={`${GITHUB}/blob/main/SETUP_GUIDE.md`} target="_blank" rel="noreferrer">SETUP_GUIDE.md</a>.
      </p>

      <h2 id="windows">Windows</h2>
      <CodeBlock label="powershell · windows">{`git clone ${GITHUB}.git
cd Friday_Linux
.\\setup.ps1          # deps, Piper for Windows, default models, .env
.\\.venv\\Scripts\\Activate.ps1
python main.py`}</CodeBlock>
      <p>The PowerShell script accepts flags:</p>
      <ul>
        <li><code>-SkipModels</code> — don&apos;t download model files (bring your own).</li>
        <li><code>-SkipPlaywright</code> — skip browser-automation runtime.</li>
        <li><code>-Force</code> — re-run steps even if outputs exist.</li>
      </ul>
      <Callout tone="warn" title="Windows first run">
        You may need to relax the PowerShell execution policy and install Microsoft C++ Build Tools
        for the native llama.cpp build. The dedicated{" "}
        <a href={`${GITHUB}/blob/main/SETUP_GUIDE_WINDOWS.md`} target="_blank" rel="noreferrer">SETUP_GUIDE_WINDOWS.md</a>{" "}
        covers execution policy, env-var scope, build tools, long-path issues, and audio device
        discovery.
      </Callout>

      <h2 id="models">Default models</h2>
      <p>Setup downloads a quantized local stack. Override the chat/tool downloads with the env vars below, or drop your own <code>.gguf</code> files into <code>models/</code>.</p>
      <FactGrid
        items={[
          ["chat", "Qwen3.5-0.8B-Q4_K_M.gguf · ~533 MB"],
          ["tool / planner", "Qwen3.5-4B-Q4_K_M.gguf · ~2.7 GB"],
          ["speech-to-text", "faster-whisper base.en · ~140 MB"],
          ["vision", "SmolVLM2-2.2B-Instruct-Q4_K_M.gguf · ~1.7 GB"],
          ["embeddings", "all-MiniLM-L6-v2 + ms-marco reranker · ~120 MB"],
          ["overrides", "FRIDAY_CHAT_MODEL_URL · FRIDAY_TOOL_MODEL_URL"],
        ]}
      />

      <h2 id="env">Environment &amp; secrets</h2>
      <p>
        Runtime behaviour lives in <code>config.yaml</code>; secrets and machine overrides go in{" "}
        <code>.env</code> (copied from <code>.env.example</code> at setup). A couple you may want:
      </p>
      <CodeBlock label=".env">{`# Required on both OSes for the wake word
FRIDAY_PORCUPINE_KEY=your-picovoice-access-key

# Optional model download overrides
FRIDAY_CHAT_MODEL_URL=https://...
FRIDAY_TOOL_MODEL_URL=https://...`}</CodeBlock>

      <h2 id="verify">Verify it runs</h2>
      <CodeBlock label="bash">{`python main.py --text     # text-only smoke test
# then type:  set brightness to 60`}</CodeBlock>
      <p>
        If you see a brightness change (or a clear &quot;capability not available&quot; on
        unsupported hardware) rather than a fabricated &quot;Brightness set to 60.&quot;, the
        deterministic router is doing its job. See{" "}
        <Link href="/docs/how-it-works">How routing works</Link>.
      </p>

      <Callout tone="note" title="Cold-start latency">
        The embedding router lazy-loads on first query (~700 ms). The Mem0 extraction server, when
        enabled, takes ~3 s to warm up — the first turn after boot may have empty recalled facts.
      </Callout>

      <PrevNext current="/docs/installation" />
    </>
  );
}
