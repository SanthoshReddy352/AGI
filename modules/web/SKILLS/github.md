---
name: github
description: "Read and write GitHub issues, PRs, and comments via the gh CLI."
source: "hermes-agent skills/github (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - evaluate_code
  - llm_chat
  - approval
---

# github

## When to use

The user wants to interact with GitHub: list issues / PRs, read a specific one, post a comment, open a new issue, or merge / approve a PR. Triggers: "any new PRs on the friday repo", "what's the latest issue in foo/bar", "open an issue titled X".

Requires `gh` (GitHub CLI) installed and authenticated (`gh auth status`). If not, refuse and link to setup docs.

## How to use

All actions go through `evaluate_code(language='bash')` invoking `gh`. Read-only actions run unattended; write actions go through `core.approval.request_approval()` first.

### Read patterns
```bash
gh pr list --repo <owner/repo> --state open --json number,title,author,createdAt --limit 10
gh issue view <number> --repo <owner/repo> --json title,body,comments
gh pr view <number> --repo <owner/repo> --json title,body,reviews,checksUrl
```

### Write patterns (each gated by approval)
```bash
gh issue create --repo <owner/repo> --title "<title>" --body "<body>"
gh pr comment <number> --repo <owner/repo> --body "<body>"
gh pr review <number> --repo <owner/repo> --approve --body "LGTM"
gh pr merge <number> --repo <owner/repo> --squash --delete-branch
```

After each write, log to `audit_events` with the gh URL of the result.

## Repository resolution

When the user says "the friday repo" or omits the repo, default to the `git remote get-url origin` of the current working directory. Confirm with `clarify` when ambiguous.

## Examples

- "Friday, list the open PRs on this repo."
- "Friday, summarise issue 142 on anthropics/claude-code."
- "Friday, open an issue titled 'STT mishears Nellore' and paste the last error from the log."
- "Friday, approve PR 87 and merge with squash." (gated by approval)

## Common failures and recovery

- **`gh` not installed or unauthenticated** → "GitHub CLI isn't ready — run `gh auth login` and try again."
- **Repo argument missing and `origin` doesn't point at GitHub** → ask the user which repo via `clarify`.
- **Write action denied at approval step** → reply "skipped" and emit no further state changes.
- **Rate limited (HTTP 403)** → surface the reset time from the response header; don't retry until then.
