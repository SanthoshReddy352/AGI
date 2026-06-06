"""P3.19 — voice mode toggle (TTS mute/unmute).

Distinct from the existing ``set_voice_mode`` capability (which switches
the LISTENING mode: persistent / wake-word / on-demand / manual). This
module governs the SPEAKING side: whether FRIDAY produces audio at all,
and an optional timed mute.

State is persisted to ``data/runtime_state.json`` so a restart respects
the most recent decision.

Public surface:
    - ``VoiceModeController(app, state_path).set(state, duration_minutes=None)``
    - ``VoiceModeController.is_muted()`` — also clears expired timed mutes
    - factory ``make_voice_mode_controller(app)``
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from core.logger import logger


_VALID_STATES = {"on", "off", "mute", "unmute", "text_only", "voice"}


def _default_state_path() -> str:
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(project_root, "data", "runtime_state.json")


def _load(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(path: str, data: dict) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning("[voice_mode] persist failed: %s", exc)


class VoiceModeController:
    """Owns the ``tts_muted`` flag on ``app`` and the persisted state."""

    def __init__(self, app: Any, state_path: str | None = None,
                 clock=time.monotonic) -> None:
        self._app = app
        self._path = state_path or _default_state_path()
        self._clock = clock
        self._lock = threading.Lock()
        self._mute_until: float | None = None
        self._load_state()

    def _load_state(self) -> None:
        data = _load(self._path)
        voice = data.get("voice") if isinstance(data, dict) else None
        if not isinstance(voice, dict):
            self._apply(muted=False, until=None)
            return
        muted = bool(voice.get("muted"))
        until_iso = voice.get("muted_until_monotonic")
        until: float | None = None
        if isinstance(until_iso, (int, float)):
            # Stored value is wall-clock seconds (epoch); reduce to monotonic
            # delta. After a restart we can't carry the monotonic clock —
            # treat any future epoch as an indefinite mute.
            now_wall = time.time()
            if until_iso > now_wall:
                # Approximate: schedule the same delta from current monotonic.
                until = self._clock() + (until_iso - now_wall)
            else:
                muted = False
        self._apply(muted=muted, until=until)

    def _apply(self, muted: bool, until: float | None) -> None:
        with self._lock:
            self._mute_until = until
        try:
            setattr(self._app, "tts_muted", bool(muted))
        except Exception:
            pass
        # Persist with wall-clock epoch so future restarts can compare.
        payload = {"voice": {"muted": bool(muted)}}
        if until is not None:
            payload["voice"]["muted_until_monotonic"] = time.time() + (until - self._clock())
        _save(self._path, payload)

    def set(self, state: str, duration_minutes: int | float | None = None) -> str:
        """Apply a state. Returns a short human message for the user."""
        s = (state or "").strip().lower().replace("-", "_").replace(" ", "_")
        if s not in _VALID_STATES:
            return f"I don't recognize voice mode '{state}'."
        muting = s in {"off", "mute", "text_only"}
        until: float | None = None
        if muting and duration_minutes:
            try:
                seconds = float(duration_minutes) * 60.0
            except (TypeError, ValueError):
                seconds = 0.0
            if seconds > 0:
                until = self._clock() + seconds
        self._apply(muted=muting, until=until)
        if muting:
            if duration_minutes:
                return f"Muted for {int(duration_minutes)} minute(s). Say 'speak again' to unmute."
            return "Voice muted. Say 'speak again' to unmute."
        return "Voice unmuted. I'll speak again."

    def is_muted(self) -> bool:
        """Returns the current muted state, clearing an expired timer."""
        with self._lock:
            until = self._mute_until
        if until is not None and self._clock() >= until:
            self._apply(muted=False, until=None)
            return False
        return bool(getattr(self._app, "tts_muted", False))


def make_voice_mode_controller(app: Any, state_path: str | None = None,
                               clock=time.monotonic) -> VoiceModeController:
    return VoiceModeController(app, state_path=state_path, clock=clock)
