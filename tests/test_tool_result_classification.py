"""P3.22 — tool result classification."""
import pytest
from core.tool_result import classify, is_failure


@pytest.mark.parametrize("result,expected", [
    ("File opened successfully.", "ok"),
    ("Here is the weather forecast.", "ok"),
    (None, "soft_fail"),
    ("Error: failed to open file", "soft_fail"),
    ("could not find the target", "soft_fail"),
    ("Connection refused by host", "retryable"),
    ("Request timed out", "retryable"),
    ("Permission denied: /etc/shadow", "fatal"),
    ("Access denied for user", "fatal"),
])
def test_classify(result, expected):
    assert classify("some_tool", result) == expected


def test_is_failure_ok():
    assert not is_failure("ok")


def test_is_failure_soft_fail():
    assert is_failure("soft_fail")


def test_is_failure_retryable():
    assert is_failure("retryable")


def test_is_failure_fatal():
    assert is_failure("fatal")


def test_tool_name_ignored_for_classification():
    # tool_name is accepted but not used in current heuristic
    assert classify("open_file", "Success!") == "ok"
    assert classify("unknown_tool", "Success!") == "ok"
