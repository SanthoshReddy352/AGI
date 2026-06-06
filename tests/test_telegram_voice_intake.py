"""P1.4 — Telegram inbound dispatcher forks voice / audio / video_note handlers."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.comms.telegram import TelegramChannel, TelegramInbound


@pytest.fixture
def inbound():
    channel = TelegramChannel(token="fake", chat_id="12345")
    app = SimpleNamespace(telegram_turn_active=False, process_input=lambda *a, **k: "")
    return TelegramInbound(channel, app)


def _voice_update(kind: str, file_id: str = "abc"):
    return {
        "update_id": 1,
        "message": {
            "chat": {"id": 12345},
            kind: {"file_id": file_id},
        },
    }


def _text_update(text: str):
    return {
        "update_id": 1,
        "message": {"chat": {"id": 12345}, "text": text},
    }


# ----------------------------------------------------------------------
# Dispatch routing
# ----------------------------------------------------------------------

def test_voice_message_invokes_handler(inbound):
    with patch.object(inbound, "_handle_voice_note") as h:
        # patch threading.Thread so we call synchronously
        with patch("modules.comms.telegram.threading.Thread") as T:
            T.side_effect = lambda target, args, name, daemon: SimpleNamespace(
                start=lambda: target(*args)
            )
            inbound._dispatch(_voice_update("voice"))
    h.assert_called_once_with("abc")


def test_audio_message_invokes_handler(inbound):
    with patch.object(inbound, "_handle_voice_note") as h:
        with patch("modules.comms.telegram.threading.Thread") as T:
            T.side_effect = lambda target, args, name, daemon: SimpleNamespace(
                start=lambda: target(*args)
            )
            inbound._dispatch(_voice_update("audio"))
    h.assert_called_once_with("abc")


def test_video_note_message_invokes_handler(inbound):
    with patch.object(inbound, "_handle_voice_note") as h:
        with patch("modules.comms.telegram.threading.Thread") as T:
            T.side_effect = lambda target, args, name, daemon: SimpleNamespace(
                start=lambda: target(*args)
            )
            inbound._dispatch(_voice_update("video_note"))
    h.assert_called_once_with("abc")


def test_text_message_does_not_invoke_voice_handler(inbound):
    with patch.object(inbound, "_handle_voice_note") as h:
        inbound._dispatch(_text_update("hello"))
    h.assert_not_called()


def test_voice_from_wrong_chat_is_ignored(inbound):
    other = {
        "update_id": 2,
        "message": {
            "chat": {"id": 99999},   # mismatched chat
            "voice": {"file_id": "abc"},
        },
    }
    with patch.object(inbound, "_handle_voice_note") as h:
        inbound._dispatch(other)
    h.assert_not_called()


# ----------------------------------------------------------------------
# Transcription entrypoint (P3.20 contract)
# ----------------------------------------------------------------------

def test_handle_voice_note_uses_central_transcription(tmp_path, inbound, monkeypatch):
    """The new handler must delegate to core.transcription.transcribe_file."""
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"\x00\x01")
    # Stub the helpers the handler calls so we don't hit the network.
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp(
        {"result": {"file_path": "voice/path.ogg"}}
    ))
    monkeypatch.setattr("urllib.request.urlretrieve", lambda url, dest: dest)
    calls: list[str] = []

    def fake_transcribe(path, app=None):
        calls.append(path)
        return "open youtube"

    monkeypatch.setattr("core.transcription.transcribe_file", fake_transcribe)
    captured: list[str] = []
    monkeypatch.setattr(inbound, "_process", lambda t: captured.append(t))
    monkeypatch.setattr("tempfile.NamedTemporaryFile",
                        lambda suffix, delete: _FakeTmp(str(audio)))
    inbound._handle_voice_note(file_id="abc123")
    assert calls and captured == ["open youtube"]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        import json
        return json.dumps(self._data).encode()


class _FakeTmp:
    def __init__(self, path):
        self.name = path

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
