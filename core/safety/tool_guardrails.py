"""Tool guardrails — pre/post argument validation hooks (P3.17).

ToolGuardrails.check(tool_name, args) runs registered pre-call
validators and returns (ok, reason). Wire into router._invoke_route
or individual plugin handlers for sensitive tools.

Built-in validators:
  - file tools: path_security check on any 'path'/'filename' arg
  - url tools: url_safety check on any 'url' arg
"""
from __future__ import annotations

from typing import Callable

from core.safety.path_security import check_path
from core.safety.url_safety import is_safe_url

_Validator = Callable[[str, dict], tuple[bool, str]]

_FILE_ARG_KEYS = ("path", "filename", "file_path", "filepath", "dest", "destination")
_URL_ARG_KEYS = ("url", "link", "href", "endpoint")

# Tools that operate on the filesystem — path security applied automatically.
_FILE_TOOLS = frozenset({
    "open_file", "read_file", "write_file", "summarize_file", "manage_file",
    "delete_file", "rename_file", "copy_file", "search_file",
})

# Tools that fetch remote URLs — url safety applied automatically.
_URL_TOOLS = frozenset({
    "open_browser_url", "web_search", "web_extract", "web_crawl",
    "fetch_url", "browse",
})


class ToolGuardrails:
    def __init__(self):
        self._validators: dict[str, list[_Validator]] = {}

    def register(self, tool_name: str, validator: _Validator) -> None:
        self._validators.setdefault(tool_name, []).append(validator)

    def check(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Run built-in + registered validators. Returns (ok, reason)."""
        if tool_name in _FILE_TOOLS:
            ok, reason = self._check_file_args(args)
            if not ok:
                return False, reason
        if tool_name in _URL_TOOLS:
            ok, reason = self._check_url_args(args)
            if not ok:
                return False, reason
        for validator in self._validators.get(tool_name, []):
            ok, reason = validator(tool_name, args)
            if not ok:
                return False, reason
        return True, ""

    def _check_file_args(self, args: dict) -> tuple[bool, str]:
        for key in _FILE_ARG_KEYS:
            val = args.get(key)
            if val and isinstance(val, str):
                ok, reason = check_path(val)
                if not ok:
                    return False, f"unsafe path in '{key}': {reason}"
        return True, ""

    def _check_url_args(self, args: dict) -> tuple[bool, str]:
        for key in _URL_ARG_KEYS:
            val = args.get(key)
            if val and isinstance(val, str):
                ok, reason = is_safe_url(val)
                if not ok:
                    return False, f"unsafe URL in '{key}': {reason}"
        return True, ""


# Module-level singleton.
guardrails = ToolGuardrails()
