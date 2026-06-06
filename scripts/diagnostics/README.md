# Diagnostic scripts

Standalone hardware/runtime checks for debugging an installation. These are
**not** part of the automated `pytest` suite — run them by hand when you are
diagnosing a specific subsystem.

| Script | Checks | Run |
|---|---|---|
| `audio_tone_check.py` | Output device + plays a 440 Hz tone via `sounddevice` | `python scripts/diagnostics/audio_tone_check.py` |
| `piper_tts_check.py` | Piper binary + voice model are present and can synthesize | `python scripts/diagnostics/piper_tts_check.py` |
| `tts_runtime_check.py` | `TextToSpeech` runtime preparation paths resolve | `python scripts/diagnostics/tts_runtime_check.py` |
| `kokoro_tts_check.py` | Kokoro TTS speak / chunked-speak / interruption | `python scripts/diagnostics/kokoro_tts_check.py` |
| `routing_smoke_check.py` | Full-app boot + a calendar turn through the v2 orchestrator | `python scripts/diagnostics/routing_smoke_check.py` |

> Some scripts boot the full app or touch audio hardware. Run them inside the
> project virtualenv (`.venv`) with your models already downloaded.
