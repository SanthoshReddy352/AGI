"""P3.20 — single file-based transcription entrypoint."""
from types import SimpleNamespace

import pytest

from core import transcription


class _FakeEngine:
    def __init__(self, response: str = "hello world", raises: bool = False) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[str] = []

    def transcribe_audio_file(self, path: str) -> str:
        self.calls.append(path)
        if self.raises:
            raise RuntimeError("boom")
        return self.response


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "voice.ogg"
    p.write_bytes(b"\x00\x01\x02")
    return str(p)


def test_returns_empty_when_path_missing():
    assert transcription.transcribe_file("", app=None) == ""


def test_returns_empty_when_file_missing(tmp_path):
    assert transcription.transcribe_file(str(tmp_path / "nope.ogg")) == ""


def test_returns_empty_when_no_engine(audio_file):
    assert transcription.transcribe_file(audio_file, app=SimpleNamespace()) == ""


def test_uses_app_stt(audio_file):
    fake = _FakeEngine(response="hi")
    app = SimpleNamespace(stt=fake)
    assert transcription.transcribe_file(audio_file, app=app) == "hi"
    assert fake.calls == [audio_file]


def test_uses_app_stt_engine_alias(audio_file):
    fake = _FakeEngine(response="alt")
    app = SimpleNamespace(stt_engine=fake)
    assert transcription.transcribe_file(audio_file, app=app) == "alt"


def test_strips_whitespace(audio_file):
    fake = _FakeEngine(response="  hello  \n")
    app = SimpleNamespace(stt=fake)
    assert transcription.transcribe_file(audio_file, app=app) == "hello"


def test_engine_exception_swallowed(audio_file):
    fake = _FakeEngine(raises=True)
    app = SimpleNamespace(stt=fake)
    assert transcription.transcribe_file(audio_file, app=app) == ""


def test_prefers_stt_over_other_attrs(audio_file):
    primary = _FakeEngine(response="primary")
    backup = _FakeEngine(response="backup")
    app = SimpleNamespace(stt=primary, stt_engine=backup)
    assert transcription.transcribe_file(audio_file, app=app) == "primary"
