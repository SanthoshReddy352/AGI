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
    ch._send_sync = lambda text: sent.append(text)  # capture replies synchronously
    seen = []

    def on_msg(text):
        seen.append(text)
        return f"echo: {text}"

    inbound = TelegramInbound(ch, on_msg)
    inbound._process("hello friday")
    assert seen == ["hello friday"] and sent == ["echo: hello friday"]


def test_inbound_ignores_wrong_chat():
    ch = TelegramChannel(token="t", chat_id="42")
    calls = []
    inbound = TelegramInbound(ch, lambda t: calls.append(t) or "x")
    inbound._dispatch({"message": {"chat": {"id": 999}, "text": "hi"}})
    assert calls == []


# ── manager ───────────────────────────────────────────────────────────────────

def test_manager_routes_to_named_channel():
    tg = TelegramChannel(token="t", chat_id="c")
    dc = DiscordChannel(webhook_url="")
    tg_sent = []
    tg._send_sync = lambda text: tg_sent.append(text)
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
    tg._send_sync = lambda text: sent.append(text)
    monkeypatch.setattr(comms_tool, "TelegramChannel", lambda: tg)
    monkeypatch.setattr(comms_tool, "DiscordChannel", lambda: DiscordChannel(webhook_url=""))
    r = reg.execute("send_notification", {"message": "deploy done", "channel": "telegram"})
    assert r.ok and "telegram" in r.content and sent == ["deploy done"]
