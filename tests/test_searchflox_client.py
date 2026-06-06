"""SearchFlox client — normalisation + graceful failure (falls back to None)."""
from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

from modules.web import searchflox_client as sf


def _fake_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _Resp(body)


def test_normalise_extracts_text_and_sources():
    res = sf._normalise("q", {
        "text": "  the answer  ",
        "sources": [
            {"title": "A", "url": "https://a.com"},
            {"link": "https://b.com"},          # 'link' alias, no title
            {"title": "no url"},                  # dropped — no url
        ],
    })
    assert res.text == "the answer"
    assert [s["url"] for s in res.sources] == ["https://a.com", "https://b.com"]


def test_normalise_empty_returns_none():
    assert sf._normalise("q", {"text": "", "sources": []}) is None
    assert sf._normalise("q", "not a dict") is None


def test_search_blank_query_returns_none():
    assert sf.search("   ") is None


def test_search_parses_live_shape():
    payload = {"text": "hi", "query": "q", "sources": [{"title": "T", "url": "https://x.com"}]}
    with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
        res = sf.search("q")
    assert res is not None and res.text == "hi"
    assert res.sources[0]["url"] == "https://x.com"


def test_search_http_error_returns_none():
    err = urllib.error.HTTPError("u", 500, "boom", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        assert sf.search("q") is None


def test_search_429_retries_then_gives_up():
    err = urllib.error.HTTPError("u", 429, "slow down", {}, None)
    with patch("urllib.request.urlopen", side_effect=err) as m, \
         patch("time.sleep"):
        assert sf.search("q", retries=1) is None
    assert m.call_count == 2  # initial + one retry


def test_search_network_error_returns_none():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        assert sf.search("q") is None
