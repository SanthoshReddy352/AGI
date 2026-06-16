"""Provider catalog + model-listing for the settings UI."""
from __future__ import annotations

from fastapi.testclient import TestClient

from friday.core.memory import Database
from friday.core.providers.base import LLMResponse
from friday.core.providers.catalog import list_models, provider_catalog
from friday.core.tools import ToolRegistry
from friday.server.api import create_app
from friday.service import FridayService
import friday.tests.test_server as ts


def test_catalog_has_all_providers(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    cat = {p["type"]: p for p in provider_catalog()}
    assert {"anthropic", "openai", "google", "opencode", "openai_compat", "lmstudio", "ollama"} <= set(cat)
    assert cat["anthropic"]["key_set"] is True
    assert cat["google"]["key_set"] is False
    assert cat["lmstudio"]["needs_key"] is False


def test_list_models_fallback_when_no_key():
    # No network/key → curated fallback (never empty for known providers).
    assert "claude-opus-4-8" in list_models("anthropic", api_key="")
    assert list_models("openai", api_key="")  # non-empty fallback


def test_provider_endpoints():
    svc = FridayService(
        config={"persona": "friday_core", "conversation": {}, "provider": {"type": "anthropic", "model": "claude-x"}},
        provider=ts.ScriptedProvider([LLMResponse(content="hi")]),
        registry=ToolRegistry(), db=Database(":memory:"))
    c = TestClient(create_app(svc))
    pr = c.get("/api/providers").json()
    assert "providers" in pr and pr["active"]["type"] == "anthropic"
    md = c.get("/api/models?type=anthropic").json()
    assert "models" in md and isinstance(md["models"], list)
