"""P2.3 — STT phonetic-correction YAML loading and normalization."""
import importlib
import os
import sys
import types

import pytest


def _reload_normalize():
    """Reload text_normalize so YAML load re-runs with current config."""
    if "core.text_normalize" in sys.modules:
        del sys.modules["core.text_normalize"]
    import core.text_normalize as m
    return m


def test_known_yaml_entry_nellore(tmp_path, monkeypatch):
    """'nolo-re' from the YAML maps to 'nellore'."""
    norm = _reload_normalize()
    result = norm.normalize_for_routing("What's the weather in nolo-re?")
    assert "nellore" in result.lower()


def test_nolore_variant():
    """'nolore' (no hyphen) also maps to 'nellore'."""
    from core.text_normalize import normalize_for_routing
    assert "nellore" in normalize_for_routing("flight to nolore").lower()


def test_hardcoded_typos_still_work():
    """Hard-coded typos (e.g. 'calender') survive the YAML merge."""
    from core.text_normalize import normalize_for_routing
    assert "calendar" in normalize_for_routing("set a calender reminder").lower()


def test_case_preserved_on_yaml_entry():
    """Leading uppercase is preserved for YAML-loaded entries."""
    from core.text_normalize import normalize_for_routing
    result = normalize_for_routing("Travel to Nolo-re")
    assert "Nellore" in result


def test_missing_yaml_does_not_break(tmp_path, monkeypatch):
    """If the YAML file is missing, normalize_for_routing still works."""
    # Patch os.path.exists to report the YAML as absent
    real_exists = os.path.exists

    def _fake_exists(path):
        if "stt_substitutions.yaml" in str(path):
            return False
        return real_exists(path)

    monkeypatch.setattr(os.path, "exists", _fake_exists)
    norm = _reload_normalize()
    # Hard-coded table should still work
    assert "calendar" in norm.normalize_for_routing("calender event").lower()


def test_yaml_bad_content_does_not_break(tmp_path, monkeypatch):
    """Malformed YAML is caught silently; hard-coded table still works."""
    bad_yaml = tmp_path / "stt_substitutions.yaml"
    bad_yaml.write_text(": : : invalid yaml :::", encoding="utf-8")

    real_exists = os.path.exists
    real_join = os.path.join

    monkeypatch.setattr(os.path, "exists", lambda p: True if "stt_substitutions" in str(p) else real_exists(p))

    import builtins
    real_open = builtins.open

    def _fake_open(path, *a, **kw):
        if "stt_substitutions" in str(path):
            return real_open(str(bad_yaml), *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr(builtins, "open", _fake_open)
    norm = _reload_normalize()
    assert "calendar" in norm.normalize_for_routing("calender event").lower()
