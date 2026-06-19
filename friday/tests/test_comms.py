"""Wave 5a — Telegram + Discord channels and the send_notification tool."""
from __future__ import annotations

import pytest

from friday.comms.discord import DiscordChannel
from friday.comms.manager import CommsManager
from friday.comms.telegram import TelegramChannel, TelegramInbound, _chunk, _markdown_to_telegram_html
from friday.core.tools import ToolRegistry
from friday.tools import comms as comms_tool
from friday.tools import load_tools


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


# ── channels ──────────────────────────────────────────────────────────────────

def test_send_notification_registered(reg):
    assert "send_notification" in reg


def test_telegram_unavailable_without_tokens():
    assert TelegramChannel(token="", chat_id="").available is False


def test_telegram_available_with_tokens():
    assert TelegramChannel(token="t", chat_id="c").available is True


def test_telegram_send_skipped_when_unavailable():
    assert TelegramChannel(token="", chat_id="").send("hi") is False


def test_markdown_to_html():
    out = _markdown_to_telegram_html("**bold** *it* `code` <x>")
    assert "<b>bold</b>" in out and "<i>it</i>" in out and "<code>code</code>" in out
    assert "&lt;x&gt;" in out  # escaped


def test_chunk_splits_long_text():
    chunks = _chunk("a" * 9000)
    assert len(chunks) >= 3 and all(len(c) <= 3800 for c in chunks)


def test_discord_unavailable_without_url():
    assert DiscordChannel(webhook_url="").available is False


# ── inbound bridge ────────────────────────────────────────────────────────────

def test_inbound_routes_text_to_callback():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True  # capture replies synchronously
    seen = []

    def on_msg(text, session_id, mode, askpass=None, model=None):
        seen.append((text, mode))
        return f"echo: {text}", "sess-1"

    inbound = TelegramInbound(ch, on_msg)
    inbound._process("hello friday")
    assert seen == [("hello friday", "agent")] and sent == ["echo: hello friday"]
    assert inbound._session_id == "sess-1"  # session persists


def test_inbound_shell_command():
    ch = TelegramChannel(token="t", chat_id="42")
    ch.send = lambda text: True
    seen = []
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: (seen.append(t) or "ok", s))
    inbound._process("!df -h")
    assert seen and "df -h" in seen[0] and "run_shell" in seen[0]


def test_inbound_mode_command():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", s))
    assert inbound._handle_command("/mode chat") is True
    assert inbound._mode == "chat"


def test_inbound_model_picker_flow():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    models = [{"id": "opus", "label": "Claude Opus"}, {"id": "gpt", "label": "GPT-5.5"}]
    used = []
    inbound = TelegramInbound(
        ch, lambda t, s, m, a=None, model=None: (used.append(model) or "ok", "sess-1"),
        get_models=lambda: models)

    # /model lists the models numbered, with a Cancel option, and opens the picker.
    assert inbound._handle_command("/model") is True
    menu = sent[-1]
    assert "1. Claude Opus" in menu and "2. GPT-5.5" in menu and "0. Cancel" in menu
    assert inbound._pending_models == models

    # A bad choice re-prompts and keeps the picker open.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "9"}})
    assert inbound._pending_models == models and "isn't on the list" in sent[-1]

    # A non-number also re-prompts.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "blah"}})
    assert inbound._pending_models == models and "isn't a number" in sent[-1]

    # A valid choice switches the model and starts a fresh session.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "2"}})
    assert inbound._pending_models is None
    assert inbound._model_id == "gpt" and inbound._session_id is None
    assert "Switched to GPT-5.5" in sent[-1]

    # The chosen model is now passed on every turn.
    inbound._process("hello")
    assert used[-1] == "gpt"


def test_inbound_model_cancel():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("ok", s),
                              get_models=lambda: [{"id": "x", "label": "X"}])
    inbound._handle_command("/model")
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "0"}})
    assert inbound._pending_models is None and inbound._model_id is None
    assert "keeping the current model" in sent[-1].lower()


def test_inbound_ignores_wrong_chat():
    ch = TelegramChannel(token="t", chat_id="42")
    calls = []
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: (calls.append(t) or "x", s))
    inbound._dispatch({"message": {"chat": {"id": 999}, "text": "hi"}})
    assert calls == []


def test_inbound_askpass_captures_password():
    ch = TelegramChannel(token="t", chat_id="42")
    sent, deleted = [], []
    ch.send = lambda text: sent.append(text) or True
    ch._post = lambda method, body: deleted.append((method, body)) or {"ok": True}
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("ok", s))

    import threading
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("pw", inbound.askpass("Enter your sudo password")))
    t.start()
    # Wait until the prompt is sent / pending request registered.
    import time
    for _ in range(50):
        if inbound._pw_event is not None:
            break
        time.sleep(0.01)
    # The next message is treated as the password (not a turn) and deleted.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "s3cret", "message_id": 9}})
    t.join(timeout=2)
    assert result["pw"] == "s3cret"
    assert any(m == "deleteMessage" for m, _ in deleted)  # password scrubbed
    assert any("🔒" in s for s in sent)                    # prompt was shown


# ── manager ───────────────────────────────────────────────────────────────────

def test_manager_routes_to_named_channel():
    tg = TelegramChannel(token="t", chat_id="c")
    dc = DiscordChannel(webhook_url="")
    tg_sent = []
    tg._send_sync = lambda text, reply_to=None: tg_sent.append(text)
    mgr = CommsManager(telegram=tg, discord=dc)
    assert mgr.channels() == ["telegram"]
    assert mgr.send("hey", channel="telegram") is True
    assert tg_sent == ["hey"]


# ── tool ──────────────────────────────────────────────────────────────────────

def test_send_notification_no_channels(reg, monkeypatch):
    monkeypatch.setattr(comms_tool, "TelegramChannel", lambda: TelegramChannel(token="", chat_id=""))
    monkeypatch.setattr(comms_tool, "DiscordChannel", lambda: DiscordChannel(webhook_url=""))
    r = reg.execute("send_notification", {"message": "hi"})
    assert not r.ok and "no channels" in r.error


def test_send_notification_sends(reg, monkeypatch):
    tg = TelegramChannel(token="t", chat_id="c")
    sent = []
    tg._send_sync = lambda text, reply_to=None: sent.append(text)
    monkeypatch.setattr(comms_tool, "TelegramChannel", lambda: tg)
    monkeypatch.setattr(comms_tool, "DiscordChannel", lambda: DiscordChannel(webhook_url=""))
    r = reg.execute("send_notification", {"message": "deploy done", "channel": "telegram"})
    assert r.ok and "telegram" in r.content and sent == ["deploy done"]


# ── inbound: command menu, replies, voice ───────────────────────────────────────

def _recording_channel():
    ch = TelegramChannel(token="t", chat_id="42")
    calls = []
    ch._post = lambda method, body, timeout=10: (
        calls.append((method, body)) or {"ok": True, "result": {"message_id": 99}})
    return ch, calls


def test_inbound_registers_command_menu():
    ch, calls = _recording_channel()
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", s))
    inbound._register_commands()
    setcmds = [b for meth, b in calls if meth == "setMyCommands"]
    assert setcmds and any(c["command"] == "help" for c in setcmds[0]["commands"])


def test_inbound_reply_quotes_user_message():
    ch, calls = _recording_channel()
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("the answer", "sess"))
    inbound._reply_turn("hi", reply_to=5)
    # The answer is sent ONCE as a reply quoting the user's message — no edits/placeholder.
    sends = [b for meth, b in calls if meth == "sendMessage"]
    assert sends and sends[0]["reply_parameters"]["message_id"] == 5
    assert "the answer" in sends[0]["text"]
    assert not [m for m, _ in calls if m == "editMessageText"]


def test_inbound_voice_transcribes_and_answers(monkeypatch):
    ch, calls = _recording_channel()
    seen = []
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: (seen.append(t) or "ok", s))
    monkeypatch.setattr(inbound, "_download", lambda v: "/tmp/voice.oga")
    monkeypatch.setattr("friday.comms.transcribe.transcribe_audio", lambda p: "what's the time")
    inbound._process_voice({"file_id": "v1"}, "", reply_to=7)
    assert seen == ["what's the time"]


def test_inbound_voice_without_stt_replies_gracefully(monkeypatch):
    ch, calls = _recording_channel()
    sent = []
    ch.send = lambda text, reply_to=None: sent.append(text) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", s))
    monkeypatch.setattr(inbound, "_download", lambda v: "/tmp/voice.oga")
    monkeypatch.setattr("friday.comms.transcribe.transcribe_audio", lambda p: None)
    inbound._process_voice({"file_id": "v1"}, "", reply_to=7)
    assert sent and "transcription isn't set up" in sent[0]
