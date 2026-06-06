---
name: code_execution
description: "Sandboxed Python and Bash code execution for calculations, scripts, and data tasks."
plugin_module: modules/code_execution
requires:
  code_execution.enabled: true
capabilities:
  - name: evaluate_code
    description: "Run Python or Bash code and return the output. Good for math, data, and automation."
    aliases:
      - "compute"
      - "calculate"
      - "run this code"
      - "evaluate"
      - "run python"
      - "run bash"
      - "what is 47 times 3.14"
---

# Code Execution Module

Runs Python and Bash snippets in an isolated sandbox with a 5-second timeout.

## Setup

Add to `config.yaml`:
```yaml
code_execution:
  enabled: true
  timeout_sec: 5    # optional, default 5
```

## Examples

```
Friday, compute 47 times 3.14
Friday, calculate the square root of 144
Friday, run python: import datetime; print(datetime.date.today())
Friday, run bash: ls ~/Desktop | wc -l
Friday, what is 2 to the power of 32?
```

## Safety

- Runs in `/tmp/friday-sandbox/<random-id>/` — isolated temp directory
- Stripped environment: no cloud credentials, minimal PATH
- 5-second wall-clock timeout (configurable)
- Output capped at 2000 characters
- Python: `python -I` flag disables user site-packages and PYTHONPATH
- Bash: restricted PATH (`/usr/bin:/bin`), `set -euo pipefail`

## Limitations

- No network access from within the sandbox (no outbound connections)
- No file access outside the sandbox directory
- Not suitable for long-running processes
