"""Messaging channels for Namma Agent (Telegram + Discord).

Self-contained, stdlib-only, env-gated. Channels stay off unless their tokens are
present in the environment:

  * Telegram — ``NAMMA_TELEGRAM_TOKEN`` + ``NAMMA_TELEGRAM_CHAT_ID``
  * Discord  — ``NAMMA_DISCORD_WEBHOOK_URL``

:class:`CommsManager` wires outbound notifications and (for Telegram) an inbound
bridge so you can chat with Namma Agent from your phone.
"""
from namma_agent.comms.discord import DiscordChannel
from namma_agent.comms.manager import CommsManager
from namma_agent.comms.telegram import TelegramChannel, TelegramInbound

__all__ = ["TelegramChannel", "TelegramInbound", "DiscordChannel", "CommsManager"]
