"""Telegram channel — outbound notifications + an inbound chat bridge.

Stdlib-only (urllib). Tokens live in the environment, never in config:
  FRIDAY_TELEGRAM_TOKEN, FRIDAY_TELEGRAM_CHAT_ID

Outbound: :meth:`TelegramChannel.send` (async, markdown→Telegram HTML, chunked).
Inbound:  :class:`TelegramInbound` long-polls getUpdates and routes each text
message through an ``on_message(text) -> reply`` callback, replying in-chat.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.request
from html import escape as _html_escape
from typing import Callable, Optional

from friday.core.logger import logger

_MAX_CHARS = 3800  # safe margin under Telegram's 4096 limit
_API = "https://api.telegram.org/bot{token}/{method}"


def _markdown_to_telegram_html(text: str) -> str:
    """Telegram HTML accepts a small tag set; escape then re-introduce **bold**,
    *italic*, `code` so the chat doesn't leak literal asterisks."""
    out = _html_escape(text)
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out, flags=re.DOTALL)
    out = re.sub(r"(?<![\*\w])\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", out)
    out = re.sub(r"`([^`]+?)`", r"<code>\1</code>", out)
    return out


def _chunk(text: str, limit: int = _MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        window = text[:limit]
        cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
        cut = cut + 1 if cut > 0 else limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


class TelegramChannel:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self._token = token if token is not None else os.environ.get("FRIDAY_TELEGRAM_TOKEN", "")
        self._chat_id = chat_id if chat_id is not None else os.environ.get("FRIDAY_TELEGRAM_CHAT_ID", "")
        self._available = bool(self._token and self._chat_id)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str) -> bool:
        """Dispatch a message on a background thread. Returns True if dispatched."""
        if not self.available or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text,), daemon=True).start()
        return True

    def _post(self, method: str, body: dict, timeout: int = 10) -> dict:
        req = urllib.request.Request(
            _API.format(token=self._token, method=method),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp)

    def _send_sync(self, text: str) -> None:
        for chunk in _chunk(text):
            try:
                result = self._post("sendMessage", {
                    "chat_id": self._chat_id,
                    "text": _markdown_to_telegram_html(chunk),
                    "parse_mode": "HTML",
                })
                if not result.get("ok"):
                    logger.warning("[telegram] send failed: %s", result.get("description"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[telegram] send error: %s", exc)


class TelegramInbound:
    """Long-poll the bot and route text messages through ``on_message``."""

    _POLL_TIMEOUT = 20

    def __init__(self, channel: TelegramChannel, on_message: Callable[[str], str]):
        self._channel = channel
        self._on_message = on_message
        self._offset = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not self._channel.available or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="TelegramInbound", daemon=True)
        self._thread.start()
        logger.info("[telegram] inbound polling started")

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                for update in self._get_updates():
                    self._dispatch(update)
                backoff = 1
            except (TimeoutError, OSError):
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("[telegram] poll error: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 15)

    def _get_updates(self) -> list:
        url = _API.format(token=self._channel._token, method="getUpdates") + (
            f"?offset={self._offset}&timeout={self._POLL_TIMEOUT}&allowed_updates=message"
        )
        with urllib.request.urlopen(url, timeout=self._POLL_TIMEOUT + 10) as resp:  # noqa: S310
            data = json.load(resp)
        if not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    def _dispatch(self, update: dict) -> None:
        message = update.get("message") or {}
        if str(message.get("chat", {}).get("id", "")) != self._channel._chat_id:
            return  # only the authorized chat
        text = (message.get("text") or "").strip()
        if not text:
            return
        if text.lower() in ("/start", "/help"):
            self._channel.send("Hi! I'm FRIDAY. Send me a message and I'll get to work.")
            return
        threading.Thread(target=self._process, args=(text,), daemon=True).start()

    def _process(self, text: str) -> None:
        try:
            reply = self._on_message(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] turn failed: %s", exc)
            reply = "Sorry — something went wrong handling that."
        self._channel.send(reply or "(no response)")
