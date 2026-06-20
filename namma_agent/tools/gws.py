"""Google Workspace tools — Gmail + Calendar via the `gws` CLI.

Ported from the v1 workspace_agent. Thin subprocess wrapper around the `gws` CLI
(https://github.com/googleworkspace/cli). The user authenticates once with
``gws auth login`` (credentials live in the OS keyring); these tools just shell
out and parse JSON. No Google client secrets in our code, no OAuth dance here.

Degrades cleanly: if `gws` isn't installed/authenticated, tools return a clear
message telling the user how to set it up.
"""
from __future__ import annotations

import json
import shutil
import subprocess

from namma_agent.core.tools import ToolRegistry, ToolResult

_TIMEOUT = 25
_SETUP_HINT = ("the `gws` CLI isn't available. Install it from "
               "https://github.com/googleworkspace/cli and run `gws auth login` once.")


def _gws_path():
    return shutil.which("gws") or shutil.which("gws.exe")


def _run(*args: str):
    """Run a gws subcommand; return (ok, parsed_or_text, error)."""
    exe = _gws_path()
    if not exe:
        return False, None, _SETUP_HINT
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, None, "gws timed out"
    except Exception as exc:  # noqa: BLE001
        return False, None, f"gws error: {exc}"
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or out or "").strip()
        if any(s in err.lower() for s in ("not authenticated", "no credentials", "failed to get token")):
            err = "gws isn't authenticated — run `gws auth login`."
        return False, None, err or f"gws exited {proc.returncode}"
    try:
        return True, json.loads(out), ""
    except (json.JSONDecodeError, ValueError):
        return True, out, ""


def _gmail_list(args: dict) -> ToolResult:
    query = (args.get("query") or "is:unread category:primary").strip()
    maxn = str(int(args.get("max", 10)))
    ok, data, err = _run("gmail", "+triage", "--max", maxn, "--query", query, "--format", "json")
    if not ok:
        return ToolResult(ok=False, content="", error=err)
    msgs = data.get("messages", []) if isinstance(data, dict) else (data or [])
    if not msgs:
        return ToolResult(ok=True, content="No matching mail.")
    lines = [f"- [{m.get('id','')}] {m.get('from','')}: {m.get('subject','(no subject)')}"
             for m in msgs]
    return ToolResult(ok=True, content="\n".join(lines), data=msgs)


def _gmail_read(args: dict) -> ToolResult:
    mid = (args.get("id") or "").strip()
    if not mid:
        return ToolResult(ok=False, content="", error="'id' is required")
    ok, data, err = _run("gmail", "+read", "--id", mid, "--format", "json", "--headers")
    if not ok:
        return ToolResult(ok=False, content="", error=err)
    if isinstance(data, dict):
        body = data.get("body_text") or data.get("body") or ""
        head = f"From: {data.get('from')}\nSubject: {data.get('subject')}\nDate: {data.get('date')}\n\n"
        return ToolResult(ok=True, content=head + body[:6000], data=data)
    return ToolResult(ok=True, content=str(data))


def _gmail_send(args: dict) -> ToolResult:
    to, subject, body = args.get("to", ""), args.get("subject", ""), args.get("body", "")
    if not (to and subject):
        return ToolResult(ok=False, content="", error="'to' and 'subject' are required")
    ok, data, err = _run("gmail", "+send", "--to", to, "--subject", subject,
                         "--body", body, "--format", "json")
    if not ok:
        return ToolResult(ok=False, content="", error=err)
    return ToolResult(ok=True, content=f"Email sent to {to}.", data=data)


def _calendar_agenda(args: dict) -> ToolResult:
    span = (args.get("span") or "today").lower()
    cmd = ["calendar", "+agenda", "--format", "json"]
    cmd.append({"today": "--today", "tomorrow": "--tomorrow", "week": "--week"}.get(span, "--today"))
    ok, data, err = _run(*cmd)
    if not ok:
        return ToolResult(ok=False, content="", error=err)
    events = data.get("events", []) if isinstance(data, dict) else (data or [])
    if not events:
        return ToolResult(ok=True, content=f"No events ({span}).")
    lines = [f"- {e.get('start','')}: {e.get('summary','(busy)')}"
             + (f" @ {e.get('location')}" if e.get("location") else "") for e in events]
    return ToolResult(ok=True, content="\n".join(lines), data=events)


def _calendar_create(args: dict) -> ToolResult:
    summary = (args.get("summary") or "").strip()
    start, end = args.get("start", ""), args.get("end", "")
    if not (summary and start and end):
        return ToolResult(ok=False, content="", error="'summary', 'start', and 'end' (ISO datetimes) are required")
    tz = args.get("timezone", "UTC")
    payload = json.dumps({
        "summary": summary, "description": args.get("description", ""),
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
    })
    ok, data, err = _run("calendar", "events", "insert",
                         "--params", json.dumps({"calendarId": "primary"}), "--json", payload)
    if not ok:
        return ToolResult(ok=False, content="", error=err)
    return ToolResult(ok=True, content=f"Created event '{summary}'.", data=data)


def register(registry: ToolRegistry) -> None:
    registry.register("gmail_list", "List recent Gmail messages (default: unread primary inbox).", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search, e.g. 'is:unread' (default unread primary)"},
            "max": {"type": "integer", "description": "max messages (default 10)"},
        },
    }, _gmail_list)

    registry.register("gmail_read", "Read a Gmail message by id.", {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "the message id from gmail_list"}},
        "required": ["id"],
    }, _gmail_read)

    registry.register("gmail_send", "Send an email via Gmail.", {
        "type": "object",
        "properties": {
            "to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"},
        },
        "required": ["to", "subject"],
    }, _gmail_send, destructive=True)

    registry.register("calendar_agenda", "List upcoming Google Calendar events.", {
        "type": "object",
        "properties": {"span": {"type": "string", "enum": ["today", "tomorrow", "week"],
                                "description": "time span (default today)"}},
    }, _calendar_agenda)

    registry.register("calendar_create_event", "Create a Google Calendar event.", {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "event title"},
            "start": {"type": "string", "description": "ISO datetime, e.g. 2026-06-08T15:00:00"},
            "end": {"type": "string", "description": "ISO datetime"},
            "description": {"type": "string"},
            "timezone": {"type": "string", "description": "IANA tz (default UTC)"},
        },
        "required": ["summary", "start", "end"],
    }, _calendar_create, destructive=True)
