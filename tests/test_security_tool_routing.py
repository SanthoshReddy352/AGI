"""P1.1 — Network recon phrases and CIDR patterns route to security_tools."""
import re
import pytest

from modules.security_tools.plugin import _PING_SWEEP_PATTERNS, _HOST_SCAN_PATTERNS


def _any_pattern_matches(patterns, text):
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


@pytest.mark.parametrize("phrase", [
    "scan my network",
    "scan the network",
    "network recon",
    "network reconnaissance",
    "recon the network",
    "do a network scan",
    "do a network recon",
    "do a recon",
])
def test_ping_sweep_free_form_phrases(phrase):
    assert _any_pattern_matches(_PING_SWEEP_PATTERNS, phrase), \
        f"Expected phrase to match ping_sweep: {phrase!r}"


@pytest.mark.parametrize("phrase", [
    "do a network recon on 192.168.1.0/24",
    "scan 10.0.0.0/8",
    "nmap 172.16.0.0/16",
])
def test_host_scan_cidr_pattern(phrase):
    assert _any_pattern_matches(_HOST_SCAN_PATTERNS, phrase), \
        f"Expected CIDR phrase to match host_scan: {phrase!r}"
