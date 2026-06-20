# Contributing

Thanks for your interest in Namma Agent. This is a cloud-only assistant; the whole
app lives in the [`namma_agent/`](namma_agent/) package.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r namma_agent/requirements.txt
python -m pytest namma_agent/tests/ -q        # should be green before you start
```

See the [README](README.md) for run instructions and provider config.

## Ground rules

- **Tests pass.** Run `python -m pytest namma_agent/tests/ -q` before opening a PR; add
  focused tests for new behavior under `namma_agent/tests/test_<area>.py`. Tests are
  offline/mocked and need no API key.
- **Add tools the v2 way.** Drop a `namma_agent/tools/<name>.py` with a
  `register(registry)` function; parameters are JSON Schema. No intent regexes.
  Make destructive/sensitive actions approval-gated, and degrade gracefully when
  an external binary is missing.
- **Don't hard-code the assistant's name.** It's configurable via
  `assistant.name` / `ASSISTANT_NAME`; resolve it through
  `namma_agent.config.assistant_name()` (backend) or `config.assistant_name` (UI). Only
  `NAMMA_*` env-var names are fixed.
- **Stay cross-platform.** Guard OS-specific code with `platform.system()` /
  `os.name`; pass `encoding="utf-8", errors="replace"` to text subprocesses.
- **Keep secrets out of git.** Configuration goes in `namma_agent/config.yaml`; secrets
  go in `.env` (gitignored).

## Pull requests

Keep PRs focused, describe what changed and why, and note how you tested it. By
contributing you agree your work is licensed under the project's [MIT License](LICENSE).
