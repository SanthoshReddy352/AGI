"""Comms tool — send a notification to Telegram / Discord.

Builds the channels from the environment on each call (cheap, stateless), so the
tool works through plain auto-discovery. Channels stay off unless their tokens
are set (``FRIDAY_TELEGRAM_TOKEN``+``FRIDAY_TELEGRAM_CHAT_ID`` /
``FRIDAY_DISCORD_WEBHOOK_URL``).
"""
from __future__ import annotations

from friday.comms.discord import DiscordChannel
from friday.comms.telegram import TelegramChannel
from friday.core.tools import ToolRegistry, ToolResult


def _send_notification(args: dict) -> ToolResult:
    message = (args.get("message") or "").strip()
    if not message:
        return ToolResult(ok=False, content="", error="a message is required")
    channel = (args.get("channel") or "all").lower()
    telegram, discord = TelegramChannel(), DiscordChannel()

    if not (telegram.available or discord.available):
        return ToolResult(ok=False, content="",
                          error="no channels configured (set FRIDAY_TELEGRAM_TOKEN+"
                                "FRIDAY_TELEGRAM_CHAT_ID or FRIDAY_DISCORD_WEBHOOK_URL)")
    sent_to = []
    if channel in ("all", "telegram") and telegram.send(message):
        sent_to.append("telegram")
    if channel in ("all", "discord") and discord.send(message):
        sent_to.append("discord")
    if not sent_to:
        return ToolResult(ok=False, content="", error=f"no available channel for {channel!r}")
    return ToolResult(ok=True, content=f"Notification sent to {', '.join(sent_to)}.")


def register(registry: ToolRegistry) -> None:
    registry.register("send_notification",
        "Send a notification message to Telegram and/or Discord.", {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "the message to send"},
                "channel": {"type": "string", "enum": ["all", "telegram", "discord"],
                            "description": "target channel (default all)"},
            },
            "required": ["message"],
        }, _send_notification)
