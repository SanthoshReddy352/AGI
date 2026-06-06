"""P3.17 — Path security checks."""
import os
import pytest
from core.safety.path_security import PathSecurity


@pytest.fixture()
def sec(tmp_path):
    return PathSecurity(roots=[str(tmp_path)])


def test_valid_path_in_root(sec, tmp_path):
    ok, reason = sec.validate(str(tmp_path / "file.txt"))
    assert ok, reason


def test_traversal_blocked(sec, tmp_path):
    ok, reason = sec.validate(str(tmp_path / ".." / "etc" / "passwd"))
    assert not ok
    assert "traversal" in reason.lower() or "outside" in reason.lower()


def test_null_byte_blocked(sec):
    ok, reason = sec.validate("/tmp/file\x00.txt")
    assert not ok
    assert "null" in reason.lower()


def test_outside_root_blocked(sec):
    ok, reason = sec.validate("/etc/passwd")
    assert not ok
    assert "outside" in reason.lower()


def test_empty_path_blocked(sec):
    ok, reason = sec.validate("")
    assert not ok


def test_safe_join_valid(sec, tmp_path):
    result = sec.safe_join(str(tmp_path), "subdir", "file.txt")
    assert result is not None
    assert result.endswith("file.txt")


def test_safe_join_traversal_blocked(sec, tmp_path):
    result = sec.safe_join(str(tmp_path), "..", "etc", "passwd")
    assert result is None


def test_module_level_check_path():
    from core.safety.path_security import check_path
    ok, _ = check_path(os.path.expanduser("~/notes.txt"))
    assert ok  # home dir is a safe root by default
