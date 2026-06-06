# Security Policy

FRIDAY runs local code, can control your desktop (brightness, locking, app
launch, clipboard, screenshots), executes sandboxed code snippets, and ships
**scoped** network-security tooling. We take its security posture seriously.

## Supported versions

FRIDAY is pre-1.0. Security fixes land on `main` and the latest tagged release.

| Version | Supported |
|---|---|
| `main` / latest release | ✅ |
| older tags | ❌ |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Instead, report privately via one of:

- **GitHub Security Advisories** — [Report a vulnerability](../../security/advisories/new) (preferred).
- **Email** — gsreddy1182006@gmail.com with subject `FRIDAY SECURITY`.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (or a proof of concept).
- Affected version/commit and OS.
- Any suggested remediation.

### What to expect

- **Acknowledgement** within 5 business days.
- An assessment and, if accepted, a fix timeline. We aim to ship fixes for
  high-severity issues within 30 days.
- Credit in the release notes (unless you prefer to remain anonymous).

## Scope & safe-harbor

The following are **in scope**: remote code execution, sandbox escapes from the
code-execution module, path-traversal in file/document handling, privilege or
permission-consent bypass (e.g. online actions running without consent), and
leakage of local data to the network.

The bundled **security tooling** (`modules/security_tools/`, e.g. nmap wrappers)
is gated behind `security.lab_mode` and `security.authorized_scopes` in
`config.yaml`. It is intended **only** for authorized testing of networks you own
or have permission to test. Misuse against third-party systems is your
responsibility, not a vulnerability in FRIDAY.

We support good-faith security research. If you make a genuine effort to avoid
privacy violations, data destruction, and service disruption while testing, we
will not pursue or support legal action against you.

## Hardening notes for operators

- FRIDAY is **local-first**; online skills are opt-in via
  `conversation.online_permission_mode: ask_first`. Review this before
  loosening it.
- Secrets belong in `.env` (git-ignored), never in `config.yaml`.
- The security audit log is written to `logs/security_audit.log`.
