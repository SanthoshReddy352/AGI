"""code_execution plugin package.

The PluginManager imports `modules.<pkg>` and calls its `setup(app)`. This
file was previously empty, so the CodeExecutionPlugin never loaded regardless
of `code_execution.enabled` — the capability was dead. `setup` now gates on the
config flag: it loads the plugin (registering `evaluate_code`) only when
`code_execution.enabled: true`, so a disabled config means no capability at all.
"""
from .plugin import CodeExecutionPlugin


def setup(app):
    cfg = getattr(app, "config", None)
    enabled = False
    if cfg and hasattr(cfg, "get"):
        enabled = str(cfg.get("code_execution.enabled", "false")).lower() == "true"
    if not enabled:
        return None
    return CodeExecutionPlugin(app)
