"""SecurityToolsPlugin — Kali capability wrappers.

Phase 1: nmap-backed host_service_scan + ping_sweep.
Phase 5: gobuster-backed web_directory_enum, dig-backed
dns_enum_owned_domain, deterministic security_report_generate and
compare_scan_results capabilities. Every wrapper call stashes a
structured Observation into ``current_turn().observations`` so the
replanner (Phase 6) and the executor's ``${step_id.field}`` resolver
can read structured data without re-parsing terminal output.

The LLM only sees compact capability cards (`description`, `aliases`,
`patterns`, `context_terms`). It never sees command strings or flag lists.
All argument validation, scope enforcement, dangerous-flag denial, and
audit logging happen here — not in the model layer.
"""
from __future__ import annotations

import re

from core.logger import logger
from core.plugin_manager import FridayPlugin

try:
    from core.turn_context import current_turn
except Exception:  # pragma: no cover - defensive boundary
    current_turn = None  # type: ignore[assignment]

try:
    from core.planning.observation import stash_observation
except Exception:  # pragma: no cover
    def stash_observation(step_id, observation):  # type: ignore[no-redef]
        return None

from .audit import SecurityAuditLog
from .parsers.nmap_parser import parse_nmap_xml
from .parsers.gobuster_parser import parse_gobuster_json
from .parsers.dig_parser import parse_dig_output
from .parsers.report_renderer import render_markdown_report
from .parsers.scan_diff import diff_scan_observations
from .wrappers.nmap_wrapper import NmapWrapper
from .wrappers.gobuster_wrapper import GobusterWrapper
from .wrappers.dig_wrapper import DigWrapper


# Compact regex patterns for deterministic routing — the IntentRecognizer /
# RouteScorer can pick this up before the LLM gets involved.
_HOST_SCAN_PATTERNS = [
    r"\b(?:scan|nmap|port[\s-]*scan)\b.+\b(?:host|machine|server|ip|localhost|127\.0\.0\.1)\b",
    r"\b(?:open\s+ports?|services?)\b.+\b(?:on|of|for)\b",
    r"\bservice\s+(?:scan|version|enum(?:eration)?)\b",
    # CIDR notation anywhere in the phrase (e.g. "do a network recon on 192.168.1.0/24")
    r"\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b",
]
_PING_SWEEP_PATTERNS = [
    r"\b(?:ping[\s-]*sweep|host\s+discovery|live\s+hosts?)\b",
    r"\b(?:discover|find|list)\s+(?:live\s+|active\s+)?hosts?\b",
    # Free-form network scan/recon phrases (P1.1)
    r"\b(?:scan\s+(?:my\s+|the\s+)?network|network\s+(?:scan|recon(?:naissance)?)|recon\s+(?:the\s+)?network|do\s+(?:a\s+)?(?:network\s+)?recon)\b",
]
_WEB_DIR_PATTERNS = [
    r"\b(?:gobuster|dirbuster|ffuf|fuzz)\b",
    r"\b(?:directory|path|content)\s+(?:enum|enumeration|brute[\s-]*force|discovery)\b",
    r"\benumerate\s+(?:directories|paths|content)\b",
]
_DNS_ENUM_PATTERNS = [
    r"\b(?:dns|nameserver|name[\s-]*server|record(?:s)?)\s+(?:enum|enumeration|lookup|inventory)\b",
    r"\b(?:enumerate|look\s+up|inventory)\s+(?:dns|records?)\b",
    r"\bdig\b.+\b(?:records?|domain)\b",
]
_REPORT_PATTERNS = [
    r"\b(?:generate|build|produce|create)\s+(?:a\s+)?(?:security\s+|markdown\s+)?report\b",
    r"\bsummari[sz]e\s+(?:the\s+)?(?:scan|recon|findings)\b",
]
_DIFF_PATTERNS = [
    r"\b(?:diff|compare|delta)\s+(?:two\s+)?scans?\b",
    r"\bwhat[' ]?s?\s+changed\s+between\b",
]


class SecurityToolsPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "security_tools"
        self.on_load()

    def _get_cfg(self) -> dict:
        cfg = getattr(self.app, "config", None)
        if cfg and hasattr(cfg, "get"):
            return cfg.get("security") or {}
        return {}

    def on_load(self) -> None:
        cfg = self._get_cfg()
        if not cfg.get("lab_mode", False):
            logger.info(
                "[security_tools] Plugin idle — set security.lab_mode: true and "
                "populate security.authorized_scopes in config.yaml to enable."
            )
            return

        self._authorized_scopes = list(cfg.get("authorized_scopes") or [])
        self._audit = SecurityAuditLog(cfg.get("audit_log_path") or "logs/security_audit.log")
        timeout = int(cfg.get("default_timeout_sec") or 120)
        self._nmap = NmapWrapper(
            nmap_binary=cfg.get("nmap_binary") or "nmap",
            default_timeout_sec=timeout,
            authorized_scopes=self._authorized_scopes,
        )
        self._gobuster = GobusterWrapper(
            gobuster_binary=cfg.get("gobuster_binary") or "gobuster",
            default_timeout_sec=timeout,
            authorized_scopes=self._authorized_scopes,
        )
        self._dig = DigWrapper(
            dig_binary=cfg.get("dig_binary") or "dig",
            default_timeout_sec=int(cfg.get("dig_timeout_sec") or 30),
        )

        self._register_host_service_scan()
        self._register_ping_sweep()
        self._register_web_directory_enum()
        self._register_dns_enum_owned_domain()
        self._register_security_report_generate()
        self._register_compare_scan_results()
        logger.info(
            "[security_tools] Loaded — 6 capabilities registered "
            "(authorized_scopes=%d)", len(self._authorized_scopes),
        )

    # ------------------------------------------------------------------
    # Capability registration
    # ------------------------------------------------------------------

    def _register_host_service_scan(self) -> None:
        self.app.register_capability(
            {
                "name": "host_service_scan",
                "description": (
                    "Read-only TCP service/version scan of an authorized lab or "
                    "loopback host using nmap. Returns open ports and detected "
                    "service versions. Refuses any target outside the configured "
                    "authorized_scopes."
                ),
                "parameters": {
                    "target": "string — IPv4/IPv6/hostname of the authorized host to scan",
                    "profile": "string — 'quick' (default), 'standard', or 'safe_deep'",
                    "ports": "string — optional port spec like '22,80,443' or '1-1024'",
                },
                "aliases": [
                    "port scan", "service scan", "scan host", "nmap host",
                    "open ports", "what services are running",
                    "service enumeration", "version scan",
                    "scan this host", "scan that host", "scan subnet",
                    "recon host", "recon subnet",
                ],
                "patterns": _HOST_SCAN_PATTERNS,
                "context_terms": [
                    "nmap", "port", "scan", "service", "ssh", "http",
                    "open", "tcp", "version", "enumerate",
                ],
            },
            self.handle_host_service_scan,
            metadata={
                "connectivity": "local",
                "latency_class": "slow",
                "permission_mode": "always_ok",  # scope check is the real gate
                "side_effect_level": "read",
                "network_scope": "lab",
                "requires_authorization": True,
                "allowed_use_cases": [
                    "scan my own machine",
                    "scan an authorized lab host",
                    "service inventory in my lab subnet",
                ],
                "forbidden_use_cases": [
                    "unauthorized scanning of public targets",
                    "stealth/evasion scanning",
                    "exploit delivery",
                ],
                "command_templates": {
                    "quick": "nmap -sT --open -oX - -T4 --top-ports 100 <target>",
                    "standard": "nmap -sT --open -oX - -T3 --top-ports 1000 -sV <target>",
                    "safe_deep": "nmap -sT --open -oX - -T2 -p- -sV <target>",
                },
                "argument_constraints": {
                    "target": "IPv4|IPv6|hostname; must match an authorized_scope",
                    "profile": "enum: quick | standard | safe_deep",
                    "ports": "optional; '80,443' or '1-1024' format",
                    "deny_flags": [
                        "--script", "-O", "-f", "--mtu", "-D", "-S",
                    ],
                },
                "parser": "nmap_xml_v1",
                "success_conditions": [
                    "structured host list emitted",
                    "process exit code 0",
                ],
                "failure_conditions": [
                    "target outside authorized_scopes",
                    "process timeout",
                    "process exit code != 0",
                ],
                "next_step_hints": [
                    "if http service found, suggest web_app_recon",
                    "if dns service found, suggest dns_enum_owned_domain",
                ],
                "rollback_or_cleanup": [],
                "logging_requirements": [
                    "trace_id", "turn_id", "source", "target",
                    "command", "status", "exit_ms",
                ],
            },
        )

    def _register_ping_sweep(self) -> None:
        self.app.register_capability(
            {
                "name": "ping_sweep",
                "description": (
                    "Read-only host discovery (-sn) across an authorized subnet. "
                    "Returns the list of live hosts. Refuses any subnet outside "
                    "the configured authorized_scopes."
                ),
                "parameters": {
                    "subnet": "string — IPv4 CIDR (e.g. 192.168.56.0/24) or single host",
                },
                "aliases": [
                    "ping sweep", "host discovery", "find live hosts",
                    "list live hosts", "who's up", "discover hosts",
                    "scan my network", "scan the network", "network recon",
                    "network reconnaissance", "recon the network", "do a network scan",
                    "network scan", "do a recon",
                ],
                "patterns": _PING_SWEEP_PATTERNS,
                "context_terms": [
                    "ping", "sweep", "live", "hosts", "subnet", "discover",
                ],
            },
            self.handle_ping_sweep,
            metadata={
                "connectivity": "local",
                "latency_class": "slow",
                "permission_mode": "always_ok",
                "side_effect_level": "read",
                "network_scope": "lab",
                "requires_authorization": True,
                "allowed_use_cases": [
                    "discover live hosts in my lab subnet",
                ],
                "forbidden_use_cases": [
                    "internet-wide host discovery",
                    "unauthorized subnet scanning",
                ],
                "command_templates": {
                    "default": "nmap -sn -oX - <subnet>",
                },
                "argument_constraints": {
                    "subnet": "IPv4/IPv6 CIDR or single host; must match authorized_scope",
                },
                "parser": "nmap_xml_v1",
                "success_conditions": ["host list emitted (may be empty)"],
                "failure_conditions": ["subnet outside authorized_scopes", "process timeout"],
                "next_step_hints": ["for each live host, suggest host_service_scan"],
                "logging_requirements": [
                    "trace_id", "turn_id", "source", "subnet",
                    "command", "status", "exit_ms",
                ],
            },
        )

    def _register_web_directory_enum(self) -> None:
        self.app.register_capability(
            {
                "name": "web_directory_enum",
                "description": (
                    "Enumerate directories/paths on an authorized lab web "
                    "server using gobuster. Read-only. Refuses URLs whose "
                    "host falls outside authorized_scopes."
                ),
                "parameters": {
                    "base_url": "string — http(s)://<host>[:port] (host must be in authorized_scopes)",
                    "wordlist": "string — registered wordlist name or absolute path",
                    "threads": "int — concurrency (1..50, default 10)",
                    "extensions": "string — comma-separated, e.g. 'php,html'",
                },
                "aliases": [
                    "directory brute force", "directory enumeration",
                    "gobuster", "path enum", "find directories",
                    "enumerate paths", "fuzz directories",
                ],
                "patterns": _WEB_DIR_PATTERNS,
                "context_terms": [
                    "directory", "path", "dirbuster", "gobuster", "ffuf",
                    "web", "http", "https", "enumeration",
                ],
            },
            self.handle_web_directory_enum,
            metadata={
                "connectivity": "local",
                "latency_class": "slow",
                "permission_mode": "always_ok",
                "side_effect_level": "read",
                "network_scope": "lab",
                "requires_authorization": True,
                "allowed_use_cases": [
                    "directory inventory on an authorized lab web app",
                    "CTF web challenge after scope confirmation",
                ],
                "forbidden_use_cases": [
                    "unauthorized internet directory brute force",
                    "evasion / stealth fuzzing",
                ],
                "command_templates": {
                    "dir": "gobuster dir -u <base_url> -w <wordlist> -t <threads> --format json",
                },
                "argument_constraints": {
                    "base_url": "http(s) URL; host must match authorized_scope",
                    "wordlist": "registered name or absolute path",
                    "threads": "1..50",
                },
                "parser": "gobuster_json_v1",
                "success_conditions": ["path list emitted (may be empty)"],
                "failure_conditions": ["host outside authorized_scopes", "wordlist missing", "timeout"],
                "next_step_hints": [
                    "if interesting paths found, suggest security_report_generate",
                ],
                "logging_requirements": [
                    "trace_id", "turn_id", "source", "base_url",
                    "command", "status", "exit_ms",
                ],
            },
        )

    def _register_dns_enum_owned_domain(self) -> None:
        self.app.register_capability(
            {
                "name": "dns_enum_owned_domain",
                "description": (
                    "Read-only DNS enumeration for a domain the user owns "
                    "or has authorization to query. Returns records grouped "
                    "by type (A, AAAA, MX, NS, TXT, SOA, CNAME, PTR, SRV, CAA)."
                ),
                "parameters": {
                    "domain": "string — DNS name",
                    "record_types": "string — comma-separated, default 'A,AAAA,MX,NS,TXT'",
                },
                "aliases": [
                    "dns enum", "dns enumeration", "lookup dns",
                    "dns records", "enumerate domain", "dig",
                ],
                "patterns": _DNS_ENUM_PATTERNS,
                "context_terms": [
                    "dns", "domain", "record", "mx", "ns", "txt", "soa", "cname",
                ],
            },
            self.handle_dns_enum_owned_domain,
            metadata={
                "connectivity": "online",
                "latency_class": "fast",
                "permission_mode": "always_ok",
                "side_effect_level": "read",
                # DNS lookups are inherently outbound to authoritative servers,
                # but they're always read-only public queries. We declare scope
                # "public" because the LLM may target external DNS — the
                # ownership/authorization claim is the user's responsibility.
                "network_scope": "public",
                "requires_authorization": False,
                "allowed_use_cases": [
                    "owned domain DNS inventory",
                    "lab domain enumeration",
                    "CTF DNS challenge",
                ],
                "forbidden_use_cases": [
                    "AXFR zone transfer attempts against unauthorized servers",
                    "DNS amplification / abuse",
                ],
                "command_templates": {
                    "default": "dig +short -t <RECORD_TYPE> <domain>  (one call per record type)",
                },
                "argument_constraints": {
                    "domain": "valid DNS label syntax",
                    "record_types": "comma-separated; only A/AAAA/MX/NS/TXT/SOA/CNAME/PTR/SRV/CAA allowed",
                },
                "parser": "dig_text_v1",
                "success_conditions": ["records emitted (may be empty)"],
                "failure_conditions": ["invalid domain", "dig binary missing", "timeout"],
                "next_step_hints": [
                    "if MX present, include in report",
                    "if A records found and authorized, suggest host_service_scan",
                ],
                "logging_requirements": [
                    "trace_id", "turn_id", "source", "domain",
                    "command", "status", "exit_ms",
                ],
            },
        )

    def _register_security_report_generate(self) -> None:
        self.app.register_capability(
            {
                "name": "security_report_generate",
                "description": (
                    "Generate a markdown security report from previously "
                    "collected scan observations stored in the active turn. "
                    "Deterministic — no shell, no LLM."
                ),
                "parameters": {
                    "title": "string — report title (default 'Security Report')",
                    "step_ids": "list — step IDs whose observations to include "
                                 "(defaults to ALL observations in this turn)",
                    "scope": "dict — optional scope summary",
                    "notes": "list — optional caller-supplied notes",
                },
                "aliases": [
                    "generate report", "build report", "produce report",
                    "summarize findings", "make a markdown report",
                ],
                "patterns": _REPORT_PATTERNS,
                "context_terms": ["report", "summary", "findings", "markdown"],
            },
            self.handle_security_report_generate,
            metadata={
                "connectivity": "local",
                "latency_class": "fast",
                "permission_mode": "always_ok",
                "side_effect_level": "read",
                "network_scope": "local",
                "requires_authorization": False,
                "allowed_use_cases": [
                    "summarize prior scan output into a markdown report",
                ],
                "forbidden_use_cases": [],
                "parser": "",
                "success_conditions": ["markdown report emitted"],
                "failure_conditions": ["no observations available in this turn"],
                "next_step_hints": [],
                "logging_requirements": ["trace_id", "turn_id", "source", "step_ids"],
            },
        )

    def _register_compare_scan_results(self) -> None:
        self.app.register_capability(
            {
                "name": "compare_scan_results",
                "description": (
                    "Diff two structured scan observations (e.g. two "
                    "host_service_scan results) and emit added/removed/changed "
                    "hosts and ports. Deterministic."
                ),
                "parameters": {
                    "step_id_a": "string — step_id of the baseline observation",
                    "step_id_b": "string — step_id of the comparison observation",
                },
                "aliases": [
                    "diff scans", "compare scans", "what changed between scans",
                    "scan delta",
                ],
                "patterns": _DIFF_PATTERNS,
                "context_terms": ["diff", "compare", "delta", "changed", "between"],
            },
            self.handle_compare_scan_results,
            metadata={
                "connectivity": "local",
                "latency_class": "fast",
                "permission_mode": "always_ok",
                "side_effect_level": "read",
                "network_scope": "local",
                "requires_authorization": False,
                "allowed_use_cases": [
                    "compare two prior scan outputs in the same turn",
                ],
                "forbidden_use_cases": [],
                "parser": "",
                "success_conditions": ["diff emitted"],
                "failure_conditions": ["one or both step observations missing"],
                "next_step_hints": ["pass diff to security_report_generate"],
                "logging_requirements": ["trace_id", "turn_id", "source", "step_id_a", "step_id_b"],
            },
        )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def handle_host_service_scan(self, text: str, args: dict) -> str:
        args = dict(args or {})
        target = (args.get("target") or "").strip() or self._extract_target(text or "")
        if not target:
            return "Which host should I scan? Give me an IP or hostname inside your authorized scopes."

        profile = (args.get("profile") or "quick").strip().lower()
        ports = (args.get("ports") or None)
        if ports is not None:
            ports = str(ports).strip() or None

        result = self._nmap.host_service_scan(
            target=target,
            profile=profile,
            ports=ports,
            allowed_scope="lab",
        )

        step_id = self._step_id(args, default="host_service_scan")
        self._audit_call(
            capability="host_service_scan",
            mode=profile,
            target=target,
            args={"profile": profile, "ports": ports},
            result=result,
        )

        if result.status == "refused":
            return f"I can't scan {target}: {result.reason}."
        if result.status == "timeout":
            return f"The scan of {target} timed out after {self._nmap.default_timeout}s."
        if result.status != "success":
            return f"Scan failed: {result.reason or 'unknown error'}"

        observation = parse_nmap_xml(result.raw_stdout)
        observation.setdefault("capability", "host_service_scan")
        observation.setdefault("step_id", step_id)
        stash_observation(step_id, observation)
        return self._format_host_scan_response(target, observation)

    def handle_ping_sweep(self, text: str, args: dict) -> str:
        args = dict(args or {})
        subnet = (args.get("subnet") or "").strip() or self._extract_target(text or "")
        if not subnet:
            return "Which subnet should I sweep? Provide a CIDR like 192.168.56.0/24."

        result = self._nmap.ping_sweep(subnet=subnet, allowed_scope="lab")
        step_id = self._step_id(args, default="ping_sweep")
        self._audit_call(
            capability="ping_sweep",
            mode="default",
            target=subnet,
            args={"subnet": subnet},
            result=result,
        )

        if result.status == "refused":
            return f"I can't sweep {subnet}: {result.reason}."
        if result.status == "timeout":
            return f"Ping sweep of {subnet} timed out."
        if result.status != "success":
            return f"Ping sweep failed: {result.reason or 'unknown error'}"

        observation = parse_nmap_xml(result.raw_stdout)
        observation.setdefault("capability", "ping_sweep")
        observation.setdefault("step_id", step_id)
        # Add a flattened first_live_host convenience key — used by the
        # lab_network_inventory template's ${s1.first_live_host} ref.
        live = [h for h in observation["structured_data"]["hosts"] if h["state"] == "up"]
        observation["structured_data"]["first_live_host"] = live[0]["address"] if live else ""
        observation["structured_data"]["live_hosts"] = [h["address"] for h in live]
        stash_observation(step_id, observation)
        if not live:
            return f"No live hosts found in {subnet}."
        addrs = ", ".join(h["address"] for h in live[:20])
        more = "" if len(live) <= 20 else f" (+{len(live) - 20} more)"
        return f"{len(live)} live host(s) in {subnet}: {addrs}{more}."

    def handle_web_directory_enum(self, text: str, args: dict) -> str:
        args = dict(args or {})
        base_url = (args.get("base_url") or "").strip() or self._extract_url(text or "")
        if not base_url:
            return "Which URL should I enumerate? Provide an http(s) URL inside your authorized scopes."

        wordlist = (args.get("wordlist") or "common_paths").strip()
        threads = int(args.get("threads") or 10)
        extensions = (args.get("extensions") or "").strip()

        result = self._gobuster.dir_enum(
            base_url=base_url,
            wordlist=wordlist,
            threads=threads,
            extensions=extensions,
            allowed_scope="lab",
        )
        step_id = self._step_id(args, default="web_directory_enum")
        self._audit_call(
            capability="web_directory_enum",
            mode="dir",
            target=base_url,
            args={"wordlist": wordlist, "threads": threads, "extensions": extensions},
            result=result,
        )

        if result.status == "refused":
            return f"I can't enumerate {base_url}: {result.reason}."
        if result.status == "timeout":
            return f"Directory enumeration of {base_url} timed out."
        if result.status != "success":
            return f"Directory enumeration failed: {result.reason or 'unknown error'}"

        observation = parse_gobuster_json(result.raw_stdout)
        observation.setdefault("capability", "web_directory_enum")
        observation.setdefault("step_id", step_id)
        stash_observation(step_id, observation)
        paths = observation["structured_data"]["paths"]
        if not paths:
            return f"No paths discovered at {base_url}."
        sample = ", ".join(p["url"] for p in paths[:8])
        more = "" if len(paths) <= 8 else f" (+{len(paths) - 8} more)"
        return f"{len(paths)} path(s) discovered at {base_url}: {sample}{more}."

    def handle_dns_enum_owned_domain(self, text: str, args: dict) -> str:
        args = dict(args or {})
        domain = (args.get("domain") or "").strip() or self._extract_domain(text or "")
        if not domain:
            return "Which domain should I enumerate? Provide a DNS name like example.com."

        record_types = args.get("record_types") or "A,AAAA,MX,NS,TXT"
        result = self._dig.enumerate(domain=domain, record_types=record_types)
        step_id = self._step_id(args, default="dns_enum_owned_domain")
        self._audit_call(
            capability="dns_enum_owned_domain",
            mode="default",
            target=domain,
            args={"record_types": record_types},
            result=result,
        )

        if result.status == "refused":
            return f"I can't enumerate {domain}: {result.reason}."
        if result.status == "timeout":
            return f"DNS enumeration of {domain} timed out."
        if result.status != "success":
            return f"DNS enumeration failed: {result.reason or 'unknown error'}"

        observation = parse_dig_output(result.raw_stdout)
        observation.setdefault("capability", "dns_enum_owned_domain")
        observation.setdefault("step_id", step_id)
        stash_observation(step_id, observation)
        records = observation["structured_data"]["records_by_type"]
        summary_lines = [f"DNS records for {domain}:"]
        for rtype, values in records.items():
            if values:
                summary_lines.append(f"  {rtype}: {', '.join(values[:6])}"
                                     + ("..." if len(values) > 6 else ""))
        if len(summary_lines) == 1:
            return f"No DNS records returned for {domain}."
        return "\n".join(summary_lines)

    def handle_security_report_generate(self, text: str, args: dict) -> str:
        args = dict(args or {})
        title = (args.get("title") or "Security Report").strip()
        step_ids = args.get("step_ids") or []
        if isinstance(step_ids, str):
            step_ids = [s.strip() for s in step_ids.split(",") if s.strip()]
        scope = args.get("scope") if isinstance(args.get("scope"), dict) else None
        notes = args.get("notes") if isinstance(args.get("notes"), list) else None

        observations = self._collect_observations(step_ids)
        if not observations:
            return ("I don't have any observations from this turn yet to "
                    "build a report. Run a scan first, then ask for the report.")

        markdown = render_markdown_report(
            title=title,
            scope=scope,
            observations=observations,
            notes=notes,
        )
        # Also stash the rendered report as its own observation so a follow-up
        # step (e.g. Telegram send) can grab it.
        step_id = self._step_id(args, default="security_report_generate")
        stash_observation(step_id, {
            "step_id": step_id,
            "capability": "security_report_generate",
            "status": "success",
            "summary": f"report generated ({len(observations)} source observation(s))",
            "structured_data": {"markdown": markdown, "source_step_ids": step_ids},
            "errors": [],
        })
        return markdown

    def handle_compare_scan_results(self, text: str, args: dict) -> str:
        args = dict(args or {})
        step_id_a = str(args.get("step_id_a") or "").strip()
        step_id_b = str(args.get("step_id_b") or "").strip()
        if not step_id_a or not step_id_b:
            return "I need two step_ids to compare. Specify step_id_a and step_id_b."

        ctx = current_turn() if current_turn else None
        observations = (ctx.observations if ctx is not None else {}) or {}
        obs_a = observations.get(step_id_a)
        obs_b = observations.get(step_id_b)
        if obs_a is None or obs_b is None:
            missing = [s for s, o in [(step_id_a, obs_a), (step_id_b, obs_b)] if o is None]
            return f"Missing observation(s) for step(s): {', '.join(missing)}."

        diff = diff_scan_observations(obs_a, obs_b)
        step_id = self._step_id(args, default="compare_scan_results")
        diff["step_id"] = step_id
        diff["capability"] = "compare_scan_results"
        stash_observation(step_id, diff)
        sd = diff["structured_data"]
        return (
            f"Diff between {step_id_a} and {step_id_b}: "
            f"hosts +{len(sd['hosts_added'])}/-{len(sd['hosts_removed'])}, "
            f"{len(sd['host_changes'])} host(s) with port changes."
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _URL_RE = re.compile(r"\bhttps?://[A-Za-z0-9\.\-:/_%~]+", re.IGNORECASE)
    _DOMAIN_RE = re.compile(r"\b([a-z0-9][a-z0-9\-]*\.)+[a-z]{2,}\b", re.IGNORECASE)

    def _extract_url(self, text: str) -> str:
        m = self._URL_RE.search(text or "")
        return m.group(0) if m else ""

    def _extract_domain(self, text: str) -> str:
        m = self._DOMAIN_RE.search(text or "")
        return m.group(0) if m else ""

    def _step_id(self, args: dict, *, default: str) -> str:
        """Return the step_id under which observations should be stashed.

        The TaskGraphExecutor injects upstream outputs under each dependency's
        node_id (not the current step's). Capability handlers therefore have
        no direct knowledge of their own node_id. The convention: if the
        planner has set ``args["__step_id__"]`` (via Phase 6+ wiring) use
        that; otherwise fall back to the capability name.
        """
        sid = (args.get("__step_id__") if isinstance(args, dict) else None) or default
        return str(sid)

    def _collect_observations(self, step_ids: list[str]) -> list[dict]:
        ctx = current_turn() if current_turn else None
        store = (ctx.observations if ctx is not None else {}) or {}
        if step_ids:
            return [store[s] for s in step_ids if s in store]
        # Default: include every observation from this turn, in insertion order.
        return list(store.values())

    _TARGET_TOKEN_RE = re.compile(
        r"\b("
        r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?:/[0-9]{1,2})?"
        r"|localhost"
        r")\b"
    )

    def _extract_target(self, text: str) -> str:
        m = self._TARGET_TOKEN_RE.search(text or "")
        return m.group(1) if m else ""

    def _format_host_scan_response(self, target: str, obs: dict) -> str:
        hosts = obs.get("structured_data", {}).get("hosts", [])
        if not hosts:
            return f"No host data returned for {target}."
        host = hosts[0]
        if host["state"] != "up":
            return f"{target} appears down or filtered."
        services = host.get("services") or []
        if not services:
            return f"{target} is up but no open TCP ports were found."
        lines = [f"{target} is up. Open services:"]
        for svc in services[:15]:
            ver = f" ({svc['version_hint']})" if svc.get("version_hint") else ""
            lines.append(f"  - {svc['port']}/{svc['protocol']} {svc['service_name'] or '?'}{ver}")
        if len(services) > 15:
            lines.append(f"  ...and {len(services) - 15} more.")
        return "\n".join(lines)

    def _audit_call(self, *, capability: str, mode: str, target: str, args: dict, result) -> None:
        ctx = current_turn() if current_turn else None
        trace_id = getattr(ctx, "trace_id", "") if ctx else ""
        turn_id = getattr(ctx, "turn_id", "") if ctx else ""
        source = getattr(ctx, "source", "") if ctx else ""
        self._audit.write({
            "trace_id": trace_id,
            "turn_id": turn_id,
            "source": source,
            "capability": capability,
            "mode": mode,
            "target": target,
            "args": args,
            "command": result.command,
            "status": result.status,
            "exit_ms": result.exec_ms,
            "reason": result.reason,
        })
