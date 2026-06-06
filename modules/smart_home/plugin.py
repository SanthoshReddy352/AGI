"""P3.15 — Home Assistant integration.

Provides FRIDAY with smart home control via the Home Assistant REST API.
All calls are local-network only (HA runs on the LAN); no cloud dependency.

Config: config/home_assistant.yaml
  url: "http://homeassistant.local:8123"
  token: "<long-lived-access-token>"
  aliases:
    bedroom lights: light.bedroom_main
    ac: climate.living_room_ac
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Optional

from core.plugin_manager import FridayPlugin
from core.logger import logger

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "config", "home_assistant.yaml",
)


def _load_config() -> dict:
    try:
        import yaml
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


class HomeAssistantClient:
    """Minimal HA REST client (no external deps beyond stdlib + PyYAML)."""

    def __init__(self, url: str, token: str) -> None:
        self._base = url.rstrip("/")
        self._token = token

    def _request(self, method: str, path: str, data: Optional[dict] = None) -> dict:
        url = f"{self._base}/api/{path.lstrip('/')}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())

    def get_state(self, entity_id: str) -> dict:
        return self._request("GET", f"states/{entity_id}")

    def call_service(self, domain: str, service: str, data: dict) -> dict:
        return self._request("POST", f"services/{domain}/{service}", data)

    def turn_on(self, entity_id: str, **kwargs) -> dict:
        return self.call_service(
            entity_id.split(".")[0], "turn_on", {"entity_id": entity_id, **kwargs}
        )

    def turn_off(self, entity_id: str) -> dict:
        return self.call_service(
            entity_id.split(".")[0], "turn_off", {"entity_id": entity_id}
        )

    def set_temperature(self, entity_id: str, temperature: float) -> dict:
        return self.call_service(
            "climate", "set_temperature", {"entity_id": entity_id, "temperature": temperature}
        )


class SmartHomePlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "SmartHome"
        self._client: Optional[HomeAssistantClient] = None
        self._aliases: dict[str, str] = {}
        self.on_load()

    def on_load(self):
        cfg = _load_config()
        url = cfg.get("url", "")
        token = cfg.get("token", "")
        self._aliases = {k.lower(): v for k, v in (cfg.get("aliases") or {}).items()}

        if url and token:
            self._client = HomeAssistantClient(url, token)
            logger.info("[smart_home] Connected to Home Assistant at %s", url)
        else:
            logger.info("[smart_home] Not configured — set url+token in config/home_assistant.yaml")

        self.app.register_capability(
            {
                "name": "ha_turn_on",
                "description": "Turn on a smart home device or light.",
                "parameters": {"entity": "string — device name or HA entity ID"},
                "aliases": [
                    "turn on the lights", "switch on", "turn on", "lights on",
                    "turn on the", "enable the",
                ],
                "patterns": [
                    r"\bturn\s+on\b.{0,30}(?:the\s+)?(?:lights?|lamp|fan|ac|heater|tv|switch|plug)",
                    r"\blights?\s+on\b",
                    r"\bswitch\s+on\b",
                ],
                "context_terms": ["turn on", "lights on", "switch on", "enable device"],
                "permission_mode": "always_ok",
            },
            self._handle_turn_on,
        )
        self.app.register_capability(
            {
                "name": "ha_turn_off",
                "description": "Turn off a smart home device or light.",
                "parameters": {"entity": "string — device name or HA entity ID"},
                "aliases": [
                    "turn off the lights", "switch off", "turn off", "lights off",
                    "turn off the", "disable the",
                ],
                "patterns": [
                    r"\bturn\s+off\b.{0,30}(?:the\s+)?(?:lights?|lamp|fan|ac|heater|tv|switch|plug)",
                    r"\blights?\s+off\b",
                    r"\bswitch\s+off\b",
                ],
                "context_terms": ["turn off", "lights off", "switch off", "disable device"],
                "permission_mode": "always_ok",
            },
            self._handle_turn_off,
        )
        self.app.register_capability(
            {
                "name": "ha_get_state",
                "description": "Check the current state of a smart home device.",
                "parameters": {"entity": "string — device name or HA entity ID"},
                "aliases": [
                    "is the door locked", "is the light on", "check the ac",
                    "what is the temperature", "is the tv on", "what is the state of",
                ],
                "patterns": [
                    r"\bis\s+the\b.{0,30}\b(?:on|off|locked|open|closed|running)\b",
                    r"\bcheck\s+(?:the\s+)?\w+\s+(?:state|status)\b",
                    r"\bwhat\s+is\s+the\s+(?:temperature|state|status)\b",
                ],
                "context_terms": ["is the door", "check state", "device status", "is it on"],
                "permission_mode": "always_ok",
            },
            self._handle_get_state,
        )
        self.app.register_capability(
            {
                "name": "ha_set_temperature",
                "description": "Set the temperature for a climate device (AC, thermostat).",
                "parameters": {
                    "entity": "string — climate entity name",
                    "temperature": "float — target temperature in configured units",
                },
                "aliases": [
                    "set the ac to", "set temperature to", "set thermostat to",
                    "cool the room to", "heat the room to", "temperature to",
                ],
                "patterns": [
                    r"\bset\b.{0,20}(?:ac|thermostat|temperature|temp)\b.{0,20}\d+",
                    r"\b(?:cool|heat)\b.{0,20}\bto\b.{0,10}\d+\s*(?:degrees?|°)",
                ],
                "context_terms": ["set temperature", "set ac", "thermostat", "degrees"],
                "permission_mode": "always_ok",
            },
            self._handle_set_temperature,
        )
        logger.info("[smart_home] SmartHomePlugin loaded — 4 capabilities registered.")

    # ------------------------------------------------------------------

    def _resolve_entity(self, text: str) -> str:
        """Map friendly name → entity_id via aliases, or return as-is."""
        lower = text.strip().lower()
        return self._aliases.get(lower, lower)

    def _handle_turn_on(self, raw_text: str, args: dict) -> str:
        if not self._client:
            return "Home Assistant is not configured. Set url and token in config/home_assistant.yaml."
        entity_name = args.get("entity") or _extract_entity(raw_text, "on")
        entity_id = self._resolve_entity(entity_name)
        guard = getattr(self.app, "confirmation_guard", None)
        if guard is not None and guard.needs_confirmation(args):
            return guard.arm(
                action="ha_turn_on", args={"entity": entity_name},
                preview=f"I'll turn on {entity_name}.",
            )
        try:
            self._client.turn_on(entity_id)
            return f"Turned on {entity_name}."
        except Exception as exc:
            logger.error("[smart_home] turn_on %s: %s", entity_id, exc)
            return f"Couldn't turn on {entity_name}: {exc}"

    def _handle_turn_off(self, raw_text: str, args: dict) -> str:
        if not self._client:
            return "Home Assistant is not configured."
        entity_name = args.get("entity") or _extract_entity(raw_text, "off")
        entity_id = self._resolve_entity(entity_name)
        guard = getattr(self.app, "confirmation_guard", None)
        if guard is not None and guard.needs_confirmation(args):
            return guard.arm(
                action="ha_turn_off", args={"entity": entity_name},
                preview=f"I'll turn off {entity_name}.",
            )
        try:
            self._client.turn_off(entity_id)
            return f"Turned off {entity_name}."
        except Exception as exc:
            logger.error("[smart_home] turn_off %s: %s", entity_id, exc)
            return f"Couldn't turn off {entity_name}: {exc}"

    def _handle_get_state(self, raw_text: str, args: dict) -> str:
        if not self._client:
            return "Home Assistant is not configured."
        entity_name = args.get("entity") or _extract_entity(raw_text)
        entity_id = self._resolve_entity(entity_name)
        try:
            state = self._client.get_state(entity_id)
            return f"{entity_name}: {state.get('state', 'unknown')}."
        except Exception as exc:
            logger.error("[smart_home] get_state %s: %s", entity_id, exc)
            return f"Couldn't get state of {entity_name}: {exc}"

    def _handle_set_temperature(self, raw_text: str, args: dict) -> str:
        if not self._client:
            return "Home Assistant is not configured."
        entity_name = args.get("entity", "ac")
        entity_id = self._resolve_entity(entity_name)
        try:
            temp = float(args.get("temperature", _extract_number(raw_text) or 22))
        except (TypeError, ValueError):
            return "Please specify a temperature (e.g. 'set the AC to 22 degrees')."
        try:
            self._client.set_temperature(entity_id, temp)
            return f"Set {entity_name} to {temp}°."
        except Exception as exc:
            logger.error("[smart_home] set_temp %s: %s", entity_id, exc)
            return f"Couldn't set temperature: {exc}"


import re as _re


def _extract_entity(text: str, direction: str = "") -> str:
    """Very simple entity extraction from NL text."""
    # Remove command words
    cleaned = _re.sub(
        r"\b(turn\s+on|turn\s+off|switch\s+on|switch\s+off|the|please|friday)\b",
        "", text, flags=_re.IGNORECASE
    ).strip()
    return cleaned or "device"


def _extract_number(text: str) -> Optional[float]:
    m = _re.search(r"\b(\d+(?:\.\d+)?)\b", text)
    return float(m.group(1)) if m else None


Optional = Optional  # re-export for the outer scope
