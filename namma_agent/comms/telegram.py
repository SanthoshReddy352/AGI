"""Telegram channel — outbound notifications + an inbound chat bridge.

Stdlib-only (urllib). Tokens live in the environment, never in config:
  NAMMA_TELEGRAM_TOKEN, NAMMA_TELEGRAM_CHAT_ID

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

from namma_agent.core.logger import logger

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
        self._token = token if token is not None else os.environ.get("NAMMA_TELEGRAM_TOKEN", "")
        self._chat_id = chat_id if chat_id is not None else os.environ.get("NAMMA_TELEGRAM_CHAT_ID", "")
        self._available = bool(self._token and self._chat_id)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str, reply_to: Optional[int] = None) -> bool:
        """Dispatch a message on a background thread. Returns True if dispatched.
        ``reply_to`` makes the message quote/point at the user's message id."""
        if not self.available or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text, reply_to), daemon=True).start()
        return True

    def send_chat_action(self, action: str = "typing") -> None:
        """Show the '<name> is typing…' status at the top of the chat (best-effort).
        Expires after ~5s, so callers refresh it on a heartbeat."""
        if not self.available:
            return
        try:
            self._post("sendChatAction", {"chat_id": self._chat_id, "action": action})
        except Exception:  # noqa: BLE001
            pass

    def _post(self, method: str, body: dict, timeout: int = 10) -> dict:
        req = urllib.request.Request(
            _API.format(token=self._token, method=method),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp)

    def _send_sync(self, text: str, reply_to: Optional[int] = None) -> None:
        for chunk in _chunk(text):
            try:
                body = {
                    "chat_id": self._chat_id,
                    "text": _markdown_to_telegram_html(chunk),
                    "parse_mode": "HTML",
                }
                if reply_to:
                    body["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
                result = self._post("sendMessage", body)
                if not result.get("ok"):
                    logger.warning("[telegram] send failed: %s", result.get("description"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[telegram] send error: %s", exc)
            reply_to = None  # only the first chunk quotes the user's message


_HELP = (
    "{name} commands:\n"
    "• plain text — I handle it (agent mode by default)\n"
    "• 🎤 voice message — I'll transcribe and answer it\n"
    "• !<cmd> — run a shell command, e.g. !df -h\n"
    "• /mode chat|agent — switch mode\n"
    "• /model — switch the AI model (pick by number)\n"
    "• /new — start a fresh conversation\n"
    "• /clear — wipe my memory\n"
    "• send a document — I'll read it\n"
    "• /help — this message"
)

# Registered with Telegram so the in-app "/" button shows a command menu w/ tooltips.
_BOT_COMMANDS = [
    {"command": "help", "description": "Show what I can do"},
    {"command": "new", "description": "Start a fresh conversation"},
    {"command": "mode", "description": "Switch mode — /mode chat or /mode agent"},
    {"command": "model", "description": "Switch the AI model (pick by number)"},
    {"command": "clear", "description": "Wipe my memory"},
]


class _TypingStatus:
    """The standard Telegram '<name> is typing…' indicator at the top of the chat,
    kept alive on a daemon heartbeat while a turn runs (the action expires after ~5s).
    No in-chat placeholder, no streaming — just the subtle top status."""

    def __init__(self, channel: "TelegramChannel"):
        self._ch = channel
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="TelegramTyping", daemon=True)

    def start(self) -> "_TypingStatus":
        self._ch.send_chat_action("typing")   # show it immediately
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(4.0):        # refresh before the ~5s TTL lapses
            self._ch.send_chat_action("typing")

    def stop(self) -> None:
        self._stop.set()


class TelegramInbound:
    """Long-poll the bot and route messages (text, voice, /commands, !shell, documents).

    ``on_message(text, session_id, mode, askpass=None) -> (reply, session_id)`` runs one
    turn and returns the reply plus the (possibly new) session id so the chat keeps
    context. The answer is delivered once as a reply to the user's message."""

    _POLL_TIMEOUT = 20

    def __init__(self, channel: TelegramChannel,
                 on_message: Callable[..., tuple],  # (text, session_id, mode, askpass, model) -> (reply, sid)
                 get_models: Optional[Callable[[], list]] = None):
        self._channel = channel
        self._on_message = on_message
        # Returns the configured model profiles (for the /model picker). Optional
        # so older callers / tests still work (no picker → /model says none set).
        self._get_models = get_models or (lambda: [])
        self._offset = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._session_id: Optional[str] = None
        self._mode = "agent"
        self._model_id: Optional[str] = None       # chosen brain (None = default)
        self._pending_models: Optional[list] = None  # set while awaiting a number
        # Pending sudo-password request (set while a turn waits for a reply).
        self._pw_lock = threading.Lock()
        self._pw_event: Optional[threading.Event] = None
        self._pw_value: Optional[str] = None

    def start(self) -> None:
        if not self._channel.available or self._thread is not None:
            return
        self._register_commands()  # populate the in-app "/" command menu
        self._thread = threading.Thread(target=self._loop, name="TelegramInbound", daemon=True)
        self._thread.start()
        logger.info("[telegram] inbound polling started")

    def _register_commands(self) -> None:
        """Register the bot's slash-command menu so Telegram shows the "/" tooltips."""
        try:
            self._channel._post("setMyCommands", {"commands": _BOT_COMMANDS})
        except Exception as exc:  # noqa: BLE001
            logger.debug("[telegram] setMyCommands failed: %s", exc)

    def _send_reply(self, text: str, reply_to: Optional[int]) -> None:
        """Send the answer synchronously as a reply to the user's message (chunk-aware;
        only the first chunk quotes it)."""
        for i, chunk in enumerate(_chunk(text)):
            try:
                body = {"chat_id": self._channel._chat_id,
                        "text": _markdown_to_telegram_html(chunk), "parse_mode": "HTML"}
                if i == 0 and reply_to:
                    body["reply_parameters"] = {"message_id": reply_to,
                                                "allow_sending_without_reply": True}
                self._channel._post("sendMessage", body)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[telegram] reply send failed: %s", exc)

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
            f"?offset={self._offset}&timeout={self._POLL_TIMEOUT}"
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
        msg_id = message.get("message_id")
        document = message.get("document")
        voice = message.get("voice") or message.get("audio")  # voice note or audio file
        caption = (message.get("caption") or "").strip()
        text = (message.get("text") or "").strip()
        # If a turn is waiting for a sudo password, this message IS the password.
        if text and self._pw_event is not None:
            self._capture_password(text, msg_id)
            return
        if voice:
            threading.Thread(target=self._process_voice, args=(voice, caption, msg_id),
                             daemon=True).start()
            return
        if document:
            threading.Thread(target=self._process_document, args=(document, caption, msg_id),
                             daemon=True).start()
            return
        if not text:
            return
        # A /model picker is open → this message is the user's number choice.
        if self._pending_models is not None and not text.startswith("/"):
            self._handle_model_selection(text)
            return
        if self._handle_command(text):
            return
        threading.Thread(target=self._process, args=(text, msg_id), daemon=True).start()

    # -- sudo askpass (in-chat, password deleted after use) ----------------

    def askpass(self, prompt: str) -> Optional[str]:
        """Ask for the sudo password in chat and wait for the reply (one at a time).
        The reply is captured, deleted from the chat, and returned — never logged."""
        ev = threading.Event()
        with self._pw_lock:
            if self._pw_event is not None:
                return None  # already prompting
            self._pw_event, self._pw_value = ev, None
        self._channel.send(f"🔒 {prompt}\nReply with your sudo password — I'll delete it right after.")
        got = ev.wait(timeout=120)
        with self._pw_lock:
            value, self._pw_event, self._pw_value = self._pw_value, None, None
        return value if got else None

    def _capture_password(self, text: str, message_id) -> None:
        with self._pw_lock:
            self._pw_value = text
            ev = self._pw_event
        self._delete_message(message_id)  # scrub the password from chat history
        if ev:
            ev.set()

    def _delete_message(self, message_id) -> None:
        if not message_id:
            return
        try:
            self._channel._post("deleteMessage",
                                {"chat_id": self._channel._chat_id, "message_id": message_id})
        except Exception:  # noqa: BLE001
            pass

    # -- commands ----------------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Handle /commands locally. Returns True if consumed."""
        low = text.lower()
        if low in ("/start", "/help"):
            from namma_agent.config import assistant_name
            self._channel.send(_HELP.replace("{name}", assistant_name()))
            return True
        if low == "/new":
            self._session_id = None
            self._channel.send("Started a fresh conversation.")
            return True
        if low == "/mode" or low.startswith("/mode "):
            arg = text[5:].strip().lower()
            if arg in ("chat", "agent"):
                self._mode = arg
                self._channel.send(f"Mode set to {arg}.")
            else:
                self._channel.send(f"Current mode: {self._mode}. Use /mode chat or /mode agent.")
            return True
        if low == "/model":
            self._show_model_menu()
            return True
        if low == "/clear":
            self._run_turn("Clear all of my memory.")
            return True
        # Unknown /command → let the agent interpret it.
        return False

    # -- model switching (numbered picker) ---------------------------------

    def _show_model_menu(self) -> None:
        """List the configured models numbered, and wait for a number reply."""
        models = list(self._get_models() or [])
        if not models:
            self._channel.send(
                "No models are configured yet. Add some in Settings → Models, "
                "then use /model to switch.")
            return
        lines = ["Pick a model — reply with its number:", ""]
        for i, m in enumerate(models, start=1):
            current = " ✅ (current)" if m.get("id") == self._model_id else ""
            label = m.get("label") or m.get("model") or m.get("id")
            lines.append(f"{i}. {label}{current}")
        # 0 is always Cancel; mark the default brain too when nothing is overridden.
        default_mark = " ✅ (current)" if self._model_id is None else ""
        lines.append(f"\n0. Cancel{default_mark}")
        self._pending_models = models
        self._channel.send("\n".join(lines))

    def _handle_model_selection(self, text: str) -> None:
        """Validate the number the user replied with. Re-prompt on bad input;
        0 cancels; a valid number switches the model and starts a fresh chat."""
        models = self._pending_models or []
        choice = text.strip()
        if choice.lower() in ("cancel", "stop", "abort"):
            choice = "0"
        if not choice.lstrip("-").isdigit():
            self._channel.send(
                f"That isn't a number. Reply with 1–{len(models)} to choose, or 0 to cancel.")
            return  # keep the picker open — prompt again
        n = int(choice)
        if n == 0:
            self._pending_models = None
            self._channel.send("Okay — keeping the current model.")
            return
        if not 1 <= n <= len(models):
            self._channel.send(
                f"{n} isn't on the list. Reply with a number from 1 to {len(models)}, or 0 to cancel.")
            return  # invalid → prompt again
        chosen = models[n - 1]
        self._pending_models = None
        self._model_id = chosen.get("id")
        self._session_id = None  # switching the brain starts a fresh conversation
        label = chosen.get("label") or chosen.get("model") or chosen.get("id")
        self._channel.send(f"✅ Switched to {label}. Started a fresh conversation.")

    # -- turns -------------------------------------------------------------

    def _run_turn(self, text: str) -> None:
        """Plain turn → plain reply (used by /commands; no typing/quote effect)."""
        try:
            reply, self._session_id = self._on_message(
                text, self._session_id, self._mode, self.askpass, self._model_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] turn failed: %s", exc)
            reply = "Sorry — something went wrong handling that."
        self._channel.send(reply or "(no response)")

    def _reply_turn(self, text: str, reply_to: Optional[int]) -> None:
        """Run one turn and deliver the answer ONCE as a reply to the user's message,
        showing only the standard top '<name> is typing…' status while it works. No
        in-chat placeholder, no streaming. When reply_to is absent (e.g. unit tests),
        sends plainly so behaviour is unchanged off the live Telegram path."""
        status = _TypingStatus(self._channel).start() if reply_to else None
        try:
            reply, self._session_id = self._on_message(
                text, self._session_id, self._mode, self.askpass, self._model_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] turn failed: %s", exc)
            reply = "Sorry — something went wrong handling that."
        finally:
            if status is not None:
                status.stop()
        reply = reply or "(no response)"
        if reply_to:
            self._send_reply(reply, reply_to)
        else:
            self._channel.send(reply)

    def _process(self, text: str, reply_to: Optional[int] = None) -> None:
        # `!cmd` → run a shell command via the agent's run_shell tool.
        if text.startswith("!"):
            cmd = text[1:].strip()
            self._reply_turn(f"Run this shell command with run_shell and show me the output:\n{cmd}", reply_to)
            return
        self._reply_turn(text, reply_to)

    def _process_voice(self, voice: dict, caption: str, reply_to: Optional[int] = None) -> None:
        from namma_agent.comms.transcribe import transcribe_audio
        try:
            path = self._download(voice)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] voice download failed: %s", exc)
            self._channel.send("Couldn't download that voice message.", reply_to=reply_to)
            return
        self._channel.send_chat_action("typing")
        text = transcribe_audio(path)
        if not text:
            self._channel.send(
                "I got your voice message, but voice transcription isn't set up. Add an "
                "OpenAI(-compatible) API key under `comms.stt` in config to enable it.",
                reply_to=reply_to)
            return
        prompt = f"{caption}\n{text}".strip() if caption else text
        self._reply_turn(prompt, reply_to)

    def _process_document(self, document: dict, caption: str, reply_to: Optional[int] = None) -> None:
        try:
            path = self._download(document)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] document download failed: %s", exc)
            self._channel.send("Couldn't download that file.", reply_to=reply_to)
            return
        ask = caption or "Read this document and give me a short summary."
        self._reply_turn(f"The user sent a document saved at {path}. "
                         f"Use read_document on it, then: {ask}", reply_to)

    def _download(self, document: dict) -> str:
        file_id = document["file_id"]
        info = self._channel._post("getFile", {"file_id": file_id})
        file_path = info["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{self._channel._token}/{file_path}"
        dest_dir = os.path.join("data", "uploads")
        os.makedirs(dest_dir, exist_ok=True)
        name = document.get("file_name") or os.path.basename(file_path)
        dest = os.path.join(dest_dir, name)
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            with open(dest, "wb") as fh:
                fh.write(resp.read())
        return os.path.abspath(dest)
