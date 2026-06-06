---
name: red-teaming
description: "Defensive / authorised-pentest patterns. Filtered subset of upstream — no offensive material."
source: "hermes-agent skills/red-teaming (MIT — see docs/third_party_credits.md). Offensive material removed; only defensive patterns ported."
adapted_for: "FRIDAY local voice assistant"
requires:
  - ping_sweep
  - host_service_scan
  - run_custom_nmap
  - lab_mode
---

# red teaming (defensive subset)

## When to use

The user is doing **authorised** security work on **their own** network or a target where they have explicit written permission (CTF, bug-bounty in scope, in-house engagement). Triggers: "recon my network", "what's exposed on this server", "do an authorised vuln check on 10.0.0.x".

**Requires `lab_mode: true` in `config/settings.yaml`.** Without it every capability in this skill refuses with a clear message — no override path. Outside lab mode FRIDAY also rejects targets outside RFC1918 / link-local space, so accidental Internet scans are blocked at the source.

## What we cover

The ported subset is the **map → enumerate → verify → report** loop against assets the user owns. We do not ship payloads, exploit kits, evasion / persistence techniques, or anything aimed at humans (phishing / social-engineering).

### 1. Map the surface
```
Friday, ping sweep 192.168.1.0/24
Friday, list devices on this subnet
```
→ `ping_sweep`. Output: live hosts + MAC where ARP cache resolves.

### 2. Enumerate services
```
Friday, scan 192.168.1.50 for open ports
Friday, what's listening on this host
```
→ `host_service_scan`. Default: `nmap -sV -T3` against the top 1000 ports.

### 3. Verify
```
Friday, run nmap -sV --script vulners 192.168.1.50
```
→ `run_custom_nmap`. Vuln-script results are surfaced verbatim — FRIDAY won't summarise CVE severity (let the user read the actual NVD entry).

### 4. Report
1. Pipe the latest scan output into `save_file` → `~/Documents/FRIDAY/recon/<target>-<YYYYMMDD>.md`.
2. Append a "Findings" section with one line per open port (port / service / version / known-CVE if vulners flagged it).
3. Read the file path back to the user.

## What is explicitly out of scope

- Anything that runs **against** a system the user hasn't proven they own / are authorised on. No "scan google.com" — that's blocked by URL safety (P3.17) outside lab mode anyway.
- Payload generation, exploit code, shellcode, weaponisation aids.
- Evasion of IDS / WAF / EDR.
- Social-engineering or phishing pretexts.
- Anything from the upstream `red-teaming/godmode/` directory that wasn't a defensive / measurement pattern.

If the user asks for any of the above, refuse and point them at appropriate dedicated tooling (Metasploit / Burp / etc.) with an authorised engagement.

## Common failures and recovery

- **`lab_mode: false`** → refuse with "Recon tools are disabled. Set `lab_mode: true` in `config/settings.yaml` if you're doing authorised testing."
- **`nmap` not installed** → "Install with `sudo apt install nmap`."
- **Target outside RFC1918** → refuse outside `lab_mode`; even inside `lab_mode`, ask `clarify`: "Confirm you're authorised on `<target>` — yes / no."
