---
name: security_tools
description: "Network reconnaissance, host scanning, and security analysis for authorized testing"
plugin_module: modules/security_tools
requires:
  lab_mode: true
capabilities:
  - name: ping_sweep
    description: "Ping sweep a network range or discover hosts on a subnet"
    aliases:
      - "scan my network"
      - "scan the network"
      - "network recon"
      - "network reconnaissance"
      - "discover hosts"
      - "find devices on network"
  - name: host_service_scan
    description: "Scan a host or IP address for open ports and running services"
    aliases:
      - "port scan"
      - "nmap scan"
      - "scan this host"
      - "what ports are open"
      - "check open ports"
  - name: run_custom_nmap
    description: "Run a custom nmap command with specified flags"
    aliases:
      - "custom nmap"
      - "run nmap"
---

# Security Tools

Requires `lab_mode: true` in `config/settings.yaml`.

## Capabilities

### ping_sweep
Discovers live hosts on a subnet using ping sweeps.

**You say:** "Friday, scan my network" or "Friday, do a ping sweep on 192.168.1.0/24"
**Verify:** `[ROUTE] source=intent tool=ping_sweep` in `logs/friday.log`

### host_service_scan
Runs an nmap service scan against a target host or subnet.

**You say:** "Friday, scan 192.168.1.100 for open ports"
**Verify:** FRIDAY returns a port/service table or nmap output.

### run_custom_nmap
Passes raw nmap flags. Use with care — requires explicit authorization.

**You say:** "Friday, run nmap -sV -p 22,80,443 192.168.1.1"
