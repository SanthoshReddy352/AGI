# FRIDAY — Linux setup

System dependencies for running FRIDAY on Debian / Ubuntu / Kali. Adjust
package names for other distros (e.g. `dnf` on Fedora).

## Required

### Python

FRIDAY targets Python 3.11+. Use a venv:
```bash
sudo apt install -y python3 python3-venv python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Screenshot (P0.1)

The Wayland-correct backend (xdg-desktop-portal) needs PyGObject. Without
these packages FRIDAY's screenshot capability fails across every backend.
```bash
sudo apt install -y python3-gi gir1.2-glib-2.0 xdg-desktop-portal-gnome grim
```

- `python3-gi` + `gir1.2-glib-2.0` — Python bindings for the portal API
- `xdg-desktop-portal-gnome` — the portal implementation on GNOME/Wayland
- `grim` — fallback screenshot CLI for wlroots compositors (Sway, Hyprland)

### Audio (STT + TTS)

```bash
sudo apt install -y ffmpeg portaudio19-dev libportaudio2
```

`ffmpeg` is also used by the media SKILL (`modules/system_control/SKILLS/media.md`)
and by file-based transcription (P3.20).

## Optional capability dependencies

### Security tools (modules/security_tools, requires `lab_mode: true`)

```bash
sudo apt install -y nmap arp-scan
```

### Web search (modules/web, P3.10)

The DuckDuckGo HTML fallback works without extra packages. For a faster
search backend:
```bash
pip install duckduckgo-search
```

### MCP client (modules/mcp_client, P3.8)

Optional — only needed if you configure MCP servers in
`config/mcp_servers.yaml`:
```bash
pip install mcp
```

### Vision (modules/vision)

Local vision-capable model (llava-1.6 recommended) loaded via llama.cpp.
See `modules/vision/SKILL.md` for the model path config. No system
packages required beyond ffmpeg.

### Smart home (modules/smart_home, P3.15)

No system packages — talks to Home Assistant's REST API via stdlib
urllib. Set `url:` + `token:` in `config/home_assistant.yaml` to
activate.

### Wake word (modules/voice_io, Porcupine)

No system packages required — `pvporcupine` + `pvrecorder` are pulled in
by `requirements.txt`. To enable the "Hey Friday" wake word, get a free
Picovoice access key at <https://console.picovoice.ai/> and put it in
`.env`:
```bash
FRIDAY_PORCUPINE_KEY=<your-key>
```
A custom `Wake-up-Friday_en_linux_v4_0_0.ppn` is bundled for Linux. On
Windows/macOS, FRIDAY falls back to a built-in keyword (default
`jarvis`, override via `FRIDAY_WAKE_KEYWORD`).

### Diagramming SKILL

```bash
sudo apt install -y plantuml   # only if you want PlantUML rendering
```
Mermaid output works without any package; render the `.md` files on
GitHub or in any Markdown viewer that supports Mermaid fences.

## First boot

After installing the deps:
```bash
python main.py
```

On a fresh DB FRIDAY enters onboarding — it asks for your name, role,
location, and preferences. Those land in the `user_profile` namespace
of `data/friday.db`.

To wipe and start clean:
```bash
python scripts/memory_admin.py wipe --confirm
```

## Where things live

| Path | What |
|------|------|
| `data/friday.db` | Canonical SQLite store (sessions, facts, memory, audit, KG, goals, workflows) |
| `data/chroma/` | Chroma vector index for semantic recall |
| `data/checkpoints/` | P3.16 long-running task checkpoints |
| `data/runtime_state.json` | P3.19 voice-mode persisted flag |
| `logs/friday.log` | Rolling log (everything FRIDAY does) |
| `config/` | YAML overrides — personas, STT subs, MCP servers, routines, web search, Home Assistant, website policy |
| `~/Pictures/FRIDAY_Screenshots/` | Where screenshots land |
| `~/Documents/FRIDAY/` | Default vault for notes, research, creative writing, diagrams |

## Troubleshooting

- **Screenshot fails with "Screenshot requires `python3-gi`"** → run the
  apt line in the Screenshot section above.
- **STT silent / no audio captured** → check `arecord -l` lists your
  mic; install `portaudio19-dev` and re-pip-install `sounddevice`.
- **Telegram bridge says "disabled"** → set `FRIDAY_TELEGRAM_TOKEN` and
  `FRIDAY_TELEGRAM_CHAT_ID` in `.env` (created by `setup.sh` from
  `.env.example`) before launching. Shell env vars also work and
  override `.env`.
- **"Vector store unavailable: No module named 'chromadb'"** → `pip install
  chromadb`. Without it semantic recall falls back to a token-overlap
  scorer; FRIDAY still works.
