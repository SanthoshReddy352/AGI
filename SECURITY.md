# Security Policy

## Reporting a vulnerability

If you find a security issue, please report it privately rather than opening a
public issue. Use GitHub's **"Report a vulnerability"** (Security → Advisories) on
the repository, and include:

- a description of the issue and its impact,
- steps to reproduce (a minimal proof of concept if possible),
- affected version / commit.

We'll acknowledge the report and work with you on a fix and disclosure timeline.

## Scope & operational notes

Namma Agent is an assistant that can run shell commands, control a browser, send
messages, and read/write files on the host. Run it as a normal (non-root) user and
treat it with the same caution as any tool with system access.

- **Secrets** live in `.env` at the project root (gitignored) — never commit API
  keys, Telegram tokens, or webhooks.
- **Approval gating** protects destructive and sensitive tools by default. Setting
  `conversation.auto_approve: true` removes that safety net — only do so in an
  environment you control.
- **Security tooling** (`port_scan`, `dir_enum`, etc.) is **disabled** unless you
  explicitly set `security.lab_mode: true` and list `authorized_scopes`. Only scan
  systems you own or are authorized to test.
- **Messaging bridges** (Telegram inbound, etc.) are off until credentials are
  configured; anyone who can message the bot can drive the assistant — restrict it
  to your own chat id.
