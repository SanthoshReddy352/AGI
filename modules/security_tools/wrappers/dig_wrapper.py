"""dig capability wrapper.

DNS enumeration for owned / lab / CTF domains. Wrapper invokes ``dig`` once
per requested record type and concatenates the outputs. The parser then
extracts records into typed entries.

The user provides a domain and an optional comma-separated record_types
string (defaults to ``A,AAAA,MX,NS,TXT``). The wrapper validates the
domain shape and restricts record types to a small allowlist (no AXFR
zone transfers, no ANY queries — these are pull-everything signatures we
don't want the LLM proposing).
"""
from __future__ import annotations

import re
import shlex
import subprocess
import time
from dataclasses import dataclass

from core.logger import logger

from ..safety import block_dangerous_flags


_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)"
    r"[A-Za-z0-9][A-Za-z0-9\-]{0,62}"
    r"(?:\.[A-Za-z0-9][A-Za-z0-9\-]{0,62})*"
    r"\.?$"
)
_ALLOWED_RECORDS = {"A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "PTR", "SRV", "CAA"}


@dataclass
class WrapperResult:
    ok: bool
    status: str
    raw_stdout: bytes = b""
    raw_stderr: str = ""
    command: str = ""
    exec_ms: int = 0
    reason: str = ""


class DigWrapper:
    def __init__(
        self,
        *,
        dig_binary: str = "dig",
        default_timeout_sec: int = 30,
    ):
        self.binary = dig_binary
        self.default_timeout = int(default_timeout_sec)

    def enumerate(
        self,
        domain: str,
        *,
        record_types: str | list[str] = "A,AAAA,MX,NS,TXT",
        timeout_sec: int | None = None,
    ) -> WrapperResult:
        if not domain or not _DOMAIN_RE.match(domain.strip()):
            return WrapperResult(
                ok=False, status="refused",
                reason=f"domain {domain!r} is not a valid DNS name",
            )

        # Normalize the record-type list.
        if isinstance(record_types, str):
            types = [t.strip().upper() for t in record_types.split(",") if t.strip()]
        else:
            types = [str(t).strip().upper() for t in record_types if str(t).strip()]
        types = [t for t in types if t in _ALLOWED_RECORDS]
        if not types:
            return WrapperResult(
                ok=False, status="refused",
                reason="no allowed record types requested (allowed: "
                       + ", ".join(sorted(_ALLOWED_RECORDS)) + ")",
            )

        joined_argv_for_audit: list[str] = []
        combined_stdout = bytearray()
        combined_stderr = ""
        t0 = time.monotonic()
        per_call_timeout = max(2, (timeout_sec or self.default_timeout) // max(1, len(types)))

        for rtype in types:
            argv = [self.binary, "+short", "+time=5", "+tries=1", "-t", rtype, domain.strip()]
            dangerous = block_dangerous_flags(" ".join(argv))
            if dangerous:
                return WrapperResult(
                    ok=False, status="refused",
                    reason=f"dangerous flag detected: {dangerous}",
                )
            joined_argv_for_audit.append(shlex.join(argv))
            logger.info("[security_tools.dig] exec: %s", joined_argv_for_audit[-1])
            try:
                proc = subprocess.run(
                    argv, capture_output=True, timeout=per_call_timeout, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                elapsed = int((time.monotonic() - t0) * 1000)
                return WrapperResult(
                    ok=False, status="timeout",
                    raw_stdout=bytes(combined_stdout),
                    raw_stderr=combined_stderr,
                    command=" ; ".join(joined_argv_for_audit),
                    exec_ms=elapsed,
                    reason=f"dig exceeded {per_call_timeout}s timeout on {rtype}",
                )
            except FileNotFoundError:
                elapsed = int((time.monotonic() - t0) * 1000)
                return WrapperResult(
                    ok=False, status="failure",
                    command=" ; ".join(joined_argv_for_audit), exec_ms=elapsed,
                    reason=f"dig binary not found at {self.binary!r}",
                )
            # Tag each chunk with its record type so the parser can split.
            chunk_header = f"\n;; {rtype} records\n".encode()
            combined_stdout.extend(chunk_header)
            combined_stdout.extend(proc.stdout or b"")
            if proc.stderr:
                combined_stderr += proc.stderr.decode("utf-8", errors="replace")

        elapsed = int((time.monotonic() - t0) * 1000)
        return WrapperResult(
            ok=True, status="success",
            raw_stdout=bytes(combined_stdout),
            raw_stderr=combined_stderr,
            command=" ; ".join(joined_argv_for_audit),
            exec_ms=elapsed,
        )
