"""Discord channel — outbound notifications via an incoming webhook URL.

Stdlib-only. No bot account required. Env-gated:
  FRIDAY_DISCORD_WEBHOOK_URL
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Optional

from friday.core.logger import logger


class DiscordChannel:
    def __init__(self, webhook_url: Optional[str] = None):
        self._url = webhook_url if webhook_url is not None else os.environ.get(
            "FRIDAY_DISCORD_WEBHOOK_URL", "")
        self._available = bool(self._url)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str, username: Optional[str] = None) -> bool:
        if not self.available or not text:
            return False
        if not username:
            from friday.config import assistant_name
            username = assistant_name()
        threading.Thread(target=self._send_sync, args=(text, username), daemon=True).start()
        return True

    def _send_sync(self, text: str, username: str) -> None:
        try:
            payload = json.dumps({"content": text[:2000], "username": username}).encode()
            req = urllib.request.Request(
                self._url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                if resp.status not in (200, 204):
                    logger.warning("[discord] send failed: HTTP %d", resp.status)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[discord] send error: %s", exc)
