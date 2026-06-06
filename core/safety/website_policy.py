"""Website policy — loads blocked/allowed domain lists from YAML (P3.17)."""
from __future__ import annotations

import os
from typing import Sequence

_DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "website_policy.yaml",
)


class WebsitePolicy:
    def __init__(self, config_path: str | None = None):
        self._config_path = config_path or _DEFAULT_CONFIG
        self.blocked_domains: list[str] = []
        self.allowed_prefixes: list[str] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._config_path):
            return
        try:
            import yaml  # type: ignore
            with open(self._config_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            self.blocked_domains = [str(d).lower() for d in (data.get("blocked_domains") or [])]
            self.allowed_prefixes = [str(p) for p in (data.get("allowed_url_prefixes") or [])]
        except Exception:
            pass

    def is_blocked_domain(self, domain: str) -> bool:
        d = domain.lower().lstrip("www.")
        return any(d == bd or d.endswith("." + bd) for bd in self.blocked_domains)

    def reload(self) -> None:
        self._load()


# Singleton loaded once at import time.
_policy = WebsitePolicy()


def get_policy() -> WebsitePolicy:
    return _policy
