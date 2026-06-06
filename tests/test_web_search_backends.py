"""P3.10 — Web module: search, extract, crawl."""
import html.parser
import pytest
from unittest.mock import MagicMock, patch

from modules.web.plugin import (
    WebPlugin, _html_to_text, _extract_url, _ddg_search, _fetch_url,
)


# ── HTML extractor ────────────────────────────────────────────────────────────

def test_html_to_text_extracts_body():
    raw = "<html><body><p>Hello world</p></body></html>"
    text, links = _html_to_text(raw)
    assert "Hello world" in text


def test_html_to_text_strips_script():
    raw = "<html><body><script>var x=1;</script><p>Real content</p></body></html>"
    text, _ = _html_to_text(raw)
    assert "var x" not in text
    assert "Real content" in text


def test_html_to_text_collects_links():
    raw = '<html><body><a href="https://example.com">link</a></body></html>'
    _, links = _html_to_text(raw)
    assert "https://example.com" in links


def test_extract_url_from_text():
    url = _extract_url("please fetch https://example.com/page for me")
    assert url == "https://example.com/page"


def test_extract_url_strips_trailing_punctuation():
    url = _extract_url("see https://example.com.")
    assert url == "https://example.com"


def test_extract_url_none_if_no_url():
    assert _extract_url("no url here") is None


# ── Plugin capability dispatch ────────────────────────────────────────────────

def _make_plugin():
    app = MagicMock()
    app.register_capability = MagicMock()
    return WebPlugin.__new__(WebPlugin), app


def test_web_search_no_query_returns_prompt():
    plugin = MagicMock(spec=WebPlugin)
    plugin._handle_search = WebPlugin._handle_search.__get__(plugin, WebPlugin)
    with patch("modules.web.plugin._ddg_search", return_value=[]) as mock_ddg:
        result = plugin._handle_search("", {"query": ""})
    assert "search" in result.lower() or "what" in result.lower()


def test_web_search_formats_results():
    plugin = MagicMock(spec=WebPlugin)
    plugin._handle_search = WebPlugin._handle_search.__get__(plugin, WebPlugin)
    fake_results = [
        {"title": "Python docs", "url": "https://docs.python.org", "snippet": "Official docs."},
    ]
    with patch("modules.web.plugin._ddg_search", return_value=fake_results):
        result = plugin._handle_search("python docs", {"query": "python docs"})
    assert "Python docs" in result
    assert "docs.python.org" in result


def test_web_extract_blocked_by_safety():
    plugin = MagicMock(spec=WebPlugin)
    plugin._handle_extract = WebPlugin._handle_extract.__get__(plugin, WebPlugin)
    with patch("modules.web.plugin._check_url_safety", return_value=(False, "private IP")):
        result = plugin._handle_extract("fetch http://192.168.1.1", {"url": "http://192.168.1.1"})
    assert "can't" in result.lower() or "private" in result.lower()


def test_web_extract_fetches_and_returns_text():
    plugin = MagicMock(spec=WebPlugin)
    plugin._handle_extract = WebPlugin._handle_extract.__get__(plugin, WebPlugin)
    raw_html = "<html><body><p>Test page content</p></body></html>"
    with patch("modules.web.plugin._check_url_safety", return_value=(True, "")), \
         patch("modules.web.plugin._fetch_url", return_value=raw_html):
        result = plugin._handle_extract("fetch https://example.com", {"url": "https://example.com"})
    assert "Test page content" in result


def test_web_crawl_no_url_returns_prompt():
    plugin = MagicMock(spec=WebPlugin)
    plugin._handle_crawl = WebPlugin._handle_crawl.__get__(plugin, WebPlugin)
    result = plugin._handle_crawl("crawl", {"url": "", "depth": "1"})
    assert "url" in result.lower() or "provide" in result.lower()


def test_web_crawl_blocked_by_safety():
    plugin = MagicMock(spec=WebPlugin)
    plugin._handle_crawl = WebPlugin._handle_crawl.__get__(plugin, WebPlugin)
    with patch("modules.web.plugin._check_url_safety", return_value=(False, "blocked")):
        result = plugin._handle_crawl("", {"url": "http://192.168.1.1", "depth": "1"})
    assert "can't" in result.lower() or "crawl" in result.lower()
