# Platform support matrix

FRIDAY targets **Linux** (primary) and **Windows**, with best-effort macOS support
for the cross-platform subsystems. Platform-specific code is guarded with
`platform.system()` / `os.name`, and system-control features route through the
adapters in [`modules/system_control/adapters/`](../modules/system_control/adapters/)
(`linux.py`, `windows.py`, `macos.py`).

This page is the honest source of truth for what works where. "Graceful" means the
feature degrades to a no-op or a clear message rather than crashing.

## Feature parity

| Feature | Linux | Windows | macOS | Notes |
|---|:---:|:---:|:---:|---|
| Wake word ("Hey Friday"), STT, TTS | ✅ | ✅ | ➖ | Porcupine + faster-whisper + Piper/pyttsx3 (SAPI5 on Windows) |
| Chat / planning / vision / embeddings (local) | ✅ | ✅ | ✅ | llama.cpp + sentence-transformers; CPU everywhere, CUDA when present |
| Screenshot | ✅ | ✅ | ✅ | Native backend per OS; `scrot` is only a last-resort X11 fallback |
| Screen lock | ✅ | ✅ | ✅ | Windows uses `LockWorkStation`; Linux uses `loginctl`/screensaver; macOS via `pmset`/CG |
| Brightness | ✅ | ✅¹ | ➖ | ¹ Windows: internal display via WMI. External monitors (DDC/CI) are not yet wired |
| Clipboard read/write | ✅ | ✅ | ✅ | Via platform adapter |
| Active-window query | ✅ | ✅ | ✅ | Via platform adapter |
| App launch | ✅ | ✅ | ✅ | Detached spawn is platform-branched (`start_new_session` vs `DETACHED_PROCESS`) |
| File index / search | ✅ | ✅ | ✅ | Index roots resolved per-platform |
| Open URL / file / folder | ✅ | ✅ | ✅ | `xdg-open` / `os.startfile` / `open` |
| Volume control | ✅ | ✅ | ➖ | |
| Browser automation (Playwright/Selenium) | ✅ | ✅ | ✅ | |
| Code-execution sandbox (Python) | ✅ | ✅ | ✅ | `run_python` uses `sys.executable` (cross-platform) |
| Code-execution sandbox (Bash) | ✅ | ➖ | ✅ | `run_bash` requires `/bin/bash` |
| Focus mode (DND + media pause) | ✅ | ⚠️ | ⚠️ | DND toggling is GNOME-centric; media pause and the timer work everywhere |
| Scheduled OS-level reminder notifications | ✅ | ⚠️ | ⚠️ | Uses `systemd-run --on-calendar` on Linux; other platforms fall back to in-app/voice reminders |
| Native in-page keystroke send (`xdotool`) | ✅ | ➖ | ➖ | Advanced browser-media focus only; degrades gracefully when absent |
| Window raise/move (`wmctrl`) | ✅ | ➖ | ➖ | Window *query* still works cross-platform via the adapter |
| Security tooling (`nmap`/`gobuster`/`dig` wrappers) | ✅ | ⚠️ | ⚠️ | Requires the underlying binaries on PATH; lab-mode gated |

Legend: ✅ supported · ⚠️ partial / best-effort · ➖ not applicable or not yet
implemented (no crash — feature is skipped with a message).

## Windows-specific notes

- **Build toolchain:** `llama-cpp-python` may build from source; `setup.ps1`
  auto-discovers MSVC via `vswhere`. See
  [SETUP_GUIDE_WINDOWS.md](../SETUP_GUIDE_WINDOWS.md).
- **External-monitor brightness** is not yet supported (internal panel only).
- **Linux-only desktop integrations** (`xdotool` keysend, `wmctrl` window
  management, `notify-send`, `gsettings` DND) have no Windows equivalent today and
  are skipped gracefully — the core voice/chat/system-control loop is unaffected.

## For contributors

When adding a feature that touches the OS:

1. Put platform-specific logic behind `platform.system()` / `os.name`, or extend
   the `system_control` adapters (`_interface.py` + the three OS files).
2. Pass `encoding="utf-8", errors="replace"` to every `subprocess.run(..., text=True)`
   (Windows' default cp1252 throws on UTF-8 output otherwise).
3. Degrade gracefully on the platforms you don't implement — return a clear
   message, never raise.
4. Update this matrix and keep `setup.sh` / `setup.ps1` in parity.
