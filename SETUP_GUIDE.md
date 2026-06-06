# FRIDAY Setup Guide — Linux

This guide walks you through installing FRIDAY on Linux **two ways**:

1. **[Automated path](#automated-path-recommended)** — run `setup.sh`. Idempotent, skips any step whose output is already on disk. It now also installs the **Piper TTS engine + default voice** and bootstraps your `.env`.
2. **[Fully manual path](#fully-manual-path)** — every step typed out, no scripts. Use this if you're auditing what gets installed or if `setup.sh` fails partway.

> **Default model lineup** (downloaded automatically by `setup.sh`):
> - chat → `models/Qwen3.5-0.8B-Q4_K_M.gguf` (Unsloth GGUF, ~533 MB)
> - tool → `models/Qwen3.5-4B-Q4_K_M.gguf` (Unsloth GGUF, ~2.7 GB)
>
> Override by exporting `FRIDAY_CHAT_MODEL_URL` / `FRIDAY_TOOL_MODEL_URL` before running `setup.sh`, or drop your own `.gguf` files into `models/` by hand. The script never *fails* on a download error or a blank URL — it tells you where to put the file and continues.

For Windows, see [SETUP_GUIDE_WINDOWS.md](SETUP_GUIDE_WINDOWS.md).

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **OS** | Ubuntu 22.04+ / Debian 12+ / Kali rolling (other Linuxes work but unsupported) |
| **Python** | 3.10 – 3.13 (3.11 recommended) |
| **RAM** | 8 GB minimum, 16 GB recommended |
| **Disk** | ~10 GB free for models + cache (Piper voice is another ~60 MB) |
| **Audio** | PipeWire (preferred) or ALSA. `libportaudio2` is required either way |
| **Internet** | Required only during setup; FRIDAY is local-first at runtime |
| **GPU** | Optional. llama.cpp and faster-whisper auto-use CUDA when present |

---

## Automated path (recommended)

```bash
git clone https://github.com/SanthoshReddy352/FRIDAY.git
cd FRIDAY
chmod +x setup.sh
./setup.sh
```

The script's phases each check before doing work:

| Phase | What it checks | What it skips when already present |
|---|---|---|
| 0. `.env` | `.env` exists | Copies `.env.example` → `.env` if missing |
| 1. System packages | `dpkg -s <pkg>` for each required and optional package | Phase as a whole if everything is installed |
| 2. Python venv | `.venv/bin/python3` exists & is executable | Venv re-creation |
| 3. Python deps | SHA-256 of `requirements.txt` vs `.venv/.requirements.sha256` | Full `pip install` |
| 4. Playwright Chromium | `~/.cache/ms-playwright/chromium-*` exists | Browser download |
| 5. Piper TTS | `piper/piper` + voice files exist | Engine extract + voice download |
| 6. Models | Each `models/<file>.gguf` exists and is non-empty | Per-file download |
| 7. Wake autostart | `~/.config/systemd/user/friday-wake.service` exists | Re-registration |

After `setup.sh` completes, set your keys in `.env` (see [Environment variables](#environment-variables)) and jump to **[Starting FRIDAY](#starting-friday)**.

---

## Fully manual path

Every step the script does, typed out. Run these in order.

### Step 1 — Install system packages

```bash
sudo apt-get update
sudo apt-get install -y \
    libportaudio2 ffmpeg python3-venv python3-pip \
    libxcb-cursor0 wget tar curl \
    wmctrl xdotool grim spectacle xfce4-screenshooter scrot maim \
    x11-utils libnotify-bin libsndfile1
```

Required: the first row. Optional but recommended: the second and third rows (window manipulation, screenshot tools, notifications). FRIDAY degrades gracefully if any optional package is missing.

### Step 2 — Clone the repository

```bash
git clone https://github.com/SanthoshReddy352/FRIDAY.git
cd FRIDAY
```

### Step 3 — Create the Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate

# Verify the venv binary is executable (fails on noexec mounts)
test -x .venv/bin/python3 && echo "venv OK" || echo "FAIL: noexec mount?"
```

If the verify line prints `FAIL`, your project sits on a `noexec` mount
(common on NTFS, exFAT, some loop-mounted volumes). Move FRIDAY to your
home directory or remount the volume with `exec` permissions.

### Step 4 — Install Python dependencies

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

This pulls in PyQt6, llama-cpp-python, faster-whisper, sentence-transformers, mem0ai (optional), and the rest. Plan for ~3 GB of downloads on a cold install.

### Step 5 — Install the Playwright Chromium runtime

```bash
python -m playwright install chromium
# If you also want OS dependencies for headless Chromium:
# python -m playwright install --with-deps chromium
```

Skip this step if you don't plan to use browser-automation tools (YouTube, web search, Workspace browser flow).

### Step 6 — Download AI models

Create the directories first:

```bash
mkdir -p logs data data/chroma models
```

FRIDAY uses these GGUF models (filenames **must** match `config.yaml`):

| Role | File (in `models/`) | config.yaml key | Source |
|---|---|---|---|
| Chat | `Qwen3.5-0.8B-Q4_K_M.gguf` | `models.chat.path` | Unsloth (default) |
| Tool / planner | `Qwen3.5-4B-Q4_K_M.gguf` | `models.tool.path` | Unsloth (default) |
| Vision | `SmolVLM2-2.2B-Instruct-Q4_K_M.gguf` | `vision.model_path` | ggml-org (below) |
| Vision projector | `mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf` | `vision.mmproj_path` | ggml-org (below) |
| Router (optional) | `gemma-2b-it.gguf` | used when `FRIDAY_USE_GEMMA_ROUTER=1` | optional |

```bash
# Chat + tool models (Unsloth GGUFs — defaults baked into setup.sh):
wget -O models/Qwen3.5-0.8B-Q4_K_M.gguf \
    "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf?download=true"
wget -O models/Qwen3.5-4B-Q4_K_M.gguf \
    "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf?download=true"

# Vision model — SmolVLM2 2.2B Instruct (~1.1 GB)
wget -O models/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf \
    "https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf?download=true"

# Vision multimodal projector — required by SmolVLM2 (~600 MB)
wget -O models/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf \
    "https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf?download=true"
```

> The automated `setup.sh` reads these URLs from the **MODEL SOURCES** block at the top of the script (or the `FRIDAY_*_MODEL_URL` environment variables). The Vision URLs are pre-filled; the chat/tool URLs are blank by default so the script will tell you to place those two files manually unless you fill them in. Local filenames must match `config.yaml` exactly.

### Step 7 — Download the Faster-Whisper STT model

```bash
python scripts/download_stt_model.py
```

This pulls `Systran/faster-whisper-base.en` (~145 MB) into the standard HuggingFace cache at `~/.cache/huggingface/hub/`. No action needed if the cache already has it.

### Step 8 — Install Piper TTS (engine + voice)

See [Piper TTS](#piper-tts-voice-output) below. On the manual path you extract
the bundled `piper_linux_x86_64.tar.gz` and download the default voice — the
automated `setup.sh` does both for you.

### Step 9 — (Optional) Wake word "Hey Friday"

Wake word is handled by **Porcupine** (cross-platform, runs fully offline once
set up). See [Wake word](#wake-word-hey-friday) for the full walkthrough. The
short version:

```bash
# 1. Get a free Picovoice access key: https://console.picovoice.ai/
# 2. Put it in .env (NOT your shell rc — register_wake reads the project .env):
echo 'FRIDAY_PORCUPINE_KEY=<your-key-here>' >> .env

# 3. Register the systemd --user autostart service:
python modules/voice_io/register_wake.py

# 4. Confirm:
systemctl --user status friday-wake.service
```

On Linux the bundled **"Hey Friday"** keyword is used. On Windows/macOS, where
no custom keyword is bundled, a built-in word (default **"jarvis"**, override
with `FRIDAY_WAKE_KEYWORD`) is used automatically.

### Step 10 — (Optional) Enable Mem0 long-term memory

Edit `config.yaml`:

```yaml
memory:
  enabled: true   # was false
```

On the next launch, FRIDAY will spawn a local llama.cpp extraction server on port 8181 (using the Qwen3 4B model you already downloaded). User facts will start surfacing in chat prompts as "What you know about the user".

---

## Piper TTS (voice output)

`setup.sh` installs Piper for you (phase 5): it extracts the bundled
`piper_linux_x86_64.tar.gz` into `piper/` and downloads the default
`en_US-lessac-medium` voice into `models/`. This section is the **manual
fallback** and reference (other CPU architectures, alternate voices).

### A) Install the Piper engine binary

The repo ships an x86_64 Linux build as `piper_linux_x86_64.tar.gz`. Extract it
at the project root (this is exactly what the script does):

```bash
tar -xzf piper_linux_x86_64.tar.gz     # creates ./piper/piper
chmod +x piper/piper
piper/piper --help                     # quick smoke test
```

On a **non-x86_64** machine (aarch64 / armv7 Raspberry Pi), download a matching
build from <https://github.com/rhasspy/piper/releases> and extract it into
`piper/` so that `piper/piper` is executable.

Expected layout:

```
piper/
├── piper          (executable, this is what FRIDAY calls)
├── espeak-ng-data/
├── libespeak-ng.so.1
├── libonnxruntime.so.*
└── libpiper_phonemize.so.*
```

### B) Download a voice model

A voice is one `.onnx` file plus its `.onnx.json` config. Both must live in `models/` and the filename must match what `modules/voice_io/tts.py` resolves (default: `en_US-lessac-medium.onnx`).

Browse the catalogue at <https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium> (or pick a different speaker/language under `en/`, `de/`, `fr/`, etc.).

For the default lessac/medium voice (~63 MB onnx + 5 KB json):

```bash
wget -O models/en_US-lessac-medium.onnx \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true"

wget -O models/en_US-lessac-medium.onnx.json \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json?download=true"
```

If you pick a different voice, also rebuild `modules/voice_io/tts.py`'s
`model_path` references — or just override via `FRIDAY_PIPER_VOICE_NAME`
if that env var is supported in your build.

### C) Smoke test

```bash
echo "Hello, this is Friday." | piper/piper \
    --model models/en_US-lessac-medium.onnx --output_raw \
    | aplay -r 22050 -f S16_LE -t raw -
```

You should hear FRIDAY speak. If `aplay` isn't available, try `pw-cat`:

```bash
echo "Hello, this is Friday." | piper/piper \
    --model models/en_US-lessac-medium.onnx --output_raw \
    | pw-cat --playback --raw --rate 22050 --format s16 --channels 1 -
```

If both fail, FRIDAY's own `sounddevice` fallback will still work at runtime — no further action needed for the smoke test.

---

## Wake word ("Hey Friday")

FRIDAY's wake word runs on **Porcupine** (Picovoice) — fully offline at
runtime, cross-platform, and used both to *launch* FRIDAY when it isn't running
(via the autostart service) and to *re-wake* it within a session.

**1. Get a free access key** at <https://console.picovoice.ai/> and put it in
your project `.env`:

```bash
echo 'FRIDAY_PORCUPINE_KEY=<your-key-here>' >> .env
```

**2. Which keyword fires?** Resolution is automatic:

| Platform | Keyword used |
|---|---|
| Linux | bundled **"Hey Friday"** (`modules/voice_io/Wake-up-Friday_en_linux_v4_0_0.ppn`) |
| Windows / macOS | a built-in Porcupine word — default **"jarvis"** (set `FRIDAY_WAKE_KEYWORD`) |

To use a custom "Hey Friday" on Windows/macOS, train a `.ppn` for that platform
at the Picovoice console and drop it next to the Linux one as
`Wake-up-Friday_en_windows_v4_0_0.ppn` / `..._mac_...` — it's picked up
automatically.

**3. Autostart on login** (optional, recommended for hands-free use):

```bash
python modules/voice_io/register_wake.py      # installs friday-wake.service
systemctl --user status friday-wake.service   # confirm it's running
```

The service listens for the wake word and launches FRIDAY, then releases the
mic while FRIDAY runs. If `FRIDAY_PORCUPINE_KEY` is unset, FRIDAY still works —
it falls back to manual listening and a transcript-based wake.

---

## Environment variables

All secrets and feature toggles live in a git-ignored `.env` at the project
root. `setup.sh` creates it from [`.env.example`](.env.example), which
documents every variable. The ones you're most likely to set:

| Variable | Purpose |
|---|---|
| `FRIDAY_PORCUPINE_KEY` | Wake word (Porcupine). Free key from Picovoice. |
| `FRIDAY_WAKE_KEYWORD` | Built-in wake word on Windows/macOS (default `jarvis`). |
| `FRIDAY_TELEGRAM_TOKEN` / `FRIDAY_TELEGRAM_CHAT_ID` | Telegram bridge. |
| `FEED_PRISM_API_KEY` | World-monitor / news feed API. |
| `FRIDAY_USE_GEMMA_ROUTER` | `1` to enable the Gemma 2B shadow router. |
| `FRIDAY_CHAT_MODEL_URL` / `FRIDAY_TOOL_MODEL_URL` | Setup-time model download sources. |

Shell environment variables always override `.env`. Edit `.env`, then restart
FRIDAY for changes to take effect.

---

## Starting FRIDAY

```bash
source .venv/bin/activate
python main.py            # Desktop HUD (PyQt6)
python main.py --text     # Text-only CLI
python main.py --verbose  # Show runtime logs in the terminal
```

To stop: close the HUD window, or hit Ctrl+C in the terminal. The shutdown handler flushes the memory queue and stops the wake-word detector if running.

---

## Troubleshooting

### Audio: "could not find an input device"

```bash
python tests/test_audio_devices.py
```

Lists all detected microphones. By default `input_device` is `null`, so FRIDAY
uses the system default mic. To pin a specific device, set it in `config.yaml`:

```yaml
voice:
  input_device: {id: 3, kind: sounddevice, label: "Your mic name"}
  # PipeWire users can instead use: {id: 108, kind: pipewire, label: "..."}
```

### Screenshots fail on Wayland

FRIDAY's fallback chain (in `modules/system_control/screenshot.py`):
Mutter ScreenCast → xdg-desktop-portal → GNOME Shell D-Bus → gnome-screenshot → grim → spectacle → X11 tools → pyautogui.

If all paths fail, install the one matching your desktop:

```bash
sudo apt-get install gnome-screenshot          # GNOME
sudo apt-get install grim slurp                # sway / Hyprland
sudo apt-get install kde-spectacle             # KDE Plasma
```

### TTS is silent

```bash
ls -la piper/piper                              # must exist and be executable
ls -la models/en_US-lessac-medium.onnx*         # both files must exist
which pw-cat aplay                              # at least one must be present
```

If `piper/piper` is missing, re-run `setup.sh` or redo [Piper TTS](#piper-tts-voice-output).

### Re-run a specific phase

`./setup.sh` is idempotent — re-running only does the missing pieces. If you want to force a single step:

- **Re-download a specific model**: delete the file and re-run `setup.sh`.
- **Re-install pip deps**: delete `.venv/.requirements.sha256` and re-run.
- **Re-install Playwright**: delete `~/.cache/ms-playwright/chromium-*` and re-run.

### `.venv/bin/python3` is not executable

Your project folder is on a `noexec` mount. Move to `~/` or remount with `exec`.

---

## What's New (2026-05-26 refresh)

- **Piper is now automated** — `setup.sh` extracts the bundled engine and downloads the default voice (phase 5). Manual steps kept as a fallback.
- **`.env` bootstrap** — setup copies `.env.example` → `.env`; all secrets/toggles documented in one place. See [Environment variables](#environment-variables).
- **Model lineup matches `config.yaml`** — `Qwen3.5-0.8B` (chat) + `Qwen3.5-4B` (tool) + SmolVLM2 2.2B (vision) + optional `gemma-2b-it` router. Chat/tool URLs are yours to provide; a blank URL is skipped, not an error.
- **Wake word standardized on Porcupine** — cross-platform, key in `.env`, automatic built-in keyword fallback on Windows/macOS. See [Wake word](#wake-word-hey-friday).
- **Portable defaults** — `input_device` defaults to the system mic; setup runs without hard failures on a fresh machine.
- **First-class Windows support** — see [SETUP_GUIDE_WINDOWS.md](SETUP_GUIDE_WINDOWS.md).

### 2026-05-14 refresh
- Idempotent setup script; SmolVLM2 vision; routing false-trigger guards & memory pipeline fixes.
