"""P2.5 — config/personas/default.yaml drives the persona identity."""
import pytest

from core.persona_manager import (
    PersonaManager,
    _load_persona_yaml,
    render_identity_prompt,
)


# ----------------------------------------------------------------------
# render_identity_prompt
# ----------------------------------------------------------------------

def test_render_includes_identity_and_tone():
    out = render_identity_prompt({
        "identity": "You are FRIDAY.",
        "tone": "warm, calm",
    })
    assert "You are FRIDAY." in out
    assert "Tone: warm, calm." in out


def test_render_renders_dos_and_donts_as_bullets():
    out = render_identity_prompt({
        "identity": "You are FRIDAY.",
        "dos": ["Speak in first person.", "Be concise."],
        "donts": ["Don't use markdown headers."],
    })
    assert "Do:" in out and "Don't:" in out
    assert "- Speak in first person." in out
    assert "- Don't use markdown headers." in out


def test_render_empty_dict_returns_empty_string():
    assert render_identity_prompt({}) == ""


def test_render_accepts_string_dos_too():
    out = render_identity_prompt({"identity": "X", "dos": "Always reply."})
    assert "Do: Always reply." in out


def test_render_falls_back_to_system_identity_key():
    out = render_identity_prompt({"system_identity": "Legacy identity here."})
    assert "Legacy identity here." in out


# ----------------------------------------------------------------------
# YAML loader
# ----------------------------------------------------------------------

def test_load_yaml_missing_file_returns_empty(tmp_path):
    assert _load_persona_yaml(str(tmp_path / "nope.yaml")) == {}


def test_load_yaml_parses_real_file(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "persona_id: friday_core\n"
        "name: FRIDAY\n"
        "identity: You are FRIDAY.\n"
        "tone: warm, calm\n"
        "dos:\n"
        "  - Speak in first person.\n"
        "donts:\n"
        "  - Don't use headers.\n"
    )
    data = _load_persona_yaml(str(p))
    assert data["name"] == "FRIDAY"
    assert data["dos"] == ["Speak in first person."]


# ----------------------------------------------------------------------
# Shipped default YAML
# ----------------------------------------------------------------------

def test_shipped_default_yaml_loads():
    data = PersonaManager.get_yaml_persona()
    # config/personas/default.yaml ships with the repo.
    assert data, "expected config/personas/default.yaml to load"
    assert data.get("persona_id") == "friday_core"
    assert data.get("name") == "FRIDAY"


def test_shipped_default_identity_prompt_includes_dos_and_donts():
    prompt = PersonaManager.identity_prompt()
    assert prompt
    assert "Do:" in prompt
    assert "Don't:" in prompt
    assert "markdown" in prompt.lower()


# ----------------------------------------------------------------------
# friday_prompt() wiring
# ----------------------------------------------------------------------

def test_friday_prompt_uses_yaml_identity():
    from core.prompt_builder import friday_prompt
    pb = friday_prompt()
    text = pb.build()
    assert "ASSISTANT_IDENTITY" in text
    # YAML identity should be present (overrides the hardcoded fallback).
    assert "Don't:" in text or "Tone:" in text