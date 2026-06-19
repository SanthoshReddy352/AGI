"""CommsManager — owns the messaging channels and the inbound bridge.

Built once by :class:`FridayService`. Outbound: :meth:`broadcast` / :meth:`send`.
Inbound: :meth:`start_inbound` launches the Telegram poller, routing each message
through the supplied ``on_message(text) -> reply`` callback (the service's turn).
"""
from __future__ import annotations

from typing import Callable, Optional

from friday.comms.discord import DiscordChannel
from friday.comms.telegram import TelegramChannel, TelegramInbound
from friday.core.logger import logger


class CommsManager:
    def __init__(self, telegram: Optional[TelegramChannel] = None,
                 discord: Optional[DiscordChannel] = None):
        self.telegram = telegram or TelegramChannel()
        self.discord = discord or DiscordChannel()
        self._inbound: Optional[TelegramInbound] = None

    @property
    def any_available(self) -> bool:
        return self.telegram.available or self.discord.available

    def channels(self) -> list[str]:
        names = []
        if self.telegram.available:
            names.append("telegram")
        if self.discord.available:
            names.append("discord")
        return names

    def send(self, text: str, channel: str = "all") -> bool:
        """Send to one channel ('telegram'/'discord') or all. True if any dispatched."""
        channel = (channel or "all").lower()
        sent = False
        if channel in ("all", "telegram"):
            sent = self.telegram.send(text) or sent
        if channel in ("all", "discord"):
            sent = self.discord.send(text) or sent
        return sent

    def start_inbound(self, on_message: Callable[[str], str],
                      name: Optional[str] = None,
                      get_models: Optional[Callable[[], list]] = None) -> None:
        if not self.telegram.available or self._inbound is not None:
            return
        self._inbound = TelegramInbound(self.telegram, on_message, get_models=get_models)
        self._inbound.start()
        if self.telegram.available:
            if not name:
                from friday.config import assistant_name
                name = assistant_name()
            self.telegram.send(f"{name} is online and ready.")
        logger.info("[comms] active channels: %s", ", ".join(self.channels()) or "none")

    def stop(self) -> None:
        if self._inbound is not None:
            self._inbound.stop()
