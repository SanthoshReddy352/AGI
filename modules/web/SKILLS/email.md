---
name: email
description: "Compose and send email via SMTP / IMAP — gated behind explicit config."
source: "hermes-agent skills/email (MIT — see docs/third_party_credits.md)"
adapted_for: "FRIDAY local voice assistant"
requires:
  - llm_chat
  - approval
---

# email

## When to use

The user wants to compose an outgoing email, reply to one, or check what's in the inbox. Triggers: "send an email to X about Y", "reply to my last email from Z", "any new email from my boss".

This skill is **default-disabled**. It only operates when `config/email.yaml` exists with valid SMTP/IMAP credentials. If config is missing, refuse politely and tell the user how to set it up.

## How to use

### Compose + send
1. **Gather slots**: recipient, subject, body. Use `clarify` (P3.11) for anything missing.
2. **Draft with `llm_chat`** in the user's voice (their `comm_style` from `user_profile` namespace controls tone).
3. **Show the draft** and request approval via `core.approval.request_approval()` — confirm phrase "send it". Anything else cancels.
4. **Send via SMTP** using stdlib `smtplib`. Log the message-id to `audit_events` as `EMAIL_SENT`.

### Read inbox
1. Connect via IMAP using stdlib `imaplib`.
2. Filter by sender / subject / unread per the user's query.
3. For each match, return: from, date, subject, one-line summary (`llm_chat`).

## Configuration

Create `config/email.yaml`:
```yaml
smtp:
  host: smtp.example.com
  port: 587
  username: you@example.com
  password_env: SMTP_PASSWORD   # never inline the password
imap:
  host: imap.example.com
  port: 993
  username: you@example.com
  password_env: IMAP_PASSWORD
defaults:
  from_name: "Your Name"
```

## Examples

- "Friday, send an email to alex@example.com about the meeting tomorrow — say I'll be 10 minutes late."
- "Friday, any new email from my landlord?"
- "Friday, reply to the last one from finance and say thanks."

## Common failures and recovery

- **SMTP auth failure** → tell the user "credentials rejected; check `$SMTP_PASSWORD` and the username in `config/email.yaml`". Do not retry blindly.
- **User cancels at the approval step** → reply "OK, didn't send" and drop the draft.
- **No `config/email.yaml`** → "Email isn't configured. See `docs/setup_linux.md` § Email to set it up — I won't send anything until you do."
