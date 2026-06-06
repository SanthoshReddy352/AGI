"""P3.17 — URL safety checks."""
import pytest
from core.safety.url_safety import is_safe_url


@pytest.mark.parametrize("url,expected_ok", [
    ("https://en.wikipedia.org/wiki/Python", True),
    ("https://arxiv.org/abs/2305.12345", True),
    ("http://192.168.1.1/admin", False),      # private IP
    ("http://10.0.0.1/", False),              # private IP
    ("http://127.0.0.1:8080/", False),        # loopback
    ("http://localhost/", True),              # hostname, not IP — not blocked by ip check
    ("", False),                              # empty
])
def test_url_safety(url, expected_ok):
    ok, reason = is_safe_url(url)
    assert ok == expected_ok, f"url={url!r}: ok={ok}, reason={reason!r}"


def test_blocked_domain_from_policy(monkeypatch):
    from core.safety import website_policy as wp_mod
    policy = wp_mod.WebsitePolicy.__new__(wp_mod.WebsitePolicy)
    policy.blocked_domains = ["malware.wicar.org"]
    policy.allowed_prefixes = []
    monkeypatch.setattr(wp_mod, "_policy", policy)
    from core.safety import url_safety as us_mod
    ok, reason = us_mod.is_safe_url("https://malware.wicar.org/test")
    assert not ok
    assert "blocked" in reason.lower()


def test_private_ip_v6():
    ok, reason = is_safe_url("http://[::1]/path")
    assert not ok
