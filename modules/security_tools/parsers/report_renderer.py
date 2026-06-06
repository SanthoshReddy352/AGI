"""Markdown report renderer for security workflow output.

Consumes a list of structured observations (the dicts produced by the
nmap / gobuster / dig parsers) and produces a markdown report. Pure
function — no I/O, no LLM, no shell.

Supported sections (auto-detected from the observation list):

- ``scope``   — target / authorization summary supplied by the caller
- ``hosts``   — from nmap-style observations
- ``services``— flattened service list across hosts
- ``paths``   — from gobuster observations
- ``records`` — from dig observations
- ``notes``   — caller-supplied free text
"""
from __future__ import annotations

from typing import Any


def render_markdown_report(
    *,
    title: str = "Security Report",
    scope: dict[str, Any] | None = None,
    observations: list[dict] | None = None,
    notes: list[str] | None = None,
) -> str:
    parts: list[str] = [f"# {title}", ""]

    if scope:
        parts.append("## Scope")
        for key, value in scope.items():
            parts.append(f"- **{key}**: {value}")
        parts.append("")

    obs = observations or []
    hosts = _collect_hosts(obs)
    paths = _collect_paths(obs)
    records = _collect_records(obs)

    if hosts:
        parts.append("## Live Hosts")
        for h in hosts:
            line = f"- `{h['address']}`"
            if h.get("hostname"):
                line += f" ({h['hostname']})"
            line += f" — state: {h.get('state', 'unknown')}"
            parts.append(line)
        parts.append("")

        services = _collect_services(hosts)
        if services:
            parts.append("## Services")
            parts.append("| Host | Port | Proto | Service | Version |")
            parts.append("|---|---|---|---|---|")
            for s in services:
                parts.append(
                    f"| {s['host']} | {s['port']} | {s['protocol']} | "
                    f"{s['service_name'] or '?'} | {s['version_hint'] or ''} |"
                )
            parts.append("")

    if paths:
        parts.append("## Discovered Paths")
        parts.append("| URL | Status | Size |")
        parts.append("|---|---|---|")
        for p in paths[:200]:
            parts.append(f"| {p['url']} | {p['status']} | {p['size']} |")
        if len(paths) > 200:
            parts.append(f"\n*(...and {len(paths) - 200} more)*")
        parts.append("")

    if records:
        parts.append("## DNS Records")
        for rtype, values in records.items():
            if not values:
                continue
            parts.append(f"### {rtype}")
            for v in values:
                parts.append(f"- `{v}`")
            parts.append("")

    if notes:
        parts.append("## Notes")
        for n in notes:
            parts.append(f"- {n}")
        parts.append("")

    if len(parts) <= 2:
        parts.append("*No structured findings to report.*")

    return "\n".join(parts).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def _collect_hosts(observations: list[dict]) -> list[dict]:
    out: list[dict] = []
    for obs in observations or []:
        data = (obs or {}).get("structured_data") or {}
        for h in data.get("hosts") or []:
            out.append(h)
    return out


def _collect_services(hosts: list[dict]) -> list[dict]:
    out: list[dict] = []
    for h in hosts:
        for s in h.get("services") or []:
            out.append({"host": h.get("address", ""), **s})
    return out


def _collect_paths(observations: list[dict]) -> list[dict]:
    out: list[dict] = []
    for obs in observations or []:
        data = (obs or {}).get("structured_data") or {}
        for p in data.get("paths") or []:
            out.append(p)
    return out


def _collect_records(observations: list[dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for obs in observations or []:
        data = (obs or {}).get("structured_data") or {}
        rbt = data.get("records_by_type") or {}
        for rtype, values in rbt.items():
            out.setdefault(rtype, []).extend(values)
    return out
