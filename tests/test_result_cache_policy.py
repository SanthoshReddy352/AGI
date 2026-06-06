"""ResultCache TTL policy (revised 2026-05-25): recompute everything except
heavy/background read tools, which cache for 15 min."""
from __future__ import annotations

from dataclasses import dataclass

from core.result_cache import ResultCache, _ttl_for, _HEAVY_TTL


@dataclass
class Desc:
    side_effect_level: str = "read"
    latency_class: str = "interactive"
    connectivity: str = "local"


def test_background_read_is_cached():
    assert _ttl_for(Desc(latency_class="background")) == _HEAVY_TTL


def test_interactive_read_not_cached():
    assert _ttl_for(Desc(latency_class="interactive")) == 0


def test_slow_online_read_not_cached():
    # weather/news/email are online 'slow' reads — must recompute now.
    assert _ttl_for(Desc(latency_class="slow", connectivity="online")) == 0


def test_background_write_not_cached():
    assert _ttl_for(Desc(latency_class="background", side_effect_level="write")) == 0


def test_no_descriptor_not_cached():
    assert _ttl_for(None) == 0


def test_cache_set_get_roundtrip_for_heavy():
    cache = ResultCache()
    cache.set("research_topic", {"topic": "x"}, "RESULT", descriptor=Desc(latency_class="background"))
    assert cache.get("research_topic", {"topic": "x"}) == "RESULT"


def test_cache_skips_interactive():
    cache = ResultCache()
    cache.set("weather", {"city": "x"}, "RESULT", descriptor=Desc(latency_class="slow", connectivity="online"))
    assert cache.get("weather", {"city": "x"}) is None
