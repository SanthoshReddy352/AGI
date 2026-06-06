"""Deterministic diff between two structured scan observations.

Compares two parser-output dicts (typically ``parse_nmap_xml`` results
indexed by host/port) and produces a structured diff describing added,
removed, and changed entries. Pure function.
"""
from __future__ import annotations

from typing import Any


def diff_scan_observations(a: dict, b: dict) -> dict[str, Any]:
    """Diff two scan observations (nmap-style ``structured_data.hosts``)."""
    hosts_a = _index_hosts((a or {}).get("structured_data") or {})
    hosts_b = _index_hosts((b or {}).get("structured_data") or {})

    a_keys, b_keys = set(hosts_a), set(hosts_b)
    added_hosts = sorted(b_keys - a_keys)
    removed_hosts = sorted(a_keys - b_keys)
    common = sorted(a_keys & b_keys)

    changed: list[dict[str, Any]] = []
    port_added = 0
    port_removed = 0
    for host in common:
        ports_a = set(hosts_a[host]["open_ports"])
        ports_b = set(hosts_b[host]["open_ports"])
        new_ports = sorted(ports_b - ports_a)
        gone_ports = sorted(ports_a - ports_b)
        if new_ports or gone_ports:
            changed.append({
                "host": host,
                "ports_added": new_ports,
                "ports_removed": gone_ports,
            })
            port_added += len(new_ports)
            port_removed += len(gone_ports)

    summary = (
        f"hosts: +{len(added_hosts)} / -{len(removed_hosts)}; "
        f"ports: +{port_added} / -{port_removed} on "
        f"{len(changed)} common host(s)"
    )
    return {
        "status": "success",
        "summary": summary,
        "structured_data": {
            "hosts_added": added_hosts,
            "hosts_removed": removed_hosts,
            "host_changes": changed,
        },
        "errors": [],
    }


def _index_hosts(structured: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for h in structured.get("hosts") or []:
        addr = h.get("address") or ""
        if addr:
            out[addr] = {
                "open_ports": list(h.get("open_ports") or []),
                "services": h.get("services") or [],
            }
    return out
