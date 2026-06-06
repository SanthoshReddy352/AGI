import pvporcupine
from pvrecorder import PvRecorder
import sys
import os
import subprocess
import time
import platform
from datetime import datetime
from dotenv import load_dotenv

from wake_keyword import resolve_keyword

# Config
load_dotenv()
ACCESS_KEY = os.environ.get("FRIDAY_PORCUPINE_KEY", "")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Resolve the keyword cross-platform: the bundled "Hey Friday" .ppn when one
# exists for this OS, otherwise a built-in pvporcupine keyword (ships for every
# platform) so the launcher works out of the box on Windows/macOS too.
KEYWORD_FILE_PATH, KEYWORD_LABEL, _IS_CUSTOM = resolve_keyword()
FRIDAY_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def _venv_python() -> str:
    """Return the project's venv python interpreter for the current OS."""
    if platform.system().lower() == "windows":
        candidate = os.path.join(FRIDAY_DIR, ".venv", "Scripts", "python.exe")
    else:
        candidate = os.path.join(FRIDAY_DIR, ".venv", "bin", "python3")
    return candidate if os.path.exists(candidate) else sys.executable


VENV_PYTHON = _venv_python()
MAIN_PY = os.path.join(FRIDAY_DIR, "main.py")
LOG_FILE = os.path.join(FRIDAY_DIR, "logs", "wake_detector.log")

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"[{timestamp}] {message}"
    print(msg)
    try:
        # Subprocess output may include any locale; force utf-8 with replace
        # so log writes never raise on Windows codepage encoding errors.
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def is_friday_running():
    """Return True when a FRIDAY main.py process is already alive.

    Uses tasklist on Windows and ps on POSIX. Either failure path is treated
    as "unknown" — we err on the side of False so the wake detector keeps
    listening rather than getting stuck believing FRIDAY is running.
    """
    try:
        if platform.system().lower() == "windows":
            # tasklist /v emits CSV; cheaper to just look at command lines via wmic
            # but wmic is deprecated on 10+. Use tasklist with /FO LIST.
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/V"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            return "main.py" in result.stdout
        result = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        for line in result.stdout.splitlines():
            if "main.py" in line and "Friday" in line:
                return True
    except Exception as e:
        log(f"Error checking if FRIDAY is running: {e}")
    return False

def launch_friday():
    log("Wake word detected — launching FRIDAY...")
    try:
        popen_kwargs = dict(
            cwd=FRIDAY_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if platform.system().lower() == "windows":
            popen_kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen([VENV_PYTHON, MAIN_PY], **popen_kwargs)
        log("FRIDAY process started.")
    except Exception as e:
        log(f"Failed to launch FRIDAY: {e}")

def main():
    porcupine = None
    recorder = None
    is_listening = False

    log("Wake word detector service starting...")
    if not ACCESS_KEY:
        log("FRIDAY_PORCUPINE_KEY not set — wake detector cannot start. "
            "Export your Picovoice access key in the environment.")
        sys.exit(1)
    if not KEYWORD_FILE_PATH or not os.path.exists(KEYWORD_FILE_PATH):
        log(f"Wake keyword file missing: {KEYWORD_FILE_PATH}. "
            "Install the wake-word extras (pip install pvporcupine pvrecorder).")
        sys.exit(1)

    log(f"Wake phrase: '{KEYWORD_LABEL}' (keyword file: {os.path.basename(KEYWORD_FILE_PATH)})")

    try:
        porcupine = pvporcupine.create(
            access_key=ACCESS_KEY,
            keyword_paths=[KEYWORD_FILE_PATH]
        )

        # device_index=-1 selects the system default microphone. Hardcoding a
        # specific index breaks on machines where the mic enumerates elsewhere;
        # override with FRIDAY_WAKE_MIC_INDEX when a specific device is needed.
        mic_index = int(os.environ.get("FRIDAY_WAKE_MIC_INDEX", "-1"))
        recorder = PvRecorder(device_index=mic_index, frame_length=porcupine.frame_length)
        
        while True:
            if is_friday_running():
                if is_listening:
                    log("FRIDAY is running. Releasing microphone...")
                    recorder.stop()
                    is_listening = False
                time.sleep(5)
                continue
            
            if not is_listening:
                log("FRIDAY is not running. Acquiring microphone...")
                recorder.start()
                is_listening = True

            audio_frame = recorder.read()
            keyword_index = porcupine.process(audio_frame)
            
            if keyword_index == 0:
                launch_friday()
                # Wait a bit for the process to appear in ps aux
                time.sleep(3)

    except KeyboardInterrupt:
        log("Shutdown requested via KeyboardInterrupt.")
    except Exception as e:
        log(f"Fatal error in detector: {e}")
    finally:
        if recorder is not None:
            if is_listening:
                recorder.stop()
            recorder.delete()
        if porcupine is not None:
            porcupine.delete()
        log("Wake word detector service stopped.")
        sys.exit(0)

if __name__ == '__main__':
    main()