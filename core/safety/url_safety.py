"""URL safety — blocks private IPs and policy-blocked domains (P3.17)."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from core.safety.website_policy import get_policy

# RFC-1918 + link-local + loopback private ranges.
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$|^\[?[0-9a-fA-F:]+\]?$")


class UrlSafety:
    def is_safe(self, url: str) -> tuple[bool, str]:
        """Return (ok, reason). ok=True means the URL is safe to fetch."""
        if not url:
            return False, "empty URL"
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "malformed URL"
        host = parsed.hostname or ""
        if not host:
            return False, "no host in URL"
        if self._is_private_ip(host):
            return False, f"private/loopback IP blocked: {host}"
        policy = get_policy()
        if policy.is_blocked_domain(host):
            return False, f"domain blocked by policy: {host}"
        return True, ""

    def _is_private_ip(self, host: str) -> bool:
        if not _IP_RE.match(host):
            return False
        try:
            addr = ipaddress.ip_address(host.strip("[]"))
            return any(addr in net for net in _PRIVATE_NETS)
        except ValueError:
            return False


_default = UrlSafety()


def is_safe_url(url: str) -> tuple[bool, str]:
    return _default.is_safe(url)
