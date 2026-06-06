"""P3.14 — describe_image capability in vision plugin."""
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from modules.vision.plugin import VisionPlugin
from modules.vision.prompts import DESCRIBE_IMAGE


def test_describe_image_prompt_exists():
    assert isinstance(DESCRIBE_IMAGE, str)
    assert len(DESCRIBE_IMAGE) > 10


def _make_plugin():
    app = MagicMock()
    app.register_capability = MagicMock()
    app.config = MagicMock()
    app.config.get = MagicMock(return_value=None)
    with patch("modules.vision.service.VisionService.__init__", return_value=None), \
         patch("modules.vision.plugin.VisionPlugin.on_load", return_value=None):
        plugin = VisionPlugin.__new__(VisionPlugin)
        plugin.app = app
        plugin._service = MagicMock()
    return plugin


def test_describe_image_registered():
    app = MagicMock()
    # _get_cfg() calls config.get("vision") — return a minimal enabled config
    app.config.get = lambda key, default=None: (
        {"enabled": True, "features": {}} if key == "vision" else default
    )
    with patch("modules.vision.service.VisionService.__init__", return_value=None), \
         patch("modules.vision.plugin.VisionPlugin._start_error_monitor", return_value=None):
        try:
            plugin = VisionPlugin(app)
        except Exception:
            pass
    # FridayPlugin shim forwards register_capability to app.router.register_tool
    calls = app.router.register_tool.call_args_list
    cap_names = [c.args[0]["name"] for c in calls]
    assert "describe_image" in cap_names


def test_handle_describe_image_no_path_returns_prompt():
    plugin = _make_plugin()
    plugin._handle_describe_image = VisionPlugin._handle_describe_image.__get__(
        plugin, VisionPlugin
    )
    plugin._load_image = VisionPlugin._load_image.__get__(plugin, VisionPlugin)
    result = plugin._handle_describe_image("describe image", {})
    assert "provide" in result.lower() or "path" in result.lower() or "url" in result.lower()


def test_handle_describe_image_nonexistent_path_returns_error():
    plugin = _make_plugin()
    plugin._handle_describe_image = VisionPlugin._handle_describe_image.__get__(
        plugin, VisionPlugin
    )
    plugin._load_image = VisionPlugin._load_image.__get__(plugin, VisionPlugin)
    plugin._ack = MagicMock()
    result = plugin._handle_describe_image("", {"path_or_url": "/nonexistent/path.png"})
    assert "couldn't" in result.lower() or "load" in result.lower() or "provide" in result.lower()


def test_handle_describe_image_with_real_file():
    plugin = _make_plugin()
    plugin._handle_describe_image = VisionPlugin._handle_describe_image.__get__(
        plugin, VisionPlugin
    )
    plugin._load_image = VisionPlugin._load_image.__get__(plugin, VisionPlugin)
    plugin._ack = MagicMock()
    plugin._ok = lambda name, text: text
    plugin._err = lambda name, exc: f"Error: {exc}"
    plugin._service.infer = MagicMock(return_value="A white image with no content.")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
        f.flush()
        result = plugin._handle_describe_image("", {"path_or_url": f.name})
    os.unlink(f.name)
    assert "image" in result.lower() or "white" in result.lower() or "content" in result.lower()


def test_load_image_expands_home():
    plugin = _make_plugin()
    plugin._load_image = VisionPlugin._load_image.__get__(plugin, VisionPlugin)
    result = plugin._load_image("~/nonexistent_friday_test_file.png")
    assert result is None  # doesn't exist, returns None
