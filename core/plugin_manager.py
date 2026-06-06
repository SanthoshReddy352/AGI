import os
import importlib
import inspect
from core.logger import logger

class PluginManager:
    def __init__(self, app):
        self.app = app
        self.plugins = []
        self.modules_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'modules')

    def load_plugins(self):
        """
        Dynamically find and load all plugins in the modules/ directory.
        A plugin is a class that inherits from FridayPlugin.
        """
        if not os.path.exists(self.modules_dir):
            logger.warning(f"Modules directory {self.modules_dir} not found.")
            return

        for item in sorted(os.listdir(self.modules_dir)):
            if item.startswith('__') or not os.path.isdir(os.path.join(self.modules_dir, item)):
                continue
                
            # Attempt to load __init__.py of each package inside modules/
            module_name = f"modules.{item}"
            try:
                module = importlib.import_module(module_name)
                # Find the setup function
                if hasattr(module, 'setup'):
                    plugin_instance = module.setup(self.app)
                    if plugin_instance:
                        self.plugins.append(plugin_instance)
                        logger.info(f"Successfully loaded plugin: {item}")
            except Exception as e:
                logger.error(f"Failed to load plugin {item}: {e}")

class FridayPlugin:
    """
    Base class for all FRIDAY plugins.
    """
    def __init__(self, app):
        self.app = app
        self.name = "BasePlugin"
        # Track 4.1b: ensure `app.register_capability` exists no matter
        # what the app type is (production FridayApp, _FakeApp, MagicMock,
        # SimpleNamespace). Plugin code can then call
        # `self.app.register_capability(spec, handler, metadata=...)`
        # uniformly without needing to know whether the host wired the
        # new API. The shim forwards to `app.router.register_tool` which
        # every host MUST provide (test fakes include it). Idempotent —
        # production `FridayApp` already has its own method that does
        # the same thing, and `_FakeApp` may define its own forwarder;
        # we only inject when the attribute is missing.
        _ensure_register_capability_shim(app)

    def on_load(self):
        """Called when the plugin is loaded."""
        pass


def _ensure_register_capability_shim(app) -> None:
    """If `app` doesn't already expose `register_capability(spec, handler,
    metadata=None)`, attach a shim that forwards to
    `app.router.register_tool(spec, handler, capability_meta=metadata)`.

    Idempotent and safe: production `FridayApp.register_capability` is
    already defined, so the shim never overrides it. The shim is for
    `_FakeApp` / `SimpleNamespace` / `MagicMock` test apps that mock
    the legacy registration entry but not the new one.
    """
    try:
        existing = getattr(app, "register_capability", None)
    except Exception:
        existing = None
    # MagicMock auto-attributes return another MagicMock — callable but
    # useless. Detect those via the `MagicMock` class name (string check
    # avoids importing unittest.mock just for this) so the shim still
    # installs a real forwarder on MagicMock-backed apps.
    cls_name = type(existing).__name__ if existing is not None else ""
    is_mock_autoattr = cls_name in {"MagicMock", "Mock", "NonCallableMagicMock"}
    if callable(existing) and not is_mock_autoattr:
        return
    router = getattr(app, "router", None)
    if router is None or not hasattr(router, "register_tool"):
        return

    def _forward(spec, handler, metadata=None):
        return router.register_tool(spec, handler, capability_meta=metadata)

    try:
        app.register_capability = _forward
    except Exception:
        # Some app proxies are read-only (frozen dataclasses, slots).
        # If we can't attach, the plugin can still call router.register_tool
        # directly or pass the new metadata kwarg through.
        pass
