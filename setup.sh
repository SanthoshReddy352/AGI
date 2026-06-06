#!/usr/bin/env bash
# FRIDAY Project Setup Script — Linux
# Idempotent: every step skips itself when its outcome already exists on disk.
# Tested on Ubuntu / Debian / Kali. Safe to re-run.
#
# This script aims to run end-to-end without errors on a fresh machine. Steps
# that need a network resource degrade to a clear instruction (never a hard
# failure) when that resource is unavailable.

set -u
# Don't `set -e` — we print friendly errors and keep going past non-fatal
# failures (e.g. an optional package missing on this distro, or a model whose
# download URL has not been configured yet).

# --- Colors ----------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
    BLUE='\033[0;34m'; CYAN='\033[0;36m'; DIM='\033[2m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; CYAN=''; DIM=''; NC=''
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "${SCRIPT_DIR}"

# ============================================================================
# MODEL SOURCES — edit the URLs below if you host the models elsewhere.
#   * A BLANK URL means "skip auto-download": the script prints where to place
#     the file manually and continues WITHOUT error.
#   * You may also override any URL from the environment without editing this
#     file, e.g.  FRIDAY_CHAT_MODEL_URL=https://...  ./setup.sh
#   * Filenames MUST match the paths in config.yaml (models.chat.path, etc.).
# ============================================================================
CHAT_MODEL_FILE="Qwen3.5-0.8B-Q4_K_M.gguf"
CHAT_MODEL_URL="${FRIDAY_CHAT_MODEL_URL:-https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf?download=true}"   # config: models.chat.path

TOOL_MODEL_FILE="Qwen3.5-4B-Q4_K_M.gguf"
TOOL_MODEL_URL="${FRIDAY_TOOL_MODEL_URL:-https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf?download=true}"   # config: models.tool.path

VISION_MODEL_FILE="SmolVLM2-2.2B-Instruct-Q4_K_M.gguf"
VISION_MODEL_URL="${FRIDAY_VISION_MODEL_URL:-https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf?download=true}"

VISION_MMPROJ_FILE="mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf"
VISION_MMPROJ_URL="${FRIDAY_VISION_MMPROJ_URL:-https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf?download=true}"

# Optional: Gemma 2B router (only loaded when FRIDAY_USE_GEMMA_ROUTER=1).
GEMMA_MODEL_FILE="gemma-2b-it.gguf"
GEMMA_MODEL_URL="${FRIDAY_GEMMA_MODEL_URL:-}"        # optional; blank = skip

# Piper TTS voice (ONNX + JSON pair). Browse https://huggingface.co/rhasspy/piper-voices
PIPER_VOICE="en_US-lessac-medium"
PIPER_VOICE_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

echo -e "${BLUE}==================================================${NC}"
echo -e "${GREEN}          FRIDAY - Local AI Assistant            ${NC}"
echo -e "${GREEN}             Installation Script (Linux)         ${NC}"
echo -e "${BLUE}==================================================${NC}"
echo -e "${DIM}Each step checks before doing work — re-running is safe.${NC}"

# --- Helper: skip-aware status print --------------------------------------
already() { echo -e "  ${GREEN}[skip]${NC} $1 already present."; }
doing()   { echo -e "  ${CYAN}[do]${NC}   $1"; }
warn()    { echo -e "  ${YELLOW}[warn]${NC} $1"; }
fail()    { echo -e "  ${RED}[fail]${NC} $1"; }

# --- 0. Environment file ---------------------------------------------------
echo -e "\n${YELLOW}[0/7] Environment file (.env)...${NC}"
if [ -f ".env" ]; then
    already ".env"
elif [ -f ".env.example" ]; then
    doing "Creating .env from .env.example (edit it to add your keys)."
    cp .env.example .env
else
    warn "No .env or .env.example found — wake word / Telegram features need one."
fi

# --- 1. System dependencies -----------------------------------------------
echo -e "\n${YELLOW}[1/7] Checking system dependencies...${NC}"
if [ -f /etc/os-release ] && grep -iq "ubuntu\|debian\|kali" /etc/os-release; then
    REQUIRED_PKGS=(
        libportaudio2 ffmpeg python3-venv python3-pip
        libxcb-cursor0 wget tar curl
        build-essential cmake
    )
    OPTIONAL_PKGS=(
        wmctrl xdotool grim spectacle xfce4-screenshooter scrot maim
        x11-utils libnotify-bin libsndfile1
    )
    MISSING_PKGS=()
    for pkg in "${REQUIRED_PKGS[@]}" "${OPTIONAL_PKGS[@]}"; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            MISSING_PKGS+=("$pkg")
        fi
    done
    if [ ${#MISSING_PKGS[@]} -eq 0 ]; then
        already "all required and optional system packages"
    else
        warn "Missing: ${MISSING_PKGS[*]}"
        read -p "  Install them now (sudo required) [Y/n]? " -n 1 -r reply; echo
        if [[ -z "$reply" || "$reply" =~ ^[Yy]$ ]]; then
            sudo apt-get update
            sudo apt-get install -y "${MISSING_PKGS[@]}" || \
                warn "Some packages failed to install — continuing."
        else
            warn "Continuing without installing — some features may not work."
        fi
    fi
else
    warn "Non-Debian system. Install manually: libportaudio2 ffmpeg python3-venv python3-pip wget tar curl"
fi

# --- 2. Python venv -------------------------------------------------------
echo -e "\n${YELLOW}[2/7] Python virtual environment...${NC}"

# Prefer Python 3.10-3.13 so binary wheels (e.g. llama-cpp-python) are
# available without needing to compile from source.
_find_supported_python() {
    for _pycand in python3.13 python3.12 python3.11 python3.10; do
        if command -v "$_pycand" >/dev/null 2>&1; then
            echo "$(command -v "$_pycand")"
            return 0
        fi
    done
    return 1
}

CHOSEN_PY="$(_find_supported_python || true)"
if [ -n "$CHOSEN_PY" ]; then
    _pyver="$($CHOSEN_PY -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    echo -e "  ${GREEN}Selected $CHOSEN_PY (Python $_pyver)${NC}"
else
    # No supported version found — try to auto-install python3.12.
    warn "No Python 3.10-3.13 found. Attempting auto-install of Python 3.12..."
    _installed=false
    if [ -f /etc/os-release ] && grep -iq "ubuntu\|debian\|kali" /etc/os-release; then
        # Try default repos first (works on Ubuntu 24.04+, Debian 12+).
        if sudo apt-get install -y python3.12 python3.12-venv >/dev/null 2>&1; then
            _installed=true
        else
            # Fall back to deadsnakes PPA (Ubuntu only).
            if grep -iq "ubuntu" /etc/os-release && command -v add-apt-repository >/dev/null 2>&1; then
                doing "Adding deadsnakes PPA for Python 3.12..."
                sudo add-apt-repository -y ppa:deadsnakes/ppa && \
                    sudo apt-get update -qq && \
                    sudo apt-get install -y python3.12 python3.12-venv && \
                    _installed=true || true
            fi
        fi
    fi
    if ! $_installed; then
        warn "Auto-install failed. Install Python 3.12 manually, e.g.:"
        warn "  sudo apt-get install python3.12 python3.12-venv"
        warn "  or: https://python.org/downloads/"
    fi
    CHOSEN_PY="$(_find_supported_python || true)"
    if [ -n "$CHOSEN_PY" ]; then
        _pyver="$($CHOSEN_PY -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        echo -e "  ${GREEN}Python $_pyver installed and selected: $CHOSEN_PY${NC}"
    else
        # Last resort: whatever python3 is on PATH.
        CHOSEN_PY="$(command -v python3 2>/dev/null || true)"
        if [ -z "$CHOSEN_PY" ]; then
            fail "python3 not found. Install Python 3.10-3.13 and re-run."
            exit 1
        fi
        _pyver="$($CHOSEN_PY -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        echo -e "  ${GREEN}Falling back to $CHOSEN_PY (Python $_pyver)${NC}"
        if [[ "$_pyver" < "3.10" || "$_pyver" > "3.13" ]]; then
            warn "Python $_pyver is outside the tested range (3.10-3.13)."
            warn "  Install Python 3.12 for full binary-wheel support."
        fi
    fi
fi

if [ -d ".venv" ] && [ -x ".venv/bin/python3" ]; then
    already ".venv/bin/python3"
else
    if [ -d ".venv" ]; then
        warn ".venv exists but bin/python3 is missing or not executable — recreating."
        rm -rf .venv
    fi
    doing "Creating .venv with Python $_pyver..."
    "$CHOSEN_PY" -m venv .venv || { fail "venv creation failed (is python3-venv installed?)"; exit 1; }
fi

if [ ! -x ".venv/bin/python3" ]; then
    fail ".venv/bin/python3 is not executable."
    fail "  This usually means the project is on a 'noexec' mount (NTFS, exFAT)."
    fail "  Move the project to your home directory or remount with 'exec'."
    exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate
VENV_PY="${SCRIPT_DIR}/.venv/bin/python3"

# --- 3. Python deps -------------------------------------------------------
echo -e "\n${YELLOW}[3/7] Python dependencies...${NC}"
if [ ! -f "requirements.txt" ]; then
    fail "requirements.txt not found in $(pwd)."
    exit 1
fi

# Cheap heuristic: hash requirements.txt and skip if the hash is already
# recorded as installed by a prior successful run.
REQ_HASH=$(sha256sum requirements.txt | awk '{print $1}')
REQ_STAMP=".venv/.requirements.sha256"
if [ -f "$REQ_STAMP" ] && [ "$(cat "$REQ_STAMP")" = "$REQ_HASH" ]; then
    already "Python dependencies (requirements.txt unchanged since last install)"
else
    doing "pip install dependencies"
    "$VENV_PY" -m pip install --upgrade pip setuptools wheel

    # Check CPU AVX2 support BEFORE choosing which llama-cpp-python to install.
    # Pre-built wheels from the abetlen index require AVX2; on non-AVX2 CPUs
    # the import triggers SIGILL which kills the process.
    CPU_HAS_AVX2=1
    if [ -f /proc/cpuinfo ] && ! grep -q avx2 /proc/cpuinfo 2>/dev/null; then
        CPU_HAS_AVX2=0
        warn "CPU does not report AVX2 support — will build llama-cpp-python without AVX2."
    fi

    LLAMA_OK=0
    if [ "$CPU_HAS_AVX2" -eq 1 ]; then
        # AVX2 available — use the fast pre-built binary wheel.
        doing "Installing llama-cpp-python (pre-built binary — no compiler needed)..."
        if "$VENV_PY" -m pip install llama-cpp-python --prefer-binary \
                --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu 2>/dev/null; then
            LLAMA_OK=1
        fi
    fi

    if [ "$LLAMA_OK" -eq 0 ]; then
        # No AVX2, or pre-built unavailable — compile from source.
        CMAKE_FLAGS=""
        [ "$CPU_HAS_AVX2" -eq 0 ] && CMAKE_FLAGS="-DLLAMA_AVX2=OFF -DLLAMA_AVX512=OFF"
        doing "Building llama-cpp-python from source (requires gcc + cmake)..."
        # --no-binary llama-cpp-python only: lets cmake/numpy use pre-built wheels
        if CMAKE_ARGS="$CMAKE_FLAGS" "$VENV_PY" -m pip install llama-cpp-python --no-binary llama-cpp-python; then
            LLAMA_OK=1
        else
            warn "llama-cpp-python build failed."
            warn "  Ensure gcc, cmake, and python3-dev are installed, then re-run setup.sh."
            warn "  LLM inference will be unavailable until resolved; all other features work."
        fi
    fi

    if [ "$LLAMA_OK" -eq 1 ]; then
        if "$VENV_PY" -m pip install -r requirements.txt; then
            echo "$REQ_HASH" > "$REQ_STAMP"
        else
            fail "pip install failed — inspect the log above and re-run."
            exit 1
        fi
    else
        # Install everything except llama-cpp-python to avoid a second failed build.
        TMP_REQS="$(mktemp /tmp/friday_req_no_llama.XXXXXX.txt)"
        grep -v '^\s*llama-cpp-python' requirements.txt > "$TMP_REQS"
        if "$VENV_PY" -m pip install -r "$TMP_REQS"; then
            echo "$REQ_HASH" > "$REQ_STAMP"
        else
            fail "pip install failed — inspect the log above and re-run."
            rm -f "$TMP_REQS"
            exit 1
        fi
        rm -f "$TMP_REQS"
    fi
fi

# --- 4. Playwright Chromium ----------------------------------------------
echo -e "\n${YELLOW}[4/7] Playwright Chromium runtime...${NC}"
# Playwright caches browsers under ~/.cache/ms-playwright/chromium-<rev>/
if compgen -G "${HOME}/.cache/ms-playwright/chromium-*" > /dev/null; then
    already "Chromium for Playwright (in ~/.cache/ms-playwright)"
else
    doing "playwright install chromium"
    if ! "$VENV_PY" -m playwright install chromium; then
        warn "Playwright install failed. Run '$VENV_PY -m playwright install chromium' later."
    fi
fi

# --- 5. Piper TTS engine + voice -----------------------------------------
echo -e "\n${YELLOW}[5/7] Piper TTS engine + voice...${NC}"
mkdir -p models
# 5a. Engine: extract the bundled Linux x86_64 build into ./piper/
if [ -x "piper/piper" ]; then
    already "Piper engine (piper/piper)"
elif [ -f "piper_linux_x86_64.tar.gz" ]; then
    doing "Extracting bundled Piper engine (piper_linux_x86_64.tar.gz)..."
    if tar -xzf piper_linux_x86_64.tar.gz; then
        chmod +x piper/piper 2>/dev/null || true
    else
        warn "Failed to extract Piper engine — TTS will be unavailable until fixed."
    fi
    if [ "$(uname -m)" != "x86_64" ]; then
        warn "This machine is $(uname -m); the bundled Piper is x86_64. If TTS fails,"
        warn "  download a matching build from https://github.com/rhasspy/piper/releases"
    fi
else
    warn "piper_linux_x86_64.tar.gz not found — download Piper from"
    warn "  https://github.com/rhasspy/piper/releases and extract it into ./piper/"
fi

# 5b. Voice: ONNX model + JSON config pair
download_voice() {
    local file="$1"; local url="$2"
    if [ -f "models/${file}" ] && [ -s "models/${file}" ]; then
        already "Piper voice ${file}"
    else
        doing "Downloading Piper voice ${file}..."
        wget --progress=bar:force -O "models/${file}" "$url" || {
            warn "Voice download failed (${file}). Re-run setup or fetch manually."
            rm -f "models/${file}"
        }
    fi
}
download_voice "${PIPER_VOICE}.onnx"      "${PIPER_VOICE_BASE}/${PIPER_VOICE}.onnx?download=true"
download_voice "${PIPER_VOICE}.onnx.json" "${PIPER_VOICE_BASE}/${PIPER_VOICE}.onnx.json?download=true"

# --- 6. AI models --------------------------------------------------------
echo -e "\n${YELLOW}[6/7] Local AI models...${NC}"
mkdir -p logs data data/chroma models

# Idempotent downloader. A BLANK url is not an error: it prints guidance and
# returns 0 so the script keeps going (and still "succeeds").
download_if_missing() {
    local dest="$1"; local url="$2"; local label="$3"
    if [ -f "$dest" ] && [ -s "$dest" ]; then
        already "$label ($(basename "$dest"))"
        return 0
    fi
    if [ -z "$url" ]; then
        warn "$label: no download URL configured."
        warn "  Place the file at: ${dest}"
        warn "  (set the URL at the top of setup.sh or via the matching env var)"
        return 0
    fi
    doing "Downloading $label..."
    if ! wget --progress=bar:force -O "$dest" "$url"; then
        fail "Download failed: $url"
        rm -f "$dest"
        return 0   # non-fatal: keep installing the rest
    fi
}

# Chat model (config: models.chat.path)
download_if_missing "models/${CHAT_MODEL_FILE}" "$CHAT_MODEL_URL" "Chat model"
# Tool / planner model (config: models.tool.path)
download_if_missing "models/${TOOL_MODEL_FILE}" "$TOOL_MODEL_URL" "Tool/planner model"
# Vision: SmolVLM2 2.2B Instruct + multimodal projector (config: vision.*)
download_if_missing "models/${VISION_MODEL_FILE}"  "$VISION_MODEL_URL"  "SmolVLM2 vision model"
download_if_missing "models/${VISION_MMPROJ_FILE}" "$VISION_MMPROJ_URL" "SmolVLM2 multimodal projector"
# Optional: Gemma 2B router (only when FRIDAY_USE_GEMMA_ROUTER=1)
download_if_missing "models/${GEMMA_MODEL_FILE}" "$GEMMA_MODEL_URL" "Gemma 2B router (optional)"

# STT: faster-whisper base.en (downloaded into HF cache via Python script)
WHISPER_MARKER="${HOME}/.cache/huggingface/hub/models--Systran--faster-whisper-base.en"
if [ -d "$WHISPER_MARKER" ] || ls "${HOME}/.cache/huggingface/hub" 2>/dev/null | grep -q "faster-whisper-base"; then
    already "Faster-Whisper base.en in HuggingFace cache"
elif [ -f scripts/download_stt_model.py ]; then
    doing "Downloading Faster-Whisper STT model..."
    "$VENV_PY" scripts/download_stt_model.py || \
        warn "Whisper model download failed — re-run scripts/download_stt_model.py later."
fi

# --- 7. Optional wake-word autostart -------------------------------------
echo -e "\n${YELLOW}[7/7] Optional: 'Hey Friday' wake-word autostart (systemd --user)${NC}"
echo -e "  ${DIM}Wake word uses Porcupine. Get a free key at https://console.picovoice.ai/${NC}"
echo -e "  ${DIM}and put it in .env as FRIDAY_PORCUPINE_KEY=... (no custom keyword? a built-in${NC}"
echo -e "  ${DIM}word like 'jarvis' is used automatically on this platform).${NC}"
if [ -f "$HOME/.config/systemd/user/friday-wake.service" ]; then
    already "friday-wake.service (systemd --user)"
elif [ -f "modules/voice_io/register_wake.py" ]; then
    read -p "  Register the wake-word service to autostart at login? [y/N]: " -n 1 -r reply; echo
    if [[ "$reply" =~ ^[Yy]$ ]]; then
        if ! grep -q "FRIDAY_PORCUPINE_KEY=..*" .env 2>/dev/null && [ -z "${FRIDAY_PORCUPINE_KEY:-}" ]; then
            warn "FRIDAY_PORCUPINE_KEY is not set in .env or the environment. The service"
            warn "will install but won't detect the wake word until you set it."
        fi
        "$VENV_PY" modules/voice_io/register_wake.py || \
            warn "Autostart registration failed — see output above."
    else
        echo -e "  ${DIM}Skipped. Run 'python modules/voice_io/register_wake.py' later if you change your mind.${NC}"
    fi
else
    warn "modules/voice_io/register_wake.py not found — wake autostart unavailable."
fi

echo
echo -e "${BLUE}==================================================${NC}"
echo -e "${GREEN}            Automated setup complete             ${NC}"
echo -e "${BLUE}==================================================${NC}"
echo -e "Before first launch, make sure these exist in ${CYAN}models/${NC}:"
echo -e "  ${DIM}${CHAT_MODEL_FILE}, ${TOOL_MODEL_FILE}, ${VISION_MODEL_FILE}${NC}"
echo -e "  ${DIM}(any '[warn] no download URL configured' file must be placed manually)${NC}"
echo -e ""
echo -e "Then to start FRIDAY:"
echo -e "  ${CYAN}source .venv/bin/activate${NC}"
echo -e "  ${CYAN}python main.py${NC}              # Desktop HUD"
echo -e "  ${CYAN}python main.py --text${NC}       # Text CLI"
echo -e "${BLUE}==================================================${NC}"
