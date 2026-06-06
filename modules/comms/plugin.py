"""Comms plugin — wires Telegram/Discord into the EventBus.

Subscribes to proactive events (reminder_fired, goal_at_risk, goal_morning_checkin,
goal_evening_review, trigger_fired) and routes them to enabled channels.

All channel tokens live in environment variables, not config.yaml. Outbound
network calls go through a background thread so they never block the main loop.
ConsentService is respected — online channels only send when enabled.

Phase 7: adds two source-aware helpers — ``send_progress`` for streaming
mid-task progress updates back to whichever channel originated the turn
(Telegram, voice, or GUI), and the ``request_approval`` plumbing
exposed via ``app.comms.telegram.request_approval()`` for security
workflows that need a yes/no round-trip.
"""
from __future__ import annotations

from core.logger import logger
from core.plugin_manager import FridayPlugin
from .telegram import TelegramChannel, TelegramInbound
from .discord import DiscordChannel

try:
    from core.turn_context import current_turn
except Exception:  # pragma: no cover
    current_turn = None  # type: ignore[assignment]


class CommsPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "Comms"
        self.telegram = TelegramChannel()
        self.discord = DiscordChannel()
        app.comms = self
        self.on_load()

    def on_load(self):
        if not self.telegram.available and not self.discord.available:
            logger.info(
                "[Comms] no channels configured. "
                "Set FRIDAY_TELEGRAM_TOKEN+FRIDAY_TELEGRAM_CHAT_ID "
                "or FRIDAY_DISCORD_WEBHOOK_URL to enable."
            )
            return

        bus = self.app.event_bus
        bus.subscribe("reminder_fired", self._handle_reminder)
        bus.subscribe("goal_morning_checkin", self._handle_morning)
        bus.subscribe("goal_evening_review", self._handle_evening)
        bus.subscribe("goal_at_risk", self._handle_goal_at_risk)
        bus.subscribe("trigger_fired", self._handle_trigger)

        channels = []
        if self.telegram.available:
            channels.append("Telegram")
            TelegramInbound(self.telegram, self.app).start()
        if self.discord.available:
            channels.append("Discord")
        logger.info("[Comms] active channels: %s", ", ".join(channels))

        if self.telegram.available:
            self.telegram.send("FRIDAY is online and ready.")

        # Register send_notification capability
        self.app.register_capability({
            "name": "send_notification",
            "description": "Send a proactive notification to Telegram or Discord.",
            "parameters": {
                "message": "string – the message text to send",
                "channel": "string – optional: 'telegram' or 'discord' (default: all)",
            },
            "connectivity": "online",
            "side_effect_level": "external",
        }, self.handle_send_notification)

        # Phase 7: source-aware progress streaming. The handler reads
        # current_turn().source to decide where the update goes; if no
        # turn is active, the update is logged but not displayed (the
        # capability is intended for use inside a workflow loop).
        self.app.register_capability({
            "name": "send_progress",
            "description": (
                "Stream a short progress update back to whichever channel "
                "originated the active turn (Telegram, voice TTS, or GUI). "
                "Used by long-running workflows to report step-by-step "
                "completion. Does not block the workflow loop."
            ),
            "parameters": {
                "message": "string – the progress line, e.g. 'step 2/3: services scanned'",
            },
        }, self.handle_send_progress, metadata={
            "connectivity": "local",
            "latency_class": "fast",
            "permission_mode": "always_ok",
            "side_effect_level": "read",
            "network_scope": "local",
            "requires_authorization": False,
        })

    def _broadcast(self, text: str) -> None:
        if self.telegram.available:
            self.telegram.send(text)
        if self.discord.available:
            self.discord.send(text)

    def handle_send_notification(self, text: str, args: dict) -> str:
        msg = args.get("message") or text
        channel = (args.get("channel") or "all").lower()
        if channel == "telegram":
            sent = self.telegram.send(msg)
        elif channel == "discord":
            sent = self.discord.send(msg)
        else:
            sent = self.telegram.send(msg) or self.discord.send(msg)
        return "Notification sent." if sent else "No channels available."

    def handle_send_progress(self, text: str, args: dict) -> str:
        msg = (args.get("message") if isinstance(args, dict) else None) or text
        if not msg:
            return "no progress message provided"
        self.send_progress(msg)
        return "ok"

    def send_progress(self, text: str) -> None:
        """Route a progress update to whichever channel originated the turn.

        - source="telegram"  → ``self.telegram.send(text)``
        - source="voice"     → ``app.tts.speak(text)`` (when TTS is wired)
        - source="gui"       → publish ``progress_update`` on the EventBus
        - anything else      → log only

        Always non-blocking; failures degrade to a log line.
        """
        source = ""
        if current_turn:
            ctx = current_turn()
            if ctx is not None:
                source = getattr(ctx, "source", "") or ""

        if source == "telegram" and self.telegram.available:
            self.telegram.send(text)
            return
        if source == "voice":
            tts = getattr(self.app, "tts", None)
            if tts is not None and hasattr(tts, "speak"):
                try:
                    tts.speak(text)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("[Comms] tts.speak failed: %s", exc)
                return
        # GUI / unknown — emit on the event bus and let any subscriber
        # render it (HUD listens for "progress_update").
        bus = getattr(self.app, "event_bus", None)
        if bus is not None and hasattr(bus, "publish"):
            try:
                bus.publish("progress_update", {"text": text, "source": source})
                return
            except Exception:  # pragma: no cover
                pass
        logger.info("[Comms] progress: %s", text)

    def _handle_reminder(self, payload: dict) -> None:
        title = payload.get("title") or payload.get("text") or "Reminder"
        self._broadcast(f"⏰ *FRIDAY Reminder:* {title}")

    def _handle_morning(self, payload: dict) -> None:
        self._broadcast("🌅 Good morning! Time for your daily goal check-in with FRIDAY.")

    def _handle_evening(self, payload: dict) -> None:
        self._broadcast("🌙 Evening check-in: How did your goals go today?")

    def _handle_goal_at_risk(self, payload: dict) -> None:
        title = payload.get("title") or "A goal"
        self._broadcast(f"⚠️ *Goal at risk:* {title} needs your attention.")

    def _handle_trigger(self, payload: dict) -> None:
        name = payload.get("name") or payload.get("trigger_type") or "trigger"
        # Only broadcast triggers that explicitly request it via data flag
        if payload.get("data", {}).get("notify_remote"):
            self._broadcast(f"🔔 *FRIDAY trigger fired:* {name}")
