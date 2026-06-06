"""Messaging channels for FRIDAY v2 (Telegram + Discord).

Self-contained, stdlib-only, env-gated. Channels stay off unless their tokens are
present in the environment:

  * Telegram — ``FRIDAY_TELEGRAM_TOKEN`` + ``FRIDAY_TELEGRAM_CHAT_ID``
  * Discord  — ``FRIDAY_DISCORD_WEBHOOK_URL``

:class:`CommsManager` wires outbound notifications and (for Telegram) an inbound
bridge so you can chat with FRIDAY from your phone.
"""
from friday.comms.discord import DiscordChannel
from friday.comms.manager import CommsManager
from friday.comms.telegram import TelegramChannel, TelegramInbound

__all__ = ["TelegramChannel", "TelegramInbound", "DiscordChannel", "CommsManager"]
