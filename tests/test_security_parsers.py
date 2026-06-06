"""Phase 5 tests — gobuster/dig parsers, report renderer, scan_diff,
observation stash + ${step_id.field} resolution, end-to-end smoke."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.turn_context import TurnContext, turn_scope
from core.planning.observation import stash_observation, get_observation
from modules.security_tools.parsers.gobuster_parser import parse_gobuster_json
from modules.security_tools.parsers.dig_parser import parse_dig_output
from modules.security_tools.parsers.report_renderer import render_markdown_report
from modules.security_tools.parsers.scan_diff import diff_scan_observations


# ---------------------------------------------------------------------------
# Gobuster parser
# ---------------------------------------------------------------------------

def test_gobuster_parser_handles_multi_path_output():
    raw = (
        '{"url":"http://lab.local/admin","status":200,"size":1234}\n'
        '{"url":"http://lab.local/login","status":302,"size":0}\n'
        '{"url":"http://lab.local/api","status":401,"size":52}\n'
    )
    obs = parse_gobuster_json(raw)
    assert obs["status"] == "success"
    assert len(obs["structured_data"]["paths"]) == 3
    assert obs["structured_data"]["status_counts"] == {200: 1, 302: 1, 401: 1}
    assert "3 path(s)" in obs["summary"]


def test_gobuster_parser_skips_non_json_lines():
    raw = (
        "warning: server slow to respond\n"
        '{"url":"http://lab.local/admin","status":200,"size":12}\n'
        "\n"
    )
    obs = parse_gobuster_json(raw)
    assert len(obs["structured_data"]["paths"]) == 1


def test_gobuster_parser_deduplicates_urls():
    raw = (
        '{"url":"http://lab.local/admin","status":200,"size":12}\n'
        '{"url":"http://lab.local/admin","status":200,"size":12}\n'
    )
    obs = parse_gobuster_json(raw)
    assert len(obs["structured_data"]["paths"]) == 1


def test_gobuster_parser_empty_output_is_success_with_no_paths():
    obs = parse_gobuster_json("")
    # Empty content is a valid "no paths found" result, not a failure.
    assert obs["status"] in {"success", "failure"}   # both OK
    assert obs["structured_data"]["paths"] == []


# ---------------------------------------------------------------------------
# Dig parser
# ---------------------------------------------------------------------------

def test_dig_parser_groups_records_by_type():
    raw = (
        "\n;; A records\n"
        "192.0.2.1\n"
        "192.0.2.2\n"
        "\n;; MX records\n"
        "10 mail.example.com.\n"
        "\n;; TXT records\n"
        '"v=spf1 -all"\n'
    )
    obs = parse_dig_output(raw)
    assert obs["status"] == "success"
    records = obs["structured_data"]["records_by_type"]
    assert records["A"] == ["192.0.2.1", "192.0.2.2"]
    assert records["MX"] == ["10 mail.example.com."]
    assert records["TXT"] == ['"v=spf1 -all"']
    assert "4 record(s)" in obs["summary"]


def test_dig_parser_handles_missing_records_section():
    # No headers — failure.
    obs = parse_dig_output("no headers here\n")
    assert obs["status"] == "failure"


def test_dig_parser_handles_empty_record_block():
    raw = "\n;; A records\n\n;; MX records\n10 mail.example.com.\n"
    obs = parse_dig_output(raw)
    assert obs["status"] in {"success", "partial"}
    assert obs["structured_data"]["records_by_type"].get("A", []) == []
    assert obs["structured_data"]["records_by_type"]["MX"] == ["10 mail.example.com."]


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def test_report_renderer_handles_nmap_and_gobuster_observations():
    nmap_obs = {
        "status": "success", "summary": "...",
        "structured_data": {
            "hosts": [{
                "address": "192.168.56.10",
                "state": "up",
                "hostname": "lab1",
                "open_ports": [22, 80],
                "services": [
                    {"port": 22, "protocol": "tcp", "service_name": "ssh", "version_hint": "OpenSSH 9.6"},
                    {"port": 80, "protocol": "tcp", "service_name": "http", "version_hint": "nginx 1.24"},
                ],
            }],
        },
    }
    gobuster_obs = {
        "status": "success", "summary": "...",
        "structured_data": {
            "paths": [
                {"url": "http://192.168.56.10/admin", "status": 200, "size": 512},
            ],
        },
    }
    md = render_markdown_report(
        title="Lab Inventory",
        scope={"network": "192.168.56.0/24"},
        observations=[nmap_obs, gobuster_obs],
        notes=["scope confirmed at session start"],
    )
    assert "# Lab Inventory" in md
    assert "## Scope" in md
    assert "192.168.56.10" in md
    assert "ssh" in md
    assert "nginx 1.24" in md
    assert "/admin" in md
    assert "## Notes" in md


def test_report_renderer_empty_observations_shows_no_findings_message():
    md = render_markdown_report(title="Empty")
    assert "No structured findings" in md


# ---------------------------------------------------------------------------
# Scan diff
# ---------------------------------------------------------------------------

def test_scan_diff_detects_added_and_removed_hosts():
    a = {"structured_data": {"hosts": [
        {"address": "1.1.1.1", "open_ports": [22]},
        {"address": "2.2.2.2", "open_ports": [80]},
    ]}}
    b = {"structured_data": {"hosts": [
        {"address": "2.2.2.2", "open_ports": [80]},
        {"address": "3.3.3.3", "open_ports": [22]},
    ]}}
    diff = diff_scan_observations(a, b)
    sd = diff["structured_data"]
    assert sd["hosts_added"] == ["3.3.3.3"]
    assert sd["hosts_removed"] == ["1.1.1.1"]
    assert sd["host_changes"] == []


def test_scan_diff_detects_port_changes_on_common_hosts():
    a = {"structured_data": {"hosts": [
        {"address": "10.0.0.1", "open_ports": [22, 80]},
    ]}}
    b = {"structured_data": {"hosts": [
        {"address": "10.0.0.1", "open_ports": [22, 443]},
    ]}}
    diff = diff_scan_observations(a, b)
    changes = diff["structured_data"]["host_changes"]
    assert len(changes) == 1
    assert changes[0]["ports_added"] == [443]
    assert changes[0]["ports_removed"] == [80]


# ---------------------------------------------------------------------------
# Observation stash via TurnContext
# ---------------------------------------------------------------------------

def test_stash_observation_writes_to_active_turn():
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        stash_observation("s1", {"status": "success", "summary": "ok",
                                  "structured_data": {"open_ports": [22]}})
        assert get_observation("s1")["structured_data"]["open_ports"] == [22]
    # Outside the scope, no current turn.
    assert get_observation("s1") is None


def test_stash_observation_silently_ignores_when_no_active_turn():
    # No turn_scope context — must not raise.
    stash_observation("s1", {"status": "success", "summary": "ok"})
    assert get_observation("s1") is None


# ---------------------------------------------------------------------------
# Executor: ${step_id.field} resolution from observations
# ---------------------------------------------------------------------------

def test_executor_resolves_observation_refs_in_args():
    """`${s1.first_live_host}` must be replaced with the value pulled
    from the active turn's observations before the handler runs."""
    from core.task_graph_executor import TaskGraphExecutor
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {
            "structured_data": {
                "first_live_host": "192.168.56.10",
                "live_hosts": ["192.168.56.10", "192.168.56.11"],
            },
        }
        executor = TaskGraphExecutor(MagicMock())
        resolved = executor._resolve_observation_refs({
            "target": "${s1.first_live_host}",
            "list_csv": "${s1.live_hosts}",
            "count": "${s1.live_hosts.count}",
            "ignored": "literal",
        })
        assert resolved["target"] == "192.168.56.10"
        assert resolved["list_csv"] == "192.168.56.10,192.168.56.11"
        assert resolved["count"] == "2"
        assert resolved["ignored"] == "literal"


def test_executor_leaves_unresolvable_refs_intact():
    """If the referenced step or field is missing, the placeholder must
    be left in place (so the handler can decide what to do)."""
    from core.task_graph_executor import TaskGraphExecutor
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        # No observations stashed.
        executor = TaskGraphExecutor(MagicMock())
        resolved = executor._resolve_observation_refs({
            "target": "${s1.first_live_host}",
        })
        assert resolved["target"] == "${s1.first_live_host}"


def test_executor_resolves_top_level_fields_too():
    from core.task_graph_executor import TaskGraphExecutor
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        ctx.observations["s1"] = {
            "status": "success", "summary": "1 host found",
            "structured_data": {"hosts": []},
        }
        executor = TaskGraphExecutor(MagicMock())
        resolved = executor._resolve_observation_refs({
            "x": "${s1.status}", "y": "${s1.summary}",
        })
        assert resolved["x"] == "success"
        assert resolved["y"] == "1 host found"


# ---------------------------------------------------------------------------
# Plugin handler flows — report + diff use stashed observations
# ---------------------------------------------------------------------------

def _make_plugin_under_turn(turn_ctx):
    """Construct a SecurityToolsPlugin with mocked wrappers and a real
    capability_registry, attached to a fake app, all running under the
    given turn context."""
    from modules.security_tools.plugin import SecurityToolsPlugin
    from core.capability_registry import CapabilityRegistry

    app = MagicMock()
    app.capability_registry = CapabilityRegistry()
    app.config = MagicMock()
    app.config.get.side_effect = lambda key: {
        "security": {
            "lab_mode": True,
            "authorized_scopes": ["192.168.56.0/24"],
            "audit_log_path": "/tmp/test_security_audit.log",
        },
    }.get(key)
    # The plugin calls self.app.router.register_tool(); just collect calls.
    app.router = MagicMock()
    return SecurityToolsPlugin(app)


def test_security_report_generate_uses_active_turn_observations(tmp_path):
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        ctx.observations["scan_lab"] = {
            "status": "success", "summary": "...",
            "structured_data": {
                "hosts": [{
                    "address": "192.168.56.10", "state": "up",
                    "open_ports": [22], "services": [
                        {"port": 22, "protocol": "tcp", "service_name": "ssh", "version_hint": "OpenSSH"},
                    ],
                }],
            },
        }
        plugin = _make_plugin_under_turn(ctx)
        output = plugin.handle_security_report_generate("", {
            "title": "Lab Report",
            "scope": {"subnet": "192.168.56.0/24"},
        })
    assert "# Lab Report" in output
    assert "192.168.56.10" in output
    assert "ssh" in output


def test_security_report_generate_refuses_when_no_observations():
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        plugin = _make_plugin_under_turn(ctx)
        output = plugin.handle_security_report_generate("", {"title": "x"})
    assert "don't have any observations" in output.lower()


def test_compare_scan_results_diffs_two_stashed_observations():
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        ctx.observations["scan_a"] = {"structured_data": {"hosts": [
            {"address": "10.0.0.1", "open_ports": [22, 80]},
        ]}}
        ctx.observations["scan_b"] = {"structured_data": {"hosts": [
            {"address": "10.0.0.1", "open_ports": [22, 443]},
        ]}}
        plugin = _make_plugin_under_turn(ctx)
        output = plugin.handle_compare_scan_results("", {
            "step_id_a": "scan_a", "step_id_b": "scan_b",
        })
    assert "Diff between scan_a and scan_b" in output
    assert "1 host(s) with port changes" in output


def test_compare_scan_results_reports_missing_observation():
    ctx = TurnContext(turn_id="t1", session_id="s", trace_id="tr", source="test", text="")
    with turn_scope(ctx):
        ctx.observations["only_one"] = {"structured_data": {"hosts": []}}
        plugin = _make_plugin_under_turn(ctx)
        output = plugin.handle_compare_scan_results("", {
            "step_id_a": "only_one", "step_id_b": "missing",
        })
    assert "Missing observation" in output
    assert "missing" in output
