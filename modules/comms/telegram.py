"""Telegram delivery channel for proactive FRIDAY notifications.

Mirrors jarvis src/comms/channels/telegram.ts.
Sends messages when the user is away from the machine (reminders, goal
check-ins, awareness suggestions).

Setup:
  1. Create a bot via @BotFather and copy the token.
  2. Message the bot once to get your chat_id.
  3. Set environment variables:
       FRIDAY_TELEGRAM_TOKEN=<bot_token>
       FRIDAY_TELEGRAM_CHAT_ID=<chat_id>
  4. Install:  pip install python-telegram-bot

Security: tokens live in OS environment variables, never in config.yaml.
"""
from __future__ import annotations

import os
import re as _re
import threading
import time
from html import escape as _html_escape

from core.logger import logger


def _markdown_to_telegram_html(text: str) -> str:
    """Convert simple markdown to Telegram's HTML parse_mode.

    Telegram HTML accepts <b>, <i>, <code>, <pre>, <s>, <u>, <a>. Every
    other angle-bracket char must be escaped, so we escape first and
    then re-introduce the formats we care about.
    """
    escaped = _html_escape(text)
    escaped = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=_re.DOTALL)
    escaped = _re.sub(r"(?<![\*\w])\*([^\*\n]+?)\*(?!\w)", r"<i>\1</i>", escaped)
    escaped = _re.sub(r"`([^`]+?)`", r"<code>\1</code>", escaped)
    return escaped


_DEFAULT_APPROVAL_OPTIONS: tuple[str, ...] = ("approve", "deny", "cancel")

# Tokens that resolve approval prompts. The TelegramInbound dispatcher
# matches incoming text against these BEFORE handing the message to
# process_input(), so a bare "yes" never gets routed to FRIDAY as a query
# while an approval gate is open.
_APPROVAL_TOKENS: dict[str, str] = {
    "approve": "approve", "approved": "approve",
    "yes": "approve", "y": "approve", "ok": "approve", "okay": "approve",
    "go": "approve", "confirm": "approve", "do it": "approve",
    "deny": "deny", "denied": "deny",
    "no": "deny", "n": "deny", "stop": "deny", "reject": "deny",
    "cancel": "cancel", "abort": "cancel", "nevermind": "cancel",
}


class _ApprovalGate:
    """One open approval round-trip. Each ``request_approval`` call owns
    its own gate so a superseded request can be cleanly cancelled without
    racing the new caller's response."""

    __slots__ = ("event", "response", "options")

    def __init__(self, options: tuple[str, ...]):
        self.event = threading.Event()
        self.response: str | None = None
        self.options: tuple[str, ...] = options


class TelegramChannel:
    """Sends proactive notifications to a Telegram chat."""

    def __init__(self, token: str | None = None, chat_id: str | None = None):
        # Respect explicitly-passed empty strings as "offline". The previous
        # `token or env.get(...)` shape silently fell back to the env var on
        # empty input, which made tests (and callers that wired in "" to
        # mean "disabled") inherit the developer's local Telegram token.
        # Only fall back to env when the arg is None.
        self._token = token if token is not None else os.environ.get("FRIDAY_TELEGRAM_TOKEN", "")
        self._chat_id = chat_id if chat_id is not None else os.environ.get("FRIDAY_TELEGRAM_CHAT_ID", "")
        self._available = bool(self._token and self._chat_id)
        if not self._available:
            logger.debug("[Telegram] disabled — set FRIDAY_TELEGRAM_TOKEN + FRIDAY_TELEGRAM_CHAT_ID")
        # Phase 7: per-channel approval gate. Only one approval can be open
        # at a time (a workflow is a single user-facing interaction). When
        # a second request_approval comes in while the first is still open,
        # the first is cancelled cleanly via its own _ApprovalGate.
        self._approval_lock = threading.Lock()
        self._current_gate: _ApprovalGate | None = None

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str, parse_mode: str = "") -> bool:
        """Send a message asynchronously. Returns True if dispatched."""
        if not self.available:
            return False
        t = threading.Thread(target=self._send_sync, args=(text, parse_mode), daemon=True)
        t.start()
        return True

    # ------------------------------------------------------------------
    # Phase 7: approval gate
    # ------------------------------------------------------------------

    def request_approval(
        self,
        question: str,
        *,
        options: list[str] | tuple[str, ...] | None = None,
        timeout: int = 180,
    ) -> str:
        """Send *question* to the user and block until they reply with one
        of *options*, or *timeout* seconds elapse.

        Returns one of the canonical tokens ``approve``, ``deny``, ``cancel``,
        or ``timeout``. Always returns ``deny`` when the channel is offline
        (refuse-by-default — security workflows must never run unattended).
        """
        if not self.available:
            return "deny"
        opts = tuple(o.lower() for o in (options or _DEFAULT_APPROVAL_OPTIONS))
        new_gate = _ApprovalGate(options=opts)
        with self._approval_lock:
            # If a previous gate is still open, cancel it. The old caller
            # reads `old.response`, not the new one's, so no race.
            old = self._current_gate
            if old is not None and not old.event.is_set():
                old.response = "cancel"
                old.event.set()
            self._current_gate = new_gate

        prompt = f"{question}\n\nReply with: {', '.join(opts)}"
        # Block briefly on the send so the prompt is in the chat before we wait.
        try:
            self._send_sync(prompt, "")
        except Exception as exc:  # pragma: no cover - network surfaces
            logger.warning("[Telegram] approval send failed: %s", exc)

        if new_gate.event.wait(timeout=max(1, int(timeout))):
            with self._approval_lock:
                response = new_gate.response or "deny"
                if self._current_gate is new_gate:
                    self._current_gate = None
            return response
        # Timed out — close the gate so a late reply doesn't satisfy it.
        with self._approval_lock:
            if self._current_gate is new_gate:
                self._current_gate = None
        return "timeout"

    def try_resolve_approval(self, raw_text: str) -> bool:
        """Return True if *raw_text* satisfies an open approval gate.

        Called by :class:`TelegramInbound` before routing the message to
        ``app.process_input``. When True, the caller MUST NOT forward the
        message to FRIDAY — it has been consumed by the gate.
        """
        normalized = (raw_text or "").strip().lower().strip(".!?")
        if not normalized:
            return False
        with self._approval_lock:
            gate = self._current_gate
            if gate is None or gate.event.is_set():
                return False
            opts = gate.options
        # Match against the canonical token map, then check whether the
        # resolved token is among the active options (defaults are
        # approve/deny/cancel which cover the union).
        resolved = _APPROVAL_TOKENS.get(normalized)
        if resolved is None:
            # Multi-word options like "do it" matched via full phrase.
            for phrase, token in _APPROVAL_TOKENS.items():
                if " " in phrase and phrase in normalized:
                    resolved = token
                    break
        if resolved is None:
            return False
        if resolved not in opts and resolved != "cancel":
            # Always honor "cancel" even when the caller didn't list it.
            return False
        with self._approval_lock:
            if self._current_gate is gate and not gate.event.is_set():
                gate.response = resolved
                gate.event.set()
                return True
        return False

    _TELEGRAM_MAX_CHARS = 3800  # safe margin under Telegram's 4096-char limit

    @staticmethod
    def _chunk_text(text: str, limit: int) -> list[str]:
        """Split text into chunks ≤ limit chars, preferring sentence/newline boundaries."""
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Try to split at a newline or sentence boundary within the window.
            window = text[:limit]
            split_at = max(window.rfind("\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
            if split_at <= 0:
                split_at = limit
            else:
                split_at += 1  # include the delimiter character
            chunks.append(text[:split_at].rstrip())
            text = text[split_at:].lstrip()
        return chunks

    def register_commands(self, commands: "list[tuple[str, str]]") -> bool:
        """Push the slash-command registry to BotFather via setMyCommands.

        Telegram clients use this list to drive their `/`-autocomplete
        UI. Without it, typing `/` in the chat shows no suggestions.

        Accepts a list of ``(name, description)`` tuples. Returns True
        when the call succeeded, False otherwise (offline, network
        error, or the bot already has the same set — which Telegram
        treats as ok-with-result=True regardless).
        """
        if not self.available or not commands:
            return False
        import urllib.request as _req
        import urllib.error as _err
        import json as _json
        url = f"https://api.telegram.org/bot{self._token}/setMyCommands"
        # Telegram's spec: command 1-32 chars [a-z0-9_], description 3-256 chars.
        cleaned = []
        for name, desc in commands:
            name_clean = (name or "").lstrip("/").lower()[:32]
            desc_clean = (desc or "").strip()[:256] or "No description."
            if name_clean and len(name_clean) <= 32:
                cleaned.append({"command": name_clean, "description": desc_clean})
        body = _json.dumps({"commands": cleaned}).encode()
        req = _req.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _req.urlopen(req, timeout=8) as resp:
                result = _json.load(resp)
                if result.get("ok"):
                    logger.info("[Telegram] setMyCommands registered %d commands", len(cleaned))
                    return True
                logger.warning("[Telegram] setMyCommands failed: %s", result.get("description"))
        except (_err.HTTPError, _err.URLError, OSError) as exc:
            logger.warning("[Telegram] setMyCommands network error: %s", exc)
        return False

    def chat_action(self, action: str = "typing") -> None:
        """Fire a single sendChatAction call (synchronous, ~80ms).

        Telegram clients display the action (typing / upload_photo /
        etc.) for up to 5 seconds. The caller is responsible for
        re-firing while a long operation is still in progress —
        :func:`typing_loop` does that as a background thread.
        """
        if not self.available:
            return
        import urllib.request as _req
        import urllib.error as _err
        import json as _json
        url = f"https://api.telegram.org/bot{self._token}/sendChatAction"
        payload = _json.dumps({"chat_id": self._chat_id, "action": action}).encode()
        req = _req.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            _req.urlopen(req, timeout=5).close()
        except (_err.HTTPError, _err.URLError, OSError) as exc:
            logger.debug("[Telegram] chat_action %s failed: %s", action, exc)

    def send_capturing_id(self, text: str, parse_mode: str = "") -> "int | None":
        """Synchronous sendMessage that returns the new message_id.

        Used by `_process` to drop a `💭 thinking…` bubble into the
        chat that can later be edited in place via `edit_message`.
        Returns None when the bot is offline or the send failed —
        callers fall back to a normal async send.
        """
        if not self.available:
            return None
        import urllib.request as _req
        import urllib.error as _err
        import json as _json
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        if not parse_mode:
            text = _markdown_to_telegram_html(text)
            parse_mode = "HTML"
        body: dict = {"chat_id": self._chat_id, "text": text, "parse_mode": parse_mode}
        req = _req.Request(url, data=_json.dumps(body).encode(),
                           headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _req.urlopen(req, timeout=8) as resp:
                result = _json.load(resp)
                if result.get("ok"):
                    return int(result.get("result", {}).get("message_id") or 0) or None
                logger.warning("[Telegram] sendMessage (placeholder) failed: %s", result.get("description"))
        except (_err.HTTPError, _err.URLError, OSError) as exc:
            logger.warning("[Telegram] sendMessage (placeholder) error: %s", exc)
        return None

    def edit_message(self, message_id: int, text: str, parse_mode: str = "") -> bool:
        """Replace the body of an existing message with *text*.

        Used to morph the `💭 thinking…` placeholder into the real
        response so the user sees the bubble change in-place instead
        of receiving a second message. Returns True when the edit was
        accepted (or harmlessly redundant), False on real failure.
        """
        if not self.available or not message_id:
            return False
        import urllib.request as _req
        import urllib.error as _err
        import json as _json
        url = f"https://api.telegram.org/bot{self._token}/editMessageText"
        if not parse_mode:
            text = _markdown_to_telegram_html(text)
            parse_mode = "HTML"
        # Telegram rejects edits longer than 4096 chars — fall back to
        # sending a new message in that case (the caller can re-send).
        if len(text) > self._TELEGRAM_MAX_CHARS:
            return False
        body = {"chat_id": self._chat_id, "message_id": int(message_id),
                "text": text, "parse_mode": parse_mode}
        req = _req.Request(url, data=_json.dumps(body).encode(),
                           headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _req.urlopen(req, timeout=8) as resp:
                result = _json.load(resp)
                if result.get("ok"):
                    return True
                logger.warning("[Telegram] editMessageText failed: %s", result.get("description"))
        except (_err.HTTPError, _err.URLError, OSError) as exc:
            logger.warning("[Telegram] editMessageText error: %s", exc)
        return False

    def delete_message(self, message_id: int) -> bool:
        """Best-effort delete of a previously-sent message."""
        if not self.available or not message_id:
            return False
        import urllib.request as _req
        import urllib.error as _err
        import json as _json
        url = f"https://api.telegram.org/bot{self._token}/deleteMessage"
        body = {"chat_id": self._chat_id, "message_id": int(message_id)}
        req = _req.Request(url, data=_json.dumps(body).encode(),
                           headers={"Content-Type": "application/json"}, method="POST")
        try:
            _req.urlopen(req, timeout=5).close()
            return True
        except (_err.HTTPError, _err.URLError, OSError) as exc:
            logger.debug("[Telegram] deleteMessage failed: %s", exc)
            return False

    def typing_loop(self, action: str = "typing") -> "tuple[threading.Event, threading.Thread]":
        """Spawn a daemon thread that keeps the `typing` indicator alive.

        Returns a (stop_event, thread) pair — call `stop_event.set()`
        once the response is in flight to halt the loop. The thread
        re-sends the action every 4s (Telegram's 5s window minus 1s).
        """
        stop = threading.Event()

        def _run():
            self.chat_action(action)
            while not stop.wait(4.0):
                self.chat_action(action)

        thread = threading.Thread(target=_run, name=f"tg-{action}", daemon=True)
        thread.start()
        return stop, thread

    def _send_sync(self, text: str, parse_mode: str) -> None:
        import urllib.request
        import urllib.error
        import json as _json
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        # If the caller didn't specify a parse_mode, run the message
        # through the markdown→Telegram-HTML converter so **bold**,
        # *italic*, and `code` render properly instead of leaking
        # literal asterisks into the user's chat.
        if not parse_mode:
            text = _markdown_to_telegram_html(text)
            parse_mode = "HTML"
        for chunk in self._chunk_text(text, self._TELEGRAM_MAX_CHARS):
            body: dict = {"chat_id": self._chat_id, "text": chunk}
            if parse_mode:
                body["parse_mode"] = parse_mode
            payload = _json.dumps(body).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = _json.load(resp)
                    if not result.get("ok"):
                        logger.warning("[Telegram] send failed: %s", result.get("description"))
            except urllib.error.HTTPError as exc:
                body_bytes = exc.read()
                logger.warning("[Telegram] send failed HTTP %d: %s", exc.code, body_bytes.decode()[:200])
            except Exception as exc:
                logger.warning("[Telegram] send failed: %s", exc)


class TelegramInbound:
    """Polls the bot for incoming messages and routes them to FRIDAY silently.

    Each incoming message is processed via app.process_input(text, source="telegram")
    on a worker thread. Because source="telegram" takes the synchronous _execute_turn
    path, process_input returns the response text directly — no event-bus subscription
    is needed. TTS is suppressed for the duration of the call via the
    app.telegram_turn_active flag checked in VoiceIOPlugin.handle_speak.
    """

    _POLL_TIMEOUT = 20   # seconds — Telegram long-poll window

    def __init__(self, channel: TelegramChannel, app):
        self._channel = channel
        self._app = app
        self._offset = 0
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Push the slash-command catalog so Telegram's `/`-autocomplete
        # UI knows what to suggest. We pull from core.slash_commands.REGISTRY
        # rather than hard-coding here, so adding a new slash command in
        # one place propagates everywhere.
        # setMyCommands is a blocking network round-trip (~1-2s). Run it on a
        # daemon thread so it never delays FRIDAY's startup — autocomplete
        # populating a beat later is fine.
        def _register_commands_async():
            try:
                from core.slash_commands import REGISTRY as _SLASH_REGISTRY  # noqa: PLC0415
                self._channel.register_commands([(name, desc) for name, _, desc in _SLASH_REGISTRY])
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("[TelegramInbound] command registration skipped: %s", exc)
        threading.Thread(target=_register_commands_async, name="TelegramCmdReg", daemon=True).start()
        self._thread = threading.Thread(target=self._poll_loop, name="TelegramInbound", daemon=True)
        self._thread.start()
        logger.info("[TelegramInbound] polling started")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        import socket
        backoff = 1
        while True:
            try:
                updates = self._get_updates()
                backoff = 1  # healthy poll → reset backoff
                for update in updates:
                    self._dispatch(update)
            except (TimeoutError, socket.timeout):
                # Benign: the long-poll window elapsed with no new message.
                # Re-poll IMMEDIATELY — sleeping here is exactly what caused
                # the multi-second receive lag (a message sent during the
                # old 5s sleep wasn't fetched until the sleep ended).
                continue
            except Exception as exc:
                logger.warning("[TelegramInbound] poll error: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 15)  # exponential backoff, capped

    def _get_updates(self) -> list:
        import urllib.request
        import urllib.error
        import json as _json

        url = (
            f"https://api.telegram.org/bot{self._channel._token}/getUpdates"
            f"?offset={self._offset}&timeout={self._POLL_TIMEOUT}&allowed_updates=message"
        )
        # Socket read timeout sits just past the long-poll window so a normal
        # empty return (Telegram closes the long poll at _POLL_TIMEOUT) never
        # trips a spurious read-timeout; if it does, _poll_loop re-polls at once.
        try:
            with urllib.request.urlopen(url, timeout=self._POLL_TIMEOUT + 10) as resp:
                data = _json.load(resp)
        except urllib.error.HTTPError as exc:
            logger.warning("[TelegramInbound] getUpdates HTTP %d", exc.code)
            time.sleep(1)
            return []
        except urllib.error.URLError as exc:
            # Wraps socket.timeout (benign) and real network errors. Let a
            # timeout bubble up as TimeoutError so the loop re-polls instantly;
            # re-raise everything else for the backoff path.
            import socket as _socket
            if isinstance(exc.reason, (TimeoutError, _socket.timeout)):
                raise TimeoutError(str(exc.reason)) from exc
            raise
        if not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    def _dispatch(self, update: dict) -> None:
        message = update.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != self._channel._chat_id:
            return

        # Voice notes / audio messages (P1.4)
        voice = message.get("voice") or message.get("audio") or message.get("video_note")
        if voice:
            file_id = voice.get("file_id", "")
            threading.Thread(
                target=self._handle_voice_note,
                args=(file_id,),
                name="TelegramVoice",
                daemon=True,
            ).start()
            return

        # File attachment (document, photo, audio, video, …)
        doc = message.get("document")
        photo_arr = message.get("photo")  # list of PhotoSize, largest last
        if doc or photo_arr:
            if doc:
                file_id = doc.get("file_id", "")
                file_name = doc.get("file_name") or f"attachment_{file_id[:8]}"
            else:
                largest = max(photo_arr, key=lambda p: p.get("file_size", 0))
                file_id = largest.get("file_id", "")
                file_name = f"photo_{file_id[:8]}.jpg"
            caption = (message.get("caption") or "").strip()
            threading.Thread(
                target=self._handle_file,
                args=(file_id, file_name, caption),
                name="TelegramFile",
                daemon=True,
            ).start()
            return

        # Plain text message
        text = (message.get("text") or "").strip()
        if not text:
            return

        # Phase 7: intercept approval responses BEFORE they're routed to
        # FRIDAY. A bare "yes" while an approval gate is open must resolve
        # the gate, not be parsed as a new query.
        if self._channel.try_resolve_approval(text):
            logger.info("[TelegramInbound] approval response consumed: %r", text)
            return

        # Slash commands must reach FRIDAY's slash dispatcher
        # (`core.slash_commands.dispatch`). Pre-Track-6.3 code dropped
        # every slash except `/start`, which silently broke `/new`,
        # `/research`, `/lock`, etc. when sent from Telegram. Only
        # `/start` is still handled here as a Telegram-bot greeting
        # convention. Strip the optional `@BotUsername` suffix that
        # Telegram appends in group chats so `/new@FridayBot` becomes
        # `/new` before we forward it.
        if text.startswith('/'):
            head, _, rest = text.partition(' ')
            stripped_head = head.split('@', 1)[0]
            text = (stripped_head + (' ' + rest if rest else '')).strip()
            command = stripped_head.lower()
            if command == '/start':
                self._channel.send(
                    "Hello! I'm FRIDAY, your AI assistant.\n"
                    "Send me a message or upload a document (.pdf, .docx, .txt, .csv, "
                    ".xlsx, .pptx, .md, .html) to get started.\n"
                    "Type / to see the full command list."
                )
                return
            # Every other slash command falls through to _process so
            # FRIDAY's slash dispatcher in core/app.py:process_input
            # gets to run it.

        threading.Thread(
            target=self._process,
            args=(text,),
            name="TelegramProcess",
            daemon=True,
        ).start()

    # Extensions the session RAG / MarkItDown converter can handle.
    # Kept in sync with modules/document_intel/converter.py SUPPORTED_EXTENSIONS
    # plus the plain-text fallbacks in SessionRAG._PLAIN_SUFFIXES.
    _SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt", ".html", ".csv"}

    def _handle_file(self, file_id: str, file_name: str, caption: str) -> None:
        """Download a Telegram file, load it into session RAG, reply with status."""
        import tempfile
        import urllib.request
        import urllib.error
        import json as _json
        from pathlib import Path

        suffix = Path(file_name).suffix.lower()
        if suffix not in self._SUPPORTED_EXTENSIONS:
            supported = ", ".join(sorted(self._SUPPORTED_EXTENSIONS))
            self._channel.send(
                f"Unsupported file type: {suffix or '(no extension)'}\n"
                f"Supported formats: {supported}"
            )
            return

        # Step 1 — resolve download URL via getFile
        try:
            gf_url = (
                f"https://api.telegram.org/bot{self._channel._token}"
                f"/getFile?file_id={file_id}"
            )
            with urllib.request.urlopen(gf_url, timeout=10) as resp:
                gf_data = _json.load(resp)
        except Exception as exc:
            logger.warning("[TelegramInbound] getFile failed: %s", exc)
            self._channel.send("Could not retrieve the file from Telegram. Please try again.")
            return

        if not gf_data.get("ok"):
            self._channel.send("Telegram returned an error fetching the file.")
            return

        file_path_remote = gf_data["result"].get("file_path", "")
        if not file_path_remote:
            self._channel.send("Telegram did not return a download path for this file.")
            return

        # Step 2 — download to a temp file
        download_url = (
            f"https://api.telegram.org/file/bot{self._channel._token}/{file_path_remote}"
        )
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix, prefix="friday_tg_", delete=False
            ) as tmp:
                tmp_path = tmp.name
            urllib.request.urlretrieve(download_url, tmp_path)
        except Exception as exc:
            logger.warning("[TelegramInbound] download failed: %s", exc)
            self._channel.send(f"Download failed: {exc}")
            return

        # Step 3 — rename to preserve the original filename (cosmetic, for status msg)
        import os
        try:
            named = str(Path(tmp_path).parent / file_name)
            os.rename(tmp_path, named)
            load_path = named
        except Exception:
            load_path = tmp_path

        status = self._app.load_session_rag_file(load_path)

        reply = f"File loaded: {file_name}\n{status}"
        if caption:
            # Process the caption as a query against the freshly loaded document
            reply += "\n\nProcessing your caption..."
            self._channel.send(reply)
            self._process(caption)
        else:
            self._channel.send(reply)

    def _handle_voice_note(self, file_id: str) -> None:
        """Download a Telegram voice/audio note and transcribe it via STT (P1.4)."""
        import tempfile, os as _os
        # Resolve download URL via getFile
        import urllib.request, json as _json
        url = f"https://api.telegram.org/bot{self._channel._token}/getFile?file_id={file_id}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = _json.load(resp)
        except Exception as exc:
            logger.warning("[TelegramVoice] getFile failed: %s", exc)
            return
        file_path = (data.get("result") or {}).get("file_path", "")
        if not file_path:
            logger.warning("[TelegramVoice] no file_path in getFile response")
            return
        download_url = f"https://api.telegram.org/file/bot{self._channel._token}/{file_path}"
        suffix = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ".ogg"
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
            urllib.request.urlretrieve(download_url, tmp_path)
        except Exception as exc:
            logger.warning("[TelegramVoice] download failed: %s", exc)
            return
        try:
            # P3.20: single transcription entrypoint shared by every audio channel.
            from core.transcription import transcribe_file  # noqa: PLC0415
            text = transcribe_file(tmp_path, app=self._app)
        finally:
            try:
                _os.unlink(tmp_path)
            except Exception:
                pass
        if not text:
            logger.warning("[TelegramVoice] transcription returned empty text")
            return
        logger.info("[TelegramVoice] transcribed: %r", text)
        self._process(text)

    def _process(self, text: str) -> None:
        # process_input(source="telegram") takes the synchronous _execute_turn path
        # and returns the response text directly — no event subscription needed.
        # The flag is True only for the duration of the synchronous call so voice
        # TTS is never blocked longer than the actual Telegram turn takes.
        self._app.telegram_turn_active = True
        # 2026-05-23: two layers of "thinking" feedback so the user sees
        # progress both in the chat header AND in the chat bubble area:
        #   1. typing_loop()       — keeps the "FRIDAY is typing…" status
        #                            alive next to the bot name (Telegram's
        #                            built-in header indicator).
        #   2. placeholder bubble — a `💭 thinking…` message dropped into
        #                            the chat that gets editMessageText'd
        #                            into the real response when ready.
        #                            This is what the user sees scrolling
        #                            past in the conversation.
        typing_stop = None
        placeholder_id: "int | None" = None
        try:
            typing_stop, _ = self._channel.typing_loop("typing")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[Telegram] typing loop start failed: %s", exc)
        try:
            placeholder_id = self._channel.send_capturing_id("💭")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[Telegram] placeholder bubble failed: %s", exc)

        try:
            response = self._app.process_input(text, source="telegram")
        finally:
            self._app.telegram_turn_active = False
            if typing_stop is not None:
                typing_stop.set()

        if response:
            edited = False
            if placeholder_id is not None:
                edited = self._channel.edit_message(placeholder_id, response)
            if not edited:
                self._channel.send(response)
        elif placeholder_id is not None:
            # Empty response (rare — voice handoff, file-load, etc.).
            # Don't leave a stale "thinking…" bubble in the chat.
            self._channel.delete_message(placeholder_id)
