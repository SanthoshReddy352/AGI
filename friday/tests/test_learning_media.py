"""Wave 3 tests — Learning-Room media tools (diagram / image / simulation)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from friday.core.tools import ToolRegistry
from friday.tools.learning_media import register


@pytest.fixture
def reg(tmp_path, monkeypatch):
    # Redirect media output into a temp dir so tests don't litter data/media.
    import friday.tools.learning_media as lm
    monkeypatch.setattr(lm, "_MEDIA", tmp_path / "media")
    r = ToolRegistry()
    register(r)
    return r


def test_render_simulation_writes_html(reg, tmp_path):
    html = "<!doctype html><html><body><h1>hi</h1><script>1+1</script></body></html>"
    res = reg.execute("render_simulation", {"html": html, "title": "Demo"})
    assert res.ok
    assert "/api/media/sims/" in res.content
    rel = res.data["url"].split("/api/media/")[1]
    assert (tmp_path / "media" / rel).read_text().startswith("<!doctype html>")


def test_render_simulation_rejects_non_html(reg):
    res = reg.execute("render_simulation", {"html": "just text"})
    assert not res.ok and "html" in res.error.lower()


def test_fetch_image_mocked(reg, tmp_path, monkeypatch):
    import io
    import friday.tools.learning_media as lm

    class FakeResp(io.BytesIO):
        def __init__(self, data, ctype="image/png"):
            super().__init__(data)
            self.headers = {"Content-Type": ctype}
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:  # the Openverse search
            import json
            body = json.dumps({"results": [{
                "url": "https://example.test/cat.png", "title": "Cat",
                "creator": "Ada", "license": "cc0"}]}).encode()
            return FakeResp(body, "application/json")
        return FakeResp(b"\x89PNG\r\n\x1a\n fake-bytes", "image/png")  # the image download

    monkeypatch.setattr(lm.urllib.request, "urlopen", fake_urlopen)
    res = reg.execute("fetch_image", {"query": "cat"})
    assert res.ok
    assert "/api/media/images/" in res.content and "Ada" in res.content
    rel = res.data["url"].split("/api/media/")[1]
    assert (tmp_path / "media" / rel).exists()


@pytest.mark.skipif(not (shutil.which("mmdc") or (Path.home() / ".npm-global/bin/mmdc").exists()),
                    reason="mermaid-cli (mmdc) not installed")
def test_render_diagram_real(reg, tmp_path):
    res = reg.execute("render_diagram", {"mermaid": "graph TD; A-->B; B-->C", "title": "Flow"})
    assert res.ok, res.error
    rel = res.data["url"].split("/api/media/")[1]
    out = tmp_path / "media" / rel
    assert out.exists() and out.stat().st_size > 0


def test_render_diagram_requires_code(reg):
    res = reg.execute("render_diagram", {"mermaid": ""})
    assert not res.ok
