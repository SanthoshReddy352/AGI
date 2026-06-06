# FRIDAY Setup Guide — Windows

This guide walks you through installing FRIDAY on Windows 10 / Windows 11 **two ways**:

1. **[Automated path](#automated-path-recommended)** — run `setup.ps1`. Idempotent, skips any step whose output already exists. It now downloads the **Piper TTS engine + default voice** and bootstraps your `.env`.
2. **[Fully manual path](#fully-manual-path)** — every step typed out, no scripts.

> **Default model lineup** (downloaded automatically by `setup.ps1`):
> - chat → `models\Qwen3.5-0.8B-Q4_K_M.gguf` (Unsloth GGUF, ~533 MB)
> - tool → `models\Qwen3.5-4B-Q4_K_M.gguf` (Unsloth GGUF, ~2.7 GB)
>
> Override by setting `$env:FRIDAY_CHAT_MODEL_URL` / `$env:FRIDAY_TOOL_MODEL_URL` before running `setup.ps1`, or drop your own `.gguf` files into `models\` by hand. A blank URL or failed download is skipped, not a script failure.

For Linux, see [SETUP_GUIDE.md](SETUP_GUIDE.md).

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **OS** | Windows 10 21H2+ or Windows 11 |
| **Python** | 3.10 – 3.13 from <https://python.org> with "Add to PATH" ticked |
| **PowerShell** | 5.1 (built-in) or 7+ |
| **Git** | <https://git-scm.com/download/win> |
| **RAM** | 8 GB minimum, 16 GB recommended |
| **Disk** | ~10 GB free for models + cache |
| **Build tools** | Most wheels are prebuilt for Windows. Only install **Visual C++ Build Tools 2022** from <https://visualstudio.microsoft.com/visual-cpp-build-tools/> if `pip install` complains about a missing compiler. |
| **Audio** | Default Windows audio stack works (WASAPI through `sounddevice`) |

---

## Automated path (recommended)

Open **PowerShell** in the FRIDAY folder:

```powershell
git clone https://github.com/SanthoshReddy352/FRIDAY.git
cd FRIDAY
# One-time: allow scripts to run in this shell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
```

Available flags:

| Flag | Purpose |
|---|---|
| `-SkipModels` | Don't download any model files |
| `-SkipPlaywright` | Don't install Chromium for Playwright |
| `-Force` | Re-download/re-install everything even if already present |

Each phase checks before doing work:

| Phase | What it checks | What it skips when present |
|---|---|---|
| 0. `.env` | `.env` exists | Copies `.env.example` → `.env` if missing |
| 1. Python | `python` on PATH, version 3.10–3.13 | Phase as a whole |
| 2. Venv | `.venv\Scripts\python.exe` exists | Venv re-creation |
| 3. Pip deps | SHA-256 of `requirements.txt` vs `.venv\.requirements.sha256` | Full `pip install` |
| 4. Playwright | `%LOCALAPPDATA%\ms-playwright\chromium-*` exists | Browser download |
| 5. Piper TTS | `piper\piper.exe` + voice files exist | Engine zip download + voice download |
| 6. Models | Each `models\<file>.gguf` exists and is non-empty | Per-file download |
| 7. Wake autostart | `…\Startup\friday_wake.bat` exists | Re-registration |

After `setup.ps1` completes, set your keys in `.env` (see [Environment variables](#environment-variables)) and jump to **[Starting FRIDAY](#starting-friday)**.

---

## Fully manual path

### Step 1 — Install prerequisites

1. **Python 3.10–3.13** from <https://python.org/downloads/windows/>.
   During the installer, **tick "Add python.exe to PATH"**.
2. **Git for Windows** from <https://git-scm.com/download/win>.
3. Open a fresh PowerShell window and verify:

```powershell
python --version            # 3.10.x .. 3.13.x
git --version
```

### Step 2 — Clone the repository

```powershell
git clone https://github.com/SanthoshReddy352/FRIDAY.git
cd FRIDAY
```

### Step 3 — Allow PowerShell scripts (one-time)

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

This only affects the current shell. To allow signed scripts permanently for your user account:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### Step 4 — Create the virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Verify
.\.venv\Scripts\python.exe --version
```

### Step 5 — Install Python dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Expect ~3 GB of downloads on a fresh install. If pip complains about a missing C++ compiler, install **Visual C++ Build Tools 2022** (tick the "Desktop development with C++" workload) and re-run.

### Step 6 — Install the Playwright Chromium runtime

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
```

Skip if you don't plan to use browser-automation tools.

### Step 7 — Download AI models

```powershell
New-Item -ItemType Directory -Force -Path logs, data, "data\chroma", models | Out-Null
```

FRIDAY uses these GGUF models (filenames **must** match `config.yaml`):

| Role | File (in `models\`) | config.yaml key | Source |
|---|---|---|---|
| Chat | `Qwen3.5-0.8B-Q4_K_M.gguf` | `models.chat.path` | Unsloth (default) |
| Tool / planner | `Qwen3.5-4B-Q4_K_M.gguf` | `models.tool.path` | Unsloth (default) |
| Vision | `SmolVLM2-2.2B-Instruct-Q4_K_M.gguf` | `vision.model_path` | ggml-org (below) |
| Vision projector | `mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf` | `vision.mmproj_path` | ggml-org (below) |
| Router (optional) | `gemma-2b-it.gguf` | used when `FRIDAY_USE_GEMMA_ROUTER=1` | optional |

Use `Invoke-WebRequest` with the progress UI **disabled** — leaving it on makes large files crawl:

```powershell
$ProgressPreference = 'SilentlyContinue'   # 10x speedup for big downloads

# Chat + tool models (Unsloth GGUFs — defaults baked into setup.ps1):
Invoke-WebRequest -Uri "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf?download=true" `
    -OutFile "models\Qwen3.5-0.8B-Q4_K_M.gguf"
Invoke-WebRequest -Uri "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf?download=true" `
    -OutFile "models\Qwen3.5-4B-Q4_K_M.gguf"

# Vision — SmolVLM2 2.2B Instruct (~1.1 GB)
Invoke-WebRequest -Uri "https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf?download=true" `
    -OutFile "models\SmolVLM2-2.2B-Instruct-Q4_K_M.gguf"

# Vision multimodal projector (~600 MB)
Invoke-WebRequest -Uri "https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf?download=true" `
    -OutFile "models\mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf"
```

`setup.ps1` reads these URLs from the **MODEL SOURCES** block at the top of the script (or the `FRIDAY_*_MODEL_URL` env vars). The Vision URLs are pre-filled; the chat/tool URLs are blank by default. Local filenames must match `config.yaml` exactly.

### Step 8 — Download the Faster-Whisper STT model

```powershell
.\.venv\Scripts\python.exe scripts\download_stt_model.py
```

This pulls `Systran/faster-whisper-base.en` (~145 MB) into `%USERPROFILE%\.cache\huggingface\hub\`.

### Step 9 — Install Piper TTS (engine + voice)

See [Piper TTS](#piper-tts-voice-output) below — `setup.ps1` does this for you
(downloads `piper_windows_amd64.zip` and the default voice).

### Step 10 — (Optional) Wake word "Hey Friday"

Wake word uses **Porcupine**. The simplest place for the key is the project
`.env` (the wake launcher reads it on startup):

```powershell
# 1. Get a free Picovoice access key: https://console.picovoice.ai/
# 2. Add it to .env (created by setup.ps1):
Add-Content .env "FRIDAY_PORCUPINE_KEY=<your-key>"

# 3. Register the .bat shortcut in the Startup folder:
.\.venv\Scripts\python.exe modules\voice_io\register_wake.py

# 4. Confirm:
Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\friday_wake.bat"
```

> **Which keyword fires on Windows?** No custom "Hey Friday" `.ppn` is bundled
> for Windows (Porcupine keyword files are platform-specific — the Linux file
> will **not** load on Windows). So a built-in word is used automatically —
> default **"jarvis"**, override with `FRIDAY_WAKE_KEYWORD` (e.g. `computer`,
> `bumblebee`). To use a real "Hey Friday", train a Windows `.ppn` at the
> Picovoice console and save it as
> `modules\voice_io\Wake-up-Friday_en_windows_v4_0_0.ppn` — it's auto-detected.

### Step 11 — (Optional) Enable Mem0 long-term memory

Edit `config.yaml` and flip:

```yaml
memory:
  enabled: true   # was false
```

FRIDAY will boot a local llama.cpp extraction server on port 8181 (using the Qwen3 4B model from Step 7) on the next launch. User facts start surfacing in chat prompts as "What you know about the user".

---

## Piper TTS (voice output)

FRIDAY uses Piper for offline voice output. **`setup.ps1` now downloads the
Windows engine zip and the default voice automatically** (phase 5). The manual
steps below are kept as a fallback for when the download fails, you need a
different voice, or you want to swap architectures.

### A) Download the Piper engine binary

1. Open <https://github.com/rhasspy/piper/releases>
2. Download `piper_windows_amd64.zip` (under the latest release's Assets).
3. From PowerShell, extract it into the `piper\` folder at the project root:

```powershell
# From the FRIDAY project root, assuming the zip is in your Downloads:
$src = "$env:USERPROFILE\Downloads\piper_windows_amd64.zip"
Expand-Archive -Path $src -DestinationPath piper -Force

# Some Piper zips nest everything under a piper\ subfolder. Flatten if so:
$nested = Join-Path (Get-Location) "piper\piper"
if (Test-Path $nested) {
    Get-ChildItem $nested -Force | Move-Item -Destination (Join-Path (Get-Location) "piper") -Force
    Remove-Item $nested -Recurse -Force
}

# Smoke test
.\piper\piper.exe --help | Select-Object -First 5
```

Expected layout:

```
piper\
├── piper.exe          (executable, this is what FRIDAY calls)
├── espeak-ng-data\
├── onnxruntime.dll
└── piper_phonemize.dll
```

### B) Download a voice model

A voice is one `.onnx` file plus its `.onnx.json` config. Both must live in `models\` and the filename must match `modules\voice_io\tts.py`'s default: `en_US-lessac-medium.onnx`.

Browse <https://huggingface.co/rhasspy/piper-voices/tree/main> to pick a voice; the default lessac/medium English voice is:

```powershell
$ProgressPreference = 'SilentlyContinue'

Invoke-WebRequest `
    -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true" `
    -OutFile "models\en_US-lessac-medium.onnx"

Invoke-WebRequest `
    -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true" `
    -OutFile "models\en_US-lessac-medium.onnx.json"
```

### C) Smoke test

```powershell
"Hello, this is Friday." | .\piper\piper.exe `
    --model models\en_US-lessac-medium.onnx --output_raw `
    | .\.venv\Scripts\python.exe -c "import sys, sounddevice as sd; s=sd.RawOutputStream(samplerate=22050, channels=1, dtype='int16'); s.start(); [s.write(c) for c in iter(lambda: sys.stdin.buffer.read(4096), b'')]; s.stop(); s.close()"
```

You should hear FRIDAY speak. If you get no sound, check Windows volume mixer and the default playback device, then try the same command again — `sounddevice` will pick up whatever WASAPI defaults to.

---

## Starting FRIDAY

```powershell
.\.venv\Scripts\Activate.ps1
python main.py            # Desktop HUD (PyQt6)
python main.py --text     # Text-only CLI
python main.py --verbose  # With runtime logs visible
```

To stop: focus the HUD and close it, or Ctrl+C in the terminal.

---

## Environment variables

All secrets and feature toggles live in a git-ignored `.env` at the project
root. `setup.ps1` creates it from [`.env.example`](.env.example), which
documents every variable. The ones you're most likely to set on Windows:

| Variable | Purpose |
|---|---|
| `FRIDAY_PORCUPINE_KEY` | Wake word (Porcupine). Free key from Picovoice. |
| `FRIDAY_WAKE_KEYWORD` | Built-in wake word (default `jarvis`). Any Porcupine built-in: `computer`, `bumblebee`, `terminator`, ... |
| `FRIDAY_WAKE_MIC_INDEX` | Pin the wake-word listener to a specific input device index (default `-1` = system default). |
| `FRIDAY_TELEGRAM_TOKEN` / `FRIDAY_TELEGRAM_CHAT_ID` | Telegram bridge. |
| `FEED_PRISM_API_KEY` | World-monitor / news feed API. |
| `FRIDAY_USE_GEMMA_ROUTER` | `1` to enable the Gemma 2B shadow router. |
| `FRIDAY_CHAT_MODEL_URL` / `FRIDAY_TOOL_MODEL_URL` | Setup-time model download sources. |

Shell environment variables always override `.env`. Edit `.env` (e.g.
`notepad .env`), then restart FRIDAY for changes to take effect.

---

## Windows-Specific Notes

### Audio devices

```powershell
python -c "import sounddevice; print(sounddevice.query_devices())"
```

By default `input_device` is `null`, so FRIDAY uses the Windows default mic.
To pin a specific device, set it in `config.yaml`:

```yaml
voice:
  input_device: {id: 3, kind: wasapi, label: "Realtek Audio"}
```

### App-launch coverage

The launcher resolves binaries via `where` (Windows PATH + PATHEXT). Bundled registry covers:

- **Browsers**: Chrome, Edge, Brave, Chromium, Firefox
- **System**: File Explorer (`explorer.exe`), Windows Terminal (`wt.exe`), PowerShell, cmd.exe, Calculator (`calc.exe`), Notepad
- **Media**: VLC, mpv

For anything else, ensure it's on `PATH` or invoke with the full path:

```
> open "C:\Program Files\Slack\slack.exe"
```

### Screenshots

The Windows path uses `pyautogui` directly. Screenshots land in `%USERPROFILE%\Pictures\FRIDAY_Screenshots\`.

### Window manipulation

`wmctrl` / `xdotool` are Linux-only; browser automation on Windows launches windows but doesn't auto-position them. If you need that, install `pywinauto` and file a feature request.

---

## Troubleshooting

### "running scripts is disabled on this system"

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

(Per-shell. For a user-scope persistent setting use `-Scope CurrentUser -ExecutionPolicy RemoteSigned`.)

### `pip install` fails — "Microsoft Visual C++ 14.0 is required"

A dependency tried to build a wheel from source. Install **Visual C++ Build Tools 2022** from <https://visualstudio.microsoft.com/visual-cpp-build-tools/>, tick the "Desktop development with C++" workload, then re-run `setup.ps1` (or Step 5 of the manual path).

### Long-path errors during pip install

Some transitive deps create paths longer than 260 characters. Enable long paths once:

```powershell
# Run as Administrator
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
    -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

Sign out and back in for the change to take effect.

### Wake-word service not starting at login

- Confirm the `.bat` exists: `Test-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\friday_wake.bat"`
- Verify `FRIDAY_PORCUPINE_KEY` is a **User** env var (not just session): in a fresh shell run `$env:FRIDAY_PORCUPINE_KEY`
- Check `logs\wake_detector.log` for errors

### Piper exits immediately with a DLL error

The Windows Piper zip relies on `onnxruntime.dll` and Visual C++ 2015–2022 runtimes. Install both:

- Latest VC++ Redistributable: <https://aka.ms/vs/17/release/vc_redist.x64.exe>
- Confirm `piper\onnxruntime.dll` exists — re-extract the zip if missing.

---

## What's New (2026-05-26 refresh)

- **Piper is now automated** — `setup.ps1` downloads `piper_windows_amd64.zip`, extracts it, and pulls the default `en_US-lessac-medium` voice (phase 5). Manual steps kept as a fallback.
- **`.env` bootstrap** — setup copies `.env.example` → `.env`; all secrets/toggles documented in one place. See [Environment variables](#environment-variables).
- **Unified wake word on Porcupine** — both in-app detection and the autostart `.bat` shortcut now share the same `pvporcupine` backend (the previous `openwakeword` dependency is gone). Custom `.ppn` files are platform-specific, so Windows falls back to a built-in keyword (default `jarvis`, override via `FRIDAY_WAKE_KEYWORD`).
- **Refreshed model lineup** — `FRIDAY_*_MODEL_URL` env vars let you self-host the GGUFs without editing the script. Default models: Qwen 3.5 0.8B (chat) + Qwen 3.5 4B (tools) + SmolVLM 2.2B (vision) + optional Gemma 2B (router).
- **Portable defaults** — `input_device` defaults to the Windows default mic; `friday-sandbox` uses `%TEMP%`; setup runs without hard failures on a fresh machine.
- **First-class Windows support** (retained): app launcher, autostart, subprocess flags, and wake-word detector all handle Windows paths and process semantics. Subprocess calls everywhere use `encoding="utf-8", errors="replace"` so non-ASCII output from Windows tools never crashes the parser.

For the architecture details, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
