<#
.SYNOPSIS
    FRIDAY Project Setup Script — Windows (PowerShell 5.1+ or PowerShell 7+).

.DESCRIPTION
    Idempotent: every step checks whether its outcome already exists on disk
    and skips itself when so. Re-running is safe. The script is designed to run
    end-to-end without throwing on a fresh machine — network steps that fail or
    are unconfigured print a clear instruction and continue.

    Chat/tool model URLs are blank by default (see the MODEL SOURCES block
    below): set them once, or pass them via environment variables, or drop the
    .gguf files into models\ manually. A blank URL is skipped, not an error.

.PARAMETER SkipModels
    Skip all AI-model downloads.

.PARAMETER SkipPlaywright
    Skip the Playwright Chromium download.

.PARAMETER Force
    Re-download models even if they already exist on disk.

.EXAMPLE
    .\setup.ps1
    .\setup.ps1 -SkipModels
    .\setup.ps1 -Force
#>

[CmdletBinding()]
param(
    [switch]$SkipModels,
    [switch]$SkipPlaywright,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# ============================================================================
# MODEL SOURCES — edit the URLs below if you host the models elsewhere.
#   * A BLANK URL means "skip auto-download": the script prints where to place
#     the file manually and continues WITHOUT error.
#   * You may also override any URL from the environment, e.g.
#       $env:FRIDAY_CHAT_MODEL_URL = "https://..."; .\setup.ps1
#   * Filenames MUST match the paths in config.yaml (models.chat.path, etc.).
# ============================================================================
$ChatModelFile   = "Qwen3.5-0.8B-Q4_K_M.gguf"
$ChatModelUrl    = if ($env:FRIDAY_CHAT_MODEL_URL) { $env:FRIDAY_CHAT_MODEL_URL } else { "https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_K_M.gguf?download=true" }
$ToolModelFile   = "Qwen3.5-4B-Q4_K_M.gguf"
$ToolModelUrl    = if ($env:FRIDAY_TOOL_MODEL_URL) { $env:FRIDAY_TOOL_MODEL_URL } else { "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf?download=true" }
$VisionModelFile = "SmolVLM2-2.2B-Instruct-Q4_K_M.gguf"
$VisionModelUrl  = if ($env:FRIDAY_VISION_MODEL_URL) { $env:FRIDAY_VISION_MODEL_URL } else { "https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf?download=true" }
$VisionMmprojFile = "mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf"
$VisionMmprojUrl  = if ($env:FRIDAY_VISION_MMPROJ_URL) { $env:FRIDAY_VISION_MMPROJ_URL } else { "https://huggingface.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF/resolve/main/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf?download=true" }
# Optional: Gemma 2B router (only loaded when FRIDAY_USE_GEMMA_ROUTER=1).
$GemmaModelFile  = "gemma-2b-it.gguf"
$GemmaModelUrl   = if ($env:FRIDAY_GEMMA_MODEL_URL) { $env:FRIDAY_GEMMA_MODEL_URL } else { "" }
# Piper TTS engine (Windows build) + voice.
$PiperZipUrl     = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
$PiperVoice      = "en_US-lessac-medium"
$PiperVoiceBase  = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

function Write-Section { param([string]$Msg) Write-Host "`n$Msg" -ForegroundColor Yellow }
function Write-Skip { param([string]$Msg) Write-Host "  [skip] $Msg already present." -ForegroundColor Green }
function Write-Doing { param([string]$Msg) Write-Host "  [do]   $Msg" -ForegroundColor Cyan }
function Write-Warn { param([string]$Msg) Write-Host "  [warn] $Msg" -ForegroundColor DarkYellow }
function Write-Err { param([string]$Msg) Write-Host "  [fail] $Msg" -ForegroundColor Red }

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "          FRIDAY - Local AI Assistant             " -ForegroundColor Green
Write-Host "             Installation Script (Windows)        " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Each step checks before doing work - re-running is safe." -ForegroundColor DarkGray

# --- 0. Environment file --------------------------------------------------
Write-Section "[0/7] Environment file (.env)..."
if (Test-Path ".env") {
    Write-Skip ".env"
} elseif (Test-Path ".env.example") {
    Write-Doing "Creating .env from .env.example (edit it to add your keys)."
    Copy-Item ".env.example" ".env"
} else {
    Write-Warn "No .env or .env.example found - wake word / Telegram features need one."
}

# --- 1. Python check ------------------------------------------------------
Write-Section "[1/7] Verifying Python interpreter..."

# Silently probe py.exe for a supported version (3.10-3.13).
function Find-SupportedPython {
    $saved = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
    $hit = $null
    foreach ($v in @("3.13", "3.12", "3.11", "3.10")) {
        $raw = (& py "-$v" -c "import sys; print(sys.executable)" 2>&1)
        $exe = ($raw | Where-Object { $_ -is [string] } | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $exe) {
            $verLine = (& py "-$v" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1)
            $verStr  = ($verLine | Where-Object { $_ -is [string] } | Select-Object -First 1).Trim()
            $hit = @{ Exe = $exe.Trim(); Ver = $verStr }
            break
        }
    }
    $ErrorActionPreference = $saved
    return $hit
}

$ChosenPyExe = $null
$pyVersion   = $null

if (Get-Command py -ErrorAction SilentlyContinue) {
    $found = Find-SupportedPython
    if (-not $found) {
        Write-Warn "No Python 3.10-3.13 found. Auto-installing Python 3.12 (this may take a minute)..."
        $saved = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
        & py install 3.12 2>&1 | Out-Host
        $pyInstallOk = $LASTEXITCODE -eq 0
        $ErrorActionPreference = $saved
        if (-not $pyInstallOk) {
            Write-Warn "py install not supported. Trying winget install Python.Python.3.12 ..."
            $saved = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
            winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
            $ErrorActionPreference = $saved
        }
        $found = Find-SupportedPython
        if ($found) {
            Write-Host "  Python $($found.Ver) installed successfully." -ForegroundColor Green
        }
    }
    if ($found) {
        $ChosenPyExe = $found.Exe
        $pyVersion   = $found.Ver
        Write-Host "  Selected Python $pyVersion via launcher: $ChosenPyExe" -ForegroundColor Green
    }
}

if (-not $ChosenPyExe) {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        Write-Err "No suitable Python found and auto-install failed."
        Write-Err "  Run manually: winget install Python.Python.3.12"
        Write-Err "  Or download:  https://python.org/downloads/"
        exit 1
    }
    $ChosenPyExe = $pyCmd.Source
    $pyVersion   = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    Write-Host "  Found Python $pyVersion at $ChosenPyExe" -ForegroundColor Green
    if ($pyVersion -lt "3.10" -or $pyVersion -gt "3.13") {
        Write-Warn "Python $pyVersion is outside the tested range (3.10-3.13)."
        Write-Warn "  Install Python 3.12 from https://python.org for full binary-wheel support."
    }
}

# --- 2. Virtual environment ----------------------------------------------
Write-Section "[2/7] Python virtual environment..."
$VenvPy = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if ((Test-Path $VenvPy) -and -not $Force) {
    Write-Skip ".venv\Scripts\python.exe"
} else {
    if (Test-Path ".venv") {
        Write-Warn ".venv exists but is incomplete - recreating."
        Remove-Item .venv -Recurse -Force
    }
    Write-Doing "Creating .venv with Python $pyVersion..."
    & $ChosenPyExe -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Failed to create venv."
        exit 1
    }
}

if (-not (Test-Path $VenvPy)) {
    Write-Err "Venv python interpreter missing at $VenvPy"
    exit 1
}

# --- 3. Python dependencies ---------------------------------------------
Write-Section "[3/7] Python dependencies..."
if (-not (Test-Path "requirements.txt")) {
    Write-Err "requirements.txt not found in $(Get-Location)."
    exit 1
}

# Hash requirements.txt; skip pip install if hash matches last successful run.
$ReqHash = (Get-FileHash -Algorithm SHA256 requirements.txt).Hash
$ReqStamp = ".venv\.requirements.sha256"
$NeedInstall = $true
if ((Test-Path $ReqStamp) -and -not $Force) {
    $prev = (Get-Content $ReqStamp -ErrorAction SilentlyContinue).Trim()
    if ($prev -eq $ReqHash) {
        Write-Skip "Python dependencies (requirements.txt unchanged since last install)"
        $NeedInstall = $false
    }
}
if ($NeedInstall) {
    Write-Doing "pip install -r requirements.txt"
    & $VenvPy -m pip install --upgrade pip setuptools wheel

    # llama-cpp-python compiles from source by default, which requires the MSVC
    # toolchain (Visual Studio Build Tools) on Windows. Attempt a pre-built
    # binary wheel first so the setup succeeds without a compiler.
    Write-Doing "Installing llama-cpp-python (pre-built binary - no compiler needed)..."
    & $VenvPy -m pip install llama-cpp-python --prefer-binary `
        --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
    $LlamaOk = $LASTEXITCODE -eq 0

    # Check CPU AVX2 support via Windows API BEFORE installing a wheel that
    # might crash at runtime (WinError 0xc000001d / STATUS_ILLEGAL_INSTRUCTION).
    # PF_AVX2_INSTRUCTIONS_AVAILABLE = 40 per Windows SDK ProcessorFeature enum.
    $HasAvx2 = $false
    $saved = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
    $avx2Out = (& $VenvPy -c @"
import ctypes, sys
try:
    has = ctypes.windll.kernel32.IsProcessorFeaturePresent(40)
    print('avx2' if has else 'noavx2')
except Exception:
    print('unknown')
"@ 2>&1)
    $ErrorActionPreference = $saved
    if ($avx2Out -match "avx2") { $HasAvx2 = $true }
    if ($avx2Out -match "noavx2") {
        Write-Warn "CPU does not support AVX2 — pre-built wheels require it."
        Write-Warn "Will build from source without AVX2 (requires Visual Studio Build Tools)."
    }

    if ($LlamaOk -and $HasAvx2) {
        Write-Host "  [ok]   CPU supports AVX2 — pre-built wheel is compatible." -ForegroundColor Green
    } elseif ($LlamaOk -and -not $HasAvx2) {
        # Pre-built would crash at runtime — uninstall and try source build.
        Write-Warn "Uninstalling AVX2 wheel and rebuilding without AVX2/AVX512..."
        & $VenvPy -m pip uninstall llama-cpp-python -y
        $LlamaOk = $false
    }

    if (-not $LlamaOk) {
        # Check for NMake / MSVC before attempting a source build that will fail.
        $NMakeFound = $null -ne (Get-Command nmake -ErrorAction SilentlyContinue)
        if (-not $NMakeFound) {
            # Use vswhere.exe (ships with VS Installer) to find vcvarsall.bat
            # for any VS / Build Tools installation regardless of install path.
            $VsWhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installerswhere.exe"
            $VcVarsPath = $null
            if (Test-Path $VsWhere) {
                $saved = $ErrorActionPreference; $ErrorActionPreference = 'SilentlyContinue'
                $VcVarsPath = (& $VsWhere -products "*" -latest -find "VC\Auxiliary\Build\vcvarsall.bat" 2>$null) | Select-Object -First 1
                $ErrorActionPreference = $saved
            }
            # Fallback: common paths for Build Tools 2022 and 2019
            if (-not $VcVarsPath) {
                foreach ($candidate in @(
                    "C:\Program Files (x86)\Microsoft Visual Studio�2\BuildTools\VC\Auxiliary\Buildcvarsall.bat",
                    "C:\Program Files\Microsoft Visual Studio�2\BuildTools\VC\Auxiliary\Buildcvarsall.bat",
                    "C:\Program Files (x86)\Microsoft Visual Studio�9\BuildTools\VC\Auxiliary\Buildcvarsall.bat"
                )) {
                    if (Test-Path $candidate) { $VcVarsPath = $candidate; break }
                }
            }
            if ($VcVarsPath) {
                Write-Doing "Initialising MSVC environment from: $VcVarsPath"
                cmd /c "`"$VcVarsPath`" x64 && set" |
                    Where-Object { $_ -match '=' } |
                    ForEach-Object { $v = $_.split('=', 2); [System.Environment]::SetEnvironmentVariable($v[0], $v[1]) }
                $NMakeFound = $null -ne (Get-Command nmake -ErrorAction SilentlyContinue)
            }
            if (-not $NMakeFound) {
                Write-Warn "NMake (MSVC) not found — cannot build llama-cpp-python from source."
                Write-Warn "  Install Visual Studio Build Tools, then re-run setup.ps1:"
                Write-Warn "    winget install Microsoft.VisualStudio.2022.BuildTools --silent --override `"--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended`""
                Write-Warn "  LLM inference disabled until then; all other features work."
            }
        }
        if ($NMakeFound) {
            Write-Doing "Building llama-cpp-python from source without AVX2/AVX512..."
            $env:CMAKE_ARGS = "-DLLAMA_AVX2=OFF -DLLAMA_AVX512=OFF"
            # --no-binary llama-cpp-python (not :all:) lets cmake + numpy use
            # their pre-built wheels; only llama itself is compiled from source.
            & $VenvPy -m pip install llama-cpp-python --no-binary llama-cpp-python
            Remove-Item Env:\CMAKE_ARGS -ErrorAction SilentlyContinue
            $LlamaOk = $LASTEXITCODE -eq 0
            if (-not $LlamaOk) {
                Write-Warn "Source build failed — see output above."
                Write-Warn "  LLM inference disabled until resolved; all other features work."
            }
        }
    }

    if ($LlamaOk) {
        # llama-cpp-python already installed; pip will skip it in the full install
        & $VenvPy -m pip install -r requirements.txt
    } else {
        # Install everything except llama-cpp-python to avoid a failed source build
        $TmpReqs = Join-Path $env:TEMP "friday_requirements_no_llama.txt"
        Get-Content requirements.txt |
            Where-Object { $_ -notmatch '^\s*llama-cpp-python' } |
            Set-Content $TmpReqs
        & $VenvPy -m pip install -r $TmpReqs
        Remove-Item $TmpReqs -Force -ErrorAction SilentlyContinue
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Err "pip install failed - inspect the log above and re-run."
        exit 1
    }
    Set-Content -Path $ReqStamp -Value $ReqHash
}

# --- 4. Playwright -------------------------------------------------------
Write-Section "[4/7] Playwright Chromium runtime..."
$playwrightCache = Join-Path $env:USERPROFILE "AppData\Local\ms-playwright"
$hasChromium = $false
if (Test-Path $playwrightCache) {
    if (Get-ChildItem -Path $playwrightCache -Filter "chromium-*" -Directory -ErrorAction SilentlyContinue) {
        $hasChromium = $true
    }
}
if ($SkipPlaywright) {
    Write-Host "  Skipped (-SkipPlaywright)." -ForegroundColor DarkGray
} elseif ($hasChromium -and -not $Force) {
    Write-Skip "Chromium for Playwright (in $playwrightCache)"
} else {
    Write-Doing "playwright install chromium"
    & $VenvPy -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "Playwright install failed. Run '$VenvPy -m playwright install chromium' manually later."
    }
}

# --- Helper: idempotent downloader (blank URL = skip, not error) ---------
function Download-IfMissing {
    param([string]$Dest, [string]$Url, [string]$Label)
    if ((Test-Path $Dest) -and -not $Force -and ((Get-Item $Dest).Length -gt 0)) {
        Write-Skip "$Label ($(Split-Path $Dest -Leaf))"
        return
    }
    if ([string]::IsNullOrWhiteSpace($Url)) {
        Write-Warn "${Label}: no download URL configured."
        Write-Warn "  Place the file at: $Dest"
        Write-Warn "  (set the URL at the top of setup.ps1 or via the matching env var)"
        return
    }
    Write-Doing "Downloading $Label..."
    try {
        $oldPref = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'  # ~10x faster large downloads
        Invoke-WebRequest -Uri $Url -OutFile $Dest
        $ProgressPreference = $oldPref
    } catch {
        Write-Warn "Failed to download $Url - $_"
        if (Test-Path $Dest) { Remove-Item $Dest -Force }
    }
}

# --- 5. Piper TTS engine + voice -----------------------------------------
Write-Section "[5/7] Piper TTS engine + voice..."
New-Item -ItemType Directory -Force -Path models | Out-Null
if (Test-Path "piper\piper.exe") {
    Write-Skip "Piper engine (piper\piper.exe)"
} else {
    Write-Doing "Downloading + extracting Piper engine (Windows amd64)..."
    try {
        $oldPref = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        $piperZip = Join-Path $env:TEMP "piper_windows_amd64.zip"
        Invoke-WebRequest -Uri $PiperZipUrl -OutFile $piperZip
        Expand-Archive -Path $piperZip -DestinationPath $ScriptDir -Force
        Remove-Item $piperZip -Force -ErrorAction SilentlyContinue
        $ProgressPreference = $oldPref
        if (-not (Test-Path "piper\piper.exe")) {
            Write-Warn "Piper extracted but piper.exe not found - check the archive layout."
        }
    } catch {
        Write-Warn "Piper engine download failed - $_"
        Write-Warn "  Download piper_windows_amd64.zip from https://github.com/rhasspy/piper/releases"
        Write-Warn "  and extract it into .\piper\ manually."
    }
}
Download-IfMissing -Dest "models\$PiperVoice.onnx"      -Url "$PiperVoiceBase/$PiperVoice.onnx?download=true"      -Label "Piper voice"
Download-IfMissing -Dest "models\$PiperVoice.onnx.json" -Url "$PiperVoiceBase/$PiperVoice.onnx.json?download=true" -Label "Piper voice config"

# --- 6. AI models --------------------------------------------------------
Write-Section "[6/7] Local AI models..."
New-Item -ItemType Directory -Force -Path logs, data, "data\chroma", models | Out-Null

if ($SkipModels) {
    Write-Host "  Skipped (-SkipModels)." -ForegroundColor DarkGray
} else {
    Download-IfMissing -Dest "models\$ChatModelFile"     -Url $ChatModelUrl     -Label "Chat model"
    Download-IfMissing -Dest "models\$ToolModelFile"     -Url $ToolModelUrl     -Label "Tool/planner model"
    Download-IfMissing -Dest "models\$VisionModelFile"   -Url $VisionModelUrl   -Label "SmolVLM2 vision model"
    Download-IfMissing -Dest "models\$VisionMmprojFile"  -Url $VisionMmprojUrl  -Label "SmolVLM2 multimodal projector"
    Download-IfMissing -Dest "models\$GemmaModelFile"    -Url $GemmaModelUrl    -Label "Gemma 2B router (optional)"

    # STT: faster-whisper base.en (HF cache)
    $whisperCache = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
    $hasWhisper = $false
    if (Test-Path $whisperCache) {
        if (Get-ChildItem -Path $whisperCache -Filter "models--Systran--faster-whisper-base*" -Directory -ErrorAction SilentlyContinue) {
            $hasWhisper = $true
        }
    }
    if ($hasWhisper -and -not $Force) {
        Write-Skip "Faster-Whisper base.en in HuggingFace cache"
    } elseif (Test-Path "scripts\download_stt_model.py") {
        Write-Doing "Downloading Faster-Whisper STT model..."
        & $VenvPy scripts\download_stt_model.py
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Whisper download failed - re-run scripts\download_stt_model.py later."
        }
    }
}

# --- 7. Optional wake-word autostart -------------------------------------
Write-Section "[7/7] Optional: 'Hey Friday' wake-word autostart"
Write-Host "  Wake word uses Porcupine. Get a free key at https://console.picovoice.ai/" -ForegroundColor DarkGray
Write-Host "  and put it in .env as FRIDAY_PORCUPINE_KEY=...  (no custom keyword? a built-in" -ForegroundColor DarkGray
Write-Host "  word like 'jarvis' is used automatically on this platform)." -ForegroundColor DarkGray
$startupBat = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\friday_wake.bat"
if (Test-Path $startupBat) {
    Write-Skip "Wake-word .bat already in Startup folder"
} elseif (Test-Path "modules\voice_io\register_wake.py") {
    $answer = Read-Host "  Register the wake-word service to start at login? [y/N]"
    if ($answer -match '^[Yy]') {
        if (-not $env:FRIDAY_PORCUPINE_KEY) {
            Write-Warn "FRIDAY_PORCUPINE_KEY env var is not set. The shortcut will be installed"
            Write-Warn "but the detector will not fire until you set it (in .env, or via"
            Write-Warn "System Properties -> Environment Variables)."
        }
        & $VenvPy "modules\voice_io\register_wake.py"
    } else {
        Write-Host "  Skipped. Run '$VenvPy modules\voice_io\register_wake.py' later if you change your mind." -ForegroundColor DarkGray
    }
}

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host "            Automated setup complete             " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "Before first launch, make sure these exist in models\:"
Write-Host "  $ChatModelFile, $ToolModelFile, $VisionModelFile"
Write-Host "  (any '[warn] no download URL configured' file must be placed manually)"
Write-Host ""
Write-Host "Then to start FRIDAY:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  python main.py            # Desktop HUD"
Write-Host "  python main.py --text     # Text CLI"
Write-Host "==================================================" -ForegroundColor Cyan
