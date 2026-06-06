"""gobuster capability wrapper.

The LLM picks a *mode* (``dir`` for path enum) and provides validated
JSON args. The wrapper composes the actual argv from a fixed template
and refuses if any safety check fails.

Modes:
- dir: HTTP directory/path enumeration against an authorized lab URL.

Output is captured as gobuster's JSON output (``-q -o /dev/stdout
--no-progress -t N`` plus ``--output-format json``) and returned as
bytes for the parser to convert into a structured Observation.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from core.logger import logger

from ..safety import block_dangerous_flags


# Built-in safe wordlists. The LLM picks a name; the wrapper resolves it
# to a path. Falls back gracefully if the file is missing.
_WORDLIST_REGISTRY = {
    "common_paths": "/usr/share/wordlists/dirb/common.txt",
    "small_paths": "/usr/share/wordlists/dirb/small.txt",
    "directory-list-2.3-small": "/usr/share/wordlists/dirbuster/directory-list-2.3-small.txt",
}


@dataclass
class WrapperResult:
    ok: bool
    status: str
    raw_stdout: bytes = b""
    raw_stderr: str = ""
    command: str = ""
    exec_ms: int = 0
    reason: str = ""


def _is_authorized_url(base_url: str, allowed_scope: str, authorized_scopes: list[str]) -> tuple[bool, str]:
    """Validate that a URL's host falls within the allowed scope+allowlist.

    Reuses ``PermissionService`` so the rule is consistent with the nmap
    wrapper and PlanValidator.
    """
    from core.kernel.permissions import PermissionService

    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return False, f"could not extract host from URL {base_url!r}"
    if parsed.scheme not in {"http", "https"}:
        return False, f"unsupported URL scheme {parsed.scheme!r}"

    perms = PermissionService()
    scope_ok, scope_reason = perms.check_network_scope(host, allowed_scope)
    if not scope_ok:
        return False, scope_reason
    if allowed_scope in ("lab", "public") and authorized_scopes:
        auth_ok, auth_reason = perms.check_authorized_target(host, authorized_scopes)
        if not auth_ok:
            return False, auth_reason
    return True, "ok"


class GobusterWrapper:
    def __init__(
        self,
        *,
        gobuster_binary: str = "gobuster",
        default_timeout_sec: int = 120,
        authorized_scopes: list[str] | None = None,
        wordlist_registry: dict[str, str] | None = None,
    ):
        self.binary = gobuster_binary
        self.default_timeout = int(default_timeout_sec)
        self.authorized_scopes = list(authorized_scopes or [])
        self.wordlists = dict(_WORDLIST_REGISTRY)
        self.wordlists.update(wordlist_registry or {})

    def dir_enum(
        self,
        base_url: str,
        *,
        wordlist: str = "common_paths",
        threads: int = 10,
        allowed_scope: str = "lab",
        timeout_sec: int | None = None,
        extensions: str = "",
    ) -> WrapperResult:
        url_ok, url_reason = _is_authorized_url(
            base_url, allowed_scope, self.authorized_scopes,
        )
        if not url_ok:
            return WrapperResult(ok=False, status="refused", reason=url_reason)

        wordlist_path = self.wordlists.get(wordlist) or wordlist
        if "/" in wordlist_path:
            import os
            if not os.path.exists(wordlist_path):
                return WrapperResult(
                    ok=False, status="refused",
                    reason=f"wordlist not found: {wordlist_path}",
                )

        # Cap threads to a sane upper bound — the LLM might propose 200.
        threads = max(1, min(int(threads or 10), 50))

        argv = [
            self.binary, "dir",
            "-u", base_url,
            "-w", wordlist_path,
            "-t", str(threads),
            "-q",
            "--no-progress",
            "--format", "json",
        ]
        if extensions:
            argv.extend(["-x", extensions])

        dangerous = block_dangerous_flags(" ".join(argv))
        if dangerous:
            return WrapperResult(
                ok=False, status="refused",
                reason=f"dangerous flag detected: {dangerous}",
            )

        return self._run(argv, timeout_sec or self.default_timeout)

    def _run(self, argv: list[str], timeout_sec: int) -> WrapperResult:
        audit_command = shlex.join(argv)
        logger.info("[security_tools.gobuster] exec: %s", audit_command)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv, capture_output=True, timeout=timeout_sec, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            return WrapperResult(
                ok=False, status="timeout",
                raw_stdout=exc.stdout or b"",
                raw_stderr=(exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else "",
                command=audit_command, exec_ms=elapsed,
                reason=f"gobuster exceeded {timeout_sec}s timeout",
            )
        except FileNotFoundError:
            elapsed = int((time.monotonic() - t0) * 1000)
            return WrapperResult(
                ok=False, status="failure",
                command=audit_command, exec_ms=elapsed,
                reason=f"gobuster binary not found at {self.binary!r}",
            )
        elapsed = int((time.monotonic() - t0) * 1000)
        return WrapperResult(
            ok=(proc.returncode == 0),
            status="success" if proc.returncode == 0 else "failure",
            raw_stdout=proc.stdout or b"",
            raw_stderr=(proc.stderr or b"").decode("utf-8", errors="replace"),
            command=audit_command, exec_ms=elapsed,
            reason="" if proc.returncode == 0 else f"gobuster exit code {proc.returncode}",
        )
