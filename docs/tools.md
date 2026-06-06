# FRIDAY Capability, Tool and Workflow Catalog

This document provides a comprehensive directory of all tools, capabilities, standalone functions, and workflows built into **FRIDAY**.

> [!NOTE]
> Each capability in FRIDAY is an in-process, MCP-compatible tool registered dynamically during bootstrap. This catalog is a **point-in-time snapshot** generated from the live capability registry of a running FRIDAY instance, so individual `…#Lxxx` source anchors may drift as files change. The canonical, always-current list of **user-facing** capabilities (with example phrasings) is [`data/tool_catalog.yaml`](../data/tool_catalog.yaml); regenerate this document from a live instance after large capability changes. Every entry below was verified to correspond to a registered capability.

## Table of Contents
1. [System Overview](#system-overview)
2. [Workflows](#workflows-directory)
3. [Tools by Category](#tools-by-category)
   - [Awareness & Vision Modules](#awareness--vision-modules)
   - [Core Voice & System Controls](#core-voice--system-controls)
   - [Cybersecurity Lab Tools](#cybersecurity-lab-tools)
   - [Integrations & Comms](#integrations--comms)
   - [Memory, Identity & Chat](#memory-identity--chat)
   - [Miscellaneous / Core Tools](#miscellaneous--core-tools)
   - [System & Desktop Controls](#system--desktop-controls)
   - [Tasks, Goals & Triggers](#tasks-goals--triggers)
   - [Web & Browser Automation](#web--browser-automation)
   - [Workspace & File Management](#workspace--file-management)

## System Overview
Capabilities are categorized using the following security and performance metadata:
- **Connectivity**: `local` (runs fully on device) or `online` (makes external web requests).
- **Permission Mode**: `always_ok` (executes instantly) or `ask_first` (prompts user for explicit authorization).
- **Side Effect Level**: `read` (read-only action, safe) or `write` (modifies state or files, high caution).
- **Latency Class**: `interactive` (fast, instant response) or `long_running` (async background execution).

---

## Workflows Directory
Workflows are orchestrations of multiple linear or parallel steps, utilizing individual tools/capabilities to achieve complex, goal-oriented tasks. They are defined as YAML templates under [core/workflows/templates](../core/workflows/templates) and executed by the [workflow_orchestrator.py](../core/workflow_orchestrator.py).

### Workflow: `compare_two_scan_results`
**Description:** Compare two previously-stored scan artifacts and produce a structured diff plus a markdown comparison summary.

- **Specification File:** [core/workflows/templates/compare_two_scan_results.yaml](../core/workflows/templates/compare_two_scan_results.yaml)
- **Version:** `0.1.0` | **Tags:** `diff, deterministic, planned`
- **Required Inputs:** `artifact_a, artifact_b`
- **Example Natural Language Trigger Queries:**
  - "Compare these two scan results"
  - "Show differences between scan A and scan B"

**Execution Steps & Capabilities Utilized:**
  - **Step `s1`**: Calls capability [`compare_scan_results`](#compare-scan-results) (Side-Effect: `read`)
  - **Step `s2`**: Calls capability [`security_report_generate`](#security-report-generate) (Side-Effect: `write`)

### Workflow: `dns_enum_owned_domain`
**Description:** Read-only DNS record enumeration for a domain the user owns or is authorized to test. Produces a markdown record inventory.

- **Specification File:** [core/workflows/templates/dns_enum_owned_domain.yaml](../core/workflows/templates/dns_enum_owned_domain.yaml)
- **Version:** `0.1.0` | **Tags:** `dns, lab, authorized, read_only, planned`
- **Required Inputs:** `domain`
- **Example Natural Language Trigger Queries:**
  - "Run DNS enumeration for my domain testlab.local"
  - "Perform DNS record inventory for ctf-target.lab"

**Execution Steps & Capabilities Utilized:**
  - **Step `s1`**: Calls capability [`dns_enum_owned_domain`](#dns-enum-owned-domain) (Side-Effect: `read`)
  - **Step `s2`**: Calls capability [`security_report_generate`](#security-report-generate) (Side-Effect: `write`)

### Workflow: `lab_network_inventory`
**Description:** Read-only inventory of an authorized lab subnet. Discovers live hosts with a ping sweep, then enumerates services on each found host.

- **Specification File:** [core/workflows/templates/lab_network_inventory.yaml](../core/workflows/templates/lab_network_inventory.yaml)
- **Version:** `1.0.0` | **Tags:** `inventory, lab, authorized, read_only`
- **Required Inputs:** `target_subnet`
- **Example Natural Language Trigger Queries:**
  - "Do a basic network inventory of 192.168.56.0/24"
  - "Perform ping sweep and service scan on lab subnet 10.0.2.0/24"

**Execution Steps & Capabilities Utilized:**
  - **Step `s1`**: Calls capability [`ping_sweep`](#ping-sweep) (Side-Effect: `read`)
  - **Step `s2`**: Calls capability [`host_service_scan`](#host-service-scan) (Side-Effect: `read`)

### Workflow: `own_machine_open_services`
**Description:** Scan the local machine (loopback) for open TCP services. Read-only, no authorization needed beyond the local scope.

- **Specification File:** [core/workflows/templates/own_machine_open_services.yaml](../core/workflows/templates/own_machine_open_services.yaml)
- **Version:** `1.0.0` | **Tags:** `local, self_audit, read_only`
- **Required Inputs:** `target_host`
- **Example Natural Language Trigger Queries:**
  - "Scan my own machine for open services"
  - "Audit open TCP ports on localhost"
  - "Run loopback service scan"

**Execution Steps & Capabilities Utilized:**
  - **Step `s1`**: Calls capability [`host_service_scan`](#host-service-scan) (Side-Effect: `read`)

### Workflow: `report_from_scan_artifacts`
**Description:** Convert previously-stored scan artifacts (nmap XML, gobuster JSON, dig output) into a polished markdown security report.

- **Specification File:** [core/workflows/templates/report_from_scan_artifacts.yaml](../core/workflows/templates/report_from_scan_artifacts.yaml)
- **Version:** `0.1.0` | **Tags:** `report, deterministic, planned`
- **Required Inputs:** `artifact_refs`
- **Example Natural Language Trigger Queries:**
  - "Create a security report from gobuster and nmap scans"
  - "Compile a markdown report from the ctf artifacts"

**Execution Steps & Capabilities Utilized:**
  - **Step `s1`**: Calls capability [`parse_scan_artifacts`](#parse-scan-artifacts) (Side-Effect: `read`)
  - **Step `s2`**: Calls capability [`security_report_generate`](#security-report-generate) (Side-Effect: `write`)

### Workflow: `user_onboarding`
**Description:** First-run user-profile onboarding. Five linear questions, then writes every collected answer to the user_profile facts namespace and marks the onboarding completion flag.

- **Specification File:** [core/workflows/templates/user_onboarding.yaml](../core/workflows/templates/user_onboarding.yaml)
- **Version:** `1.0.0` | **Tags:** `first_run, profile`
- **Required Inputs:** `None`
- **Example Natural Language Trigger Queries:**
  - "Run first-time setup"
  - "Start user onboarding"
  - "Introduce yourself and configure my profile"

**Execution Steps & Capabilities Utilized:**
  - **Step `ask_name` (Interactive)**: Prompts user: *"Hello! Before we start — what should I call you?"* and saves response to slot `user_name`
  - **Step `ask_role` (Interactive)**: Prompts user: *"Nice to meet you, {{user_name|default:there}}. What do you do?"* and saves response to slot `user_role`
  - **Step `ask_location` (Interactive)**: Prompts user: *"Where are you based? Helps me with weather, time zone, and news."* and saves response to slot `user_location`
  - **Step `ask_preferences` (Interactive)**: Prompts user: *"Any tools or topics you care about most? Short answer is fine."* and saves response to slot `user_preferences`
  - **Step `ask_comm_style` (Interactive)**: Prompts user: *"How do you like me to talk to you — concise, detailed, or somewhere in between?"* and saves response to slot `user_comm_style`
  - **Step `complete`**: Calls capability [`complete_onboarding`](#complete-onboarding) (Side-Effect: `write`)

### Workflow: `web_app_recon_lab`
**Description:** Web app reconnaissance against an authorized lab URL. Performs safe enumeration and generates a markdown report.

- **Specification File:** [core/workflows/templates/web_app_recon_lab.yaml](../core/workflows/templates/web_app_recon_lab.yaml)
- **Version:** `0.1.0` | **Tags:** `web, lab, authorized, read_only, planned`
- **Required Inputs:** `base_url`
- **Example Natural Language Trigger Queries:**
  - "Run safe web reconnaissance on http://10.0.2.15"
  - "Enumerate directories and headers on ctf web app http://mylab.local"

**Execution Steps & Capabilities Utilized:**
  - **Step `s1`**: Calls capability [`web_recon_lab`](#web-recon-lab) (Side-Effect: `read`)
  - **Step `s2`**: Calls capability [`directory_inventory_safe`](#directory-inventory-safe) (Side-Effect: `read`)
  - **Step `s3`**: Calls capability [`security_report_generate`](#security-report-generate) (Side-Effect: `write`)

---

## Tools by Category

### Awareness & Vision Modules

#### <a name="analyze_clipboard_image"></a> `analyze_clipboard_image`
**Description:** Analyze or explain the image currently copied in the clipboard. Useful when the user has copied a chart, diagram, screenshot, or photo.

- **Execution File:** [modules/vision/plugin.py:L341](../modules/vision/plugin.py#L341) (Handler: `_handle_clipboard_image`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `analyze_clipboard_image` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Explain the image in my clipboard", "What is this copied image?"
- **Parameters Schema:**
*None*

---

#### <a name="analyze_screen"></a> `analyze_screen`
**Description:** Take a screenshot of the current screen and explain what is on it. Use for: errors, crash dialogs, popups, UI questions, 'what is this'.

- **Execution File:** [modules/vision/plugin.py:L304](../modules/vision/plugin.py#L304) (Handler: `_handle_analyze_screen`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `slow`
- **Trigger Commands / Invocation:** `analyze_screen` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Explain what's on my screen", "What am I looking at right now?", "Analyze this screen"
- **Parameters Schema:**
*None*

---

#### <a name="awareness_status"></a> `awareness_status`
**Description:** Check whether awareness mode is currently running.

- **Execution File:** [modules/awareness/plugin.py:L72](../modules/awareness/plugin.py#L72) (Handler: `handle_status`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `awareness_status` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Is awareness mode running?", "Check awareness status"
- **Parameters Schema:**
*None*

---

#### <a name="disable_awareness_mode"></a> `disable_awareness_mode`
**Description:** Stop the continuous screen awareness capture loop.

- **Execution File:** [modules/awareness/plugin.py:L68](../modules/awareness/plugin.py#L68) (Handler: `handle_disable`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `disable_awareness_mode` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Stop continuous screen awareness", "Turn off screen awareness capture"
- **Parameters Schema:**
*None*

---

#### <a name="enable_awareness_mode"></a> `enable_awareness_mode`
**Description:** Start continuous awareness mode: FRIDAY watches your screen and suggests help if you seem stuck. Requires awareness.enabled=true in config.

- **Execution File:** [modules/awareness/plugin.py:L59](../modules/awareness/plugin.py#L59) (Handler: `handle_enable`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `enable_awareness_mode` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Start screen awareness mode", "Turn on continuous awareness capture"
- **Parameters Schema:**
*None*

---

#### <a name="explain_meme"></a> `explain_meme`
**Description:** Explain a meme — the joke, the cultural context, and why it is funny.

- **Execution File:** [modules/vision/plugin.py:L368](../modules/vision/plugin.py#L368) (Handler: `_handle_explain_meme`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `explain_meme` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Explain this meme", "What is the joke in this meme?"
- **Parameters Schema:**
*None*

---

#### <a name="find_ui_element"></a> `find_ui_element`
**Description:** Find a UI element on screen by description. Returns its approximate location. Can optionally click it.

- **Execution File:** [modules/vision/plugin.py:L440](../modules/vision/plugin.py#L440) (Handler: `_handle_find_ui_element`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `find_ui_element` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Find the search bar on screen", "Locate the submit button and click it"
- **Parameters Schema:**
*None*

---

#### <a name="read_text_from_image"></a> `read_text_from_image`
**Description:** Extract and read text from a screenshot, image, or photo. Works on handwritten notes, receipts, terminal output, code screenshots.

- **Execution File:** [modules/vision/plugin.py:L315](../modules/vision/plugin.py#L315) (Handler: `_handle_read_text`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `slow`
- **Trigger Commands / Invocation:** `read_text_from_image` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Read the text from this screenshot", "Extract handwritten notes from this image"
- **Parameters Schema:**
*None*

---

#### <a name="recent_screen_activity"></a> `recent_screen_activity`
**Description:** Show a summary of recently captured screen activity.

- **Execution File:** [modules/awareness/plugin.py:L81](../modules/awareness/plugin.py#L81) (Handler: `handle_recent`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `recent_screen_activity` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Show recent screen activity", "Summarize what I've been doing on screen"
- **Parameters Schema:**
*None*

---

#### <a name="review_design"></a> `review_design`
**Description:** Analyze a UI screenshot and give honest design or usability feedback.

- **Execution File:** [modules/vision/plugin.py:L390](../modules/vision/plugin.py#L390) (Handler: `_handle_review_design`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `review_design` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Give me feedback on this UI design", "Review the usability of this layout screenshot"
- **Parameters Schema:**
*None*

---

#### <a name="roast_desktop"></a> `roast_desktop`
**Description:** Take a screenshot and make a funny comment about the current desktop.

- **Execution File:** [modules/vision/plugin.py:L379](../modules/vision/plugin.py#L379) (Handler: `_handle_roast_desktop`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `roast_desktop` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Roast my desktop", "Make a funny comment about my current screen"
- **Parameters Schema:**
*None*

---

#### <a name="summarize_screen"></a> `summarize_screen`
**Description:** Take a screenshot and give a summary of what the user is currently looking at. Good for dashboards, articles, presentations, and long documents.

- **Execution File:** [modules/vision/plugin.py:L326](../modules/vision/plugin.py#L326) (Handler: `_handle_summarize_screen`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `slow`
- **Trigger Commands / Invocation:** `summarize_screen` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Summarize what I am looking at", "Give me a summary of this dashboard screen"
- **Parameters Schema:**
*None*

---

### Core Voice & System Controls

#### <a name="disable_voice"></a> `disable_voice`
**Description:** Disable the microphone and stop listening for voice commands.

- **Execution File:** [modules/voice_io/plugin.py:L117](../modules/voice_io/plugin.py#L117) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `disable_voice` (Direct intent/routing), "turn off microphone" (Voice/Text Alias), "stop listening" (Voice/Text Alias), "turn off mic" (Voice/Text Alias), "disable voice" (Voice/Text Alias), `r"\b(?:disable|stop|turn off)\s+(?:the\s+)?(?:mic|microphone|voice)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Disable voice", "Stop listening", "Turn off mic"
- **Parameters Schema:**
*None*

---

#### <a name="enable_voice"></a> `enable_voice`
**Description:** Enable the microphone and start listening for voice commands.

- **Execution File:** [modules/voice_io/plugin.py:L111](../modules/voice_io/plugin.py#L111) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `enable_voice` (Direct intent/routing), "start listening" (Voice/Text Alias), "enable voice" (Voice/Text Alias), "turn on mic" (Voice/Text Alias), "turn on microphone" (Voice/Text Alias), `r"\b(?:enable|start|turn on)\s+(?:the\s+)?(?:mic|microphone|voice)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Enable voice", "Start listening", "Turn on microphone"
- **Parameters Schema:**
*None*

---

### Cybersecurity Lab Tools

#### <a name="compare_scan_results"></a> `compare_scan_results`
**Description:** Diff two structured scan observations (e.g. two host_service_scan results) and emit added/removed/changed hosts and ports. Deterministic.

- **Execution File:** [modules/security_tools/plugin.py:L669](../modules/security_tools/plugin.py#L669) (Handler: `handle_compare_scan_results`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `fast`
- **Trigger Commands / Invocation:** `compare_scan_results` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Compare these two nmap scan results", "Show a diff between scan A and scan B"
- **Parameters Schema:**
*None*

---

#### <a name="dns_enum_owned_domain"></a> `dns_enum_owned_domain`
**Description:** Read-only DNS enumeration for a domain the user owns or has authorization to query. Returns records grouped by type (A, AAAA, MX, NS, TXT, SOA, CNAME, PTR, SRV, CAA).

- **Execution File:** [modules/security_tools/plugin.py:L598](../modules/security_tools/plugin.py#L598) (Handler: `handle_dns_enum_owned_domain`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `fast`
- **Trigger Commands / Invocation:** `dns_enum_owned_domain` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Enumerate DNS records for domain mylab.local", "Perform DNS enumeration on ctf-domain.org"
- **Parameters Schema:**
*None*

---

#### <a name="host_service_scan"></a> `host_service_scan`
**Description:** Read-only TCP service/version scan of an authorized lab or loopback host using nmap. Returns open ports and detected service versions. Refuses any target outside the configured authorized_scopes.

- **Execution File:** [modules/security_tools/plugin.py:L476](../modules/security_tools/plugin.py#L476) (Handler: `handle_host_service_scan`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `host_service_scan` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Scan port services on host 10.0.2.15", "Run a TCP port scan on 127.0.0.1"
- **Parameters Schema:**
*None*

---

#### <a name="ping_sweep"></a> `ping_sweep`
**Description:** Read-only host discovery (-sn) across an authorized subnet. Returns the list of live hosts. Refuses any subnet outside the configured authorized_scopes.

- **Execution File:** [modules/security_tools/plugin.py:L516](../modules/security_tools/plugin.py#L516) (Handler: `handle_ping_sweep`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `ping_sweep` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Run a ping sweep on subnet 10.0.2.0/24", "Discover live hosts in 192.168.1.0/24"
- **Parameters Schema:**
*None*

---

#### <a name="security_report_generate"></a> `security_report_generate`
**Description:** Generate a markdown security report from previously collected scan observations stored in the active turn. Deterministic — no shell, no LLM.

- **Execution File:** [modules/security_tools/plugin.py:L636](../modules/security_tools/plugin.py#L636) (Handler: `handle_security_report_generate`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `fast`
- **Trigger Commands / Invocation:** `security_report_generate` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Generate a markdown security report from the scans", "Compile a security report for the active turn"
- **Parameters Schema:**
*None*

---

#### <a name="web_directory_enum"></a> `web_directory_enum`
**Description:** Enumerate directories/paths on an authorized lab web server using gobuster. Read-only. Refuses URLs whose host falls outside authorized_scopes.

- **Execution File:** [modules/security_tools/plugin.py:L554](../modules/security_tools/plugin.py#L554) (Handler: `handle_web_directory_enum`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `web_directory_enum` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Enumerate directories on web server http://10.0.2.15", "Run a Gobuster scan on http://ctf-target.lab"
- **Parameters Schema:**
*None*

---

### Integrations & Comms

#### <a name="get_business_news"></a> `get_business_news`
**Description:** Fetch the top 5 business news articles from Forbes Business via Feed Prism.

- **Execution File:** [modules/news_feed/plugin.py:L69](../modules/news_feed/plugin.py#L69) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_business_news` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Show top business news headlines", "What's the business news from Forbes?"
- **Parameters Schema:**
*None*

---

#### <a name="get_company_news"></a> `get_company_news`
**Description:** Fetch the top 5 big-tech company announcements from Google Blog and Apple Newsroom via Feed Prism.

- **Execution File:** [modules/news_feed/plugin.py:L69](../modules/news_feed/plugin.py#L69) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_company_news` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "What are the latest tech company announcements?", "Show Apple and Google news announcements"
- **Parameters Schema:**
*None*

---

#### <a name="get_global_news_feed"></a> `get_global_news_feed`
**Description:** Fetch the top 5 global/world news headlines from Feed Prism.

- **Execution File:** [modules/news_feed/plugin.py:L69](../modules/news_feed/plugin.py#L69) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_global_news_feed` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "What is the global news today?", "Fetch world news headlines"
- **Parameters Schema:**
*None*

---

#### <a name="get_news_briefing"></a> `get_news_briefing`
**Description:** Fetch a comprehensive news digest from all Feed Prism categories (Technology, Global News, Company News, Startups, Security, Business), open worldmonitor.app in the browser, and deliver a summarised spoken briefing.

- **Execution File:** [modules/news_feed/plugin.py:L102](../modules/news_feed/plugin.py#L102) (Handler: `_handle_briefing`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_news_briefing` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Give me a full news briefing", "Show news digest and read it aloud"
- **Parameters Schema:**
*None*

---

#### <a name="get_security_news"></a> `get_security_news`
**Description:** Fetch the top 5 cybersecurity news stories from The Hacker News via Feed Prism.

- **Execution File:** [modules/news_feed/plugin.py:L69](../modules/news_feed/plugin.py#L69) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_security_news` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Show cybersecurity news headlines", "What are the top security news stories today?"
- **Parameters Schema:**
*None*

---

#### <a name="get_startup_news"></a> `get_startup_news`
**Description:** Fetch the top 5 startup and product launch stories from Product Hunt via Feed Prism.

- **Execution File:** [modules/news_feed/plugin.py:L69](../modules/news_feed/plugin.py#L69) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_startup_news` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Fetch startup news from Product Hunt", "Show recent product launches and startups"
- **Parameters Schema:**
*None*

---

#### <a name="get_technology_news"></a> `get_technology_news`
**Description:** Fetch the top 5 technology news articles from TechCrunch, The Verge, and Wired via Feed Prism.

- **Execution File:** [modules/news_feed/plugin.py:L69](../modules/news_feed/plugin.py#L69) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_technology_news` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "What is the latest tech news?", "Fetch technology news stories"
- **Parameters Schema:**
*None*

---

#### <a name="get_weather"></a> `get_weather`
**Description:** Tell the user the current weather for a city, town, or address. Use whenever the user asks about temperature, conditions, or the forecast. Picks up the location from the user's words.

- **Execution File:** [modules/weather/plugin.py:L86](../modules/weather/plugin.py#L86) (Handler: `handle_get_weather`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `fast`
- **Trigger Commands / Invocation:** `get_weather` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "What is the weather in Paris?", "How's the weather today in New York?"
- **Parameters Schema:**
*None*

---

### Memory, Identity & Chat

#### <a name="complete_onboarding"></a> `complete_onboarding`
**Description:** Final step of the user_onboarding workflow: write every collected profile field, mark onboarding completed, return the personalized greeting.

- **Execution File:** [modules/onboarding/extension.py:L259](../modules/onboarding/extension.py#L259) (Handler: `_handle_complete_onboarding`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `complete_onboarding` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Complete my onboarding profile"
- **Parameters Schema:**
*None*

---

#### <a name="extract_answer_or_skip"></a> `extract_answer_or_skip`
**Description:** Internal: pass through onboarding answers verbatim; return empty string for skip-tokens ('skip', 'no', 'later').

- **Execution File:** [modules/onboarding/extension.py:L253](../modules/onboarding/extension.py#L253) (Handler: `_handle_extract_answer_or_skip`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `extract_answer_or_skip` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run extract answer or skip", "Can you trigger extract answer or skip?", "How do I use extract answer or skip?"
- **Parameters Schema:**
*None*

---

#### <a name="extract_user_name_or_skip"></a> `extract_user_name_or_skip`
**Description:** Internal: parse a name from an onboarding reply.

- **Execution File:** [modules/onboarding/extension.py:L247](../modules/onboarding/extension.py#L247) (Handler: `_handle_extract_name_or_skip`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `extract_user_name_or_skip` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run extract user name or skip", "Can you trigger extract user name or skip?", "How do I use extract user name or skip?"
- **Parameters Schema:**
*None*

---

#### <a name="forget_memory"></a> `forget_memory`
**Description:** Forget a specific fact by key (e.g. 'location', 'name'). Removes the fact from the canonical memory store and the user_profile mirror.

- **Execution File:** [modules/memory_manager/plugin.py:L100](../modules/memory_manager/plugin.py#L100) (Handler: `_handle_forget_memory`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `forget_memory` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Forget my location", "Forget that I prefer concise answers"
- **Parameters Schema:**
*None*

---

#### <a name="greet"></a> `greet`
**Description:** Respond to a greeting. Use when the user says hello, hi, hey, or greets FRIDAY.

- **Execution File:** [modules/greeter/extension.py:L129](../modules/greeter/extension.py#L129) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `greet` (Direct intent/routing), "hey" (Voice/Text Alias), "good evening" (Voice/Text Alias), "hello" (Voice/Text Alias), "hi" (Voice/Text Alias), "hey friday" (Voice/Text Alias), "good morning" (Voice/Text Alias), `r"\b(hi|hello|hey|good morning|good afternoon|good evening)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Hello Friday", "Good morning!", "Hi", "Hey"
- **Parameters Schema:**


---

#### <a name="llm_chat"></a> `llm_chat`
**Description:** Answer a general question, have a conversation, or handle any request that doesn't fit a specific tool. Use this as the fallback for open-ended queries.

- **Execution File:** [modules/llm_chat/plugin.py:L42](../modules/llm_chat/plugin.py#L42) (Handler: `handle_chat`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `generative`
- **Trigger Commands / Invocation:** `llm_chat` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run llm chat", "Can you trigger llm chat?", "How do I use llm chat?"
- **Parameters Schema:**
*None*

---

#### <a name="resume_session"></a> `resume_session`
**Description:** Resume the previous session. Use ONLY when FRIDAY asked at startup whether to continue from the last session and the user agrees — says yes, sure, continue, absolutely, yep, pick up where we left off, or similar affirmations.

- **Execution File:** [modules/greeter/extension.py:L129](../modules/greeter/extension.py#L129) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `resume_session` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Yes, resume the previous session", "Pick up where we left off"
- **Parameters Schema:**


---

#### <a name="show_capabilities"></a> `show_capabilities`
**Description:** List everything FRIDAY can do. Use ONLY when the user explicitly asks 'what can you do', 'show your capabilities', 'list your tools', 'show commands', or says a bare 'help' with nothing else. Do NOT use for 'help me write X', 'help me fix Y', or any task request.

- **Execution File:** [modules/greeter/extension.py:L129](../modules/greeter/extension.py#L129) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `show_capabilities` (Direct intent/routing), "what can you do" (Voice/Text Alias), "show help" (Voice/Text Alias), "show commands" (Voice/Text Alias), "list capabilities" (Voice/Text Alias), `r"what can you do"` (Regex Pattern), `r"show (?:me )?(?:your\s+)?(?:commands|capabilities|abilities)"` (Regex Pattern), `r"list (?:your\s+)?(?:commands|capabilities)"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "What can you do?", "Show commands", "List capabilities", "Help"
- **Parameters Schema:**


---

#### <a name="show_memories"></a> `show_memories`
**Description:** Show what FRIDAY remembers about the user — preferences, facts, and context learned from past conversations.

- **Execution File:** [modules/memory_manager/plugin.py:L83](../modules/memory_manager/plugin.py#L83) (Handler: `_handle_show_memories`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `show_memories` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "What do you remember about me?", "Show my user profile details and facts"
- **Parameters Schema:**
*None*

---

#### <a name="start_fresh_session"></a> `start_fresh_session`
**Description:** Start a new session and discard the previous one. Use ONLY when FRIDAY asked at startup whether to continue from the last session and the user declines — says no, fresh start, new session, never mind, start over, different topic, or similar.

- **Execution File:** [modules/greeter/extension.py:L129](../modules/greeter/extension.py#L129) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `start_fresh_session` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "No, start a fresh session", "Let's start over with a new topic"
- **Parameters Schema:**


---

#### <a name="update_user_profile"></a> `update_user_profile`
**Description:** Update what FRIDAY remembers about the user. Use when the user says things like 'call me X', 'my name is X', 'I'm a Y', 'I live in Z', 'remember I prefer concise answers'. Field must be one of: name, role, location, preferences, comm_style.

- **Execution File:** [modules/onboarding/extension.py:L220](../modules/onboarding/extension.py#L220) (Handler: `_handle_update_profile`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `update_user_profile` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Call me Santhosh", "My role is software engineer", "I am based in San Francisco", "Remember that I prefer detailed explanations"
- **Parameters Schema:**
*None*

---

### Miscellaneous / Core Tools

#### <a name="cancel_dictation"></a> `cancel_dictation`
**Description:** Discard the current dictation memo without saving.

- **Execution File:** [modules/dictation/plugin.py:L84](../modules/dictation/plugin.py#L84) (Handler: `handle_cancel`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `cancel_dictation` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Cancel this voice memo", "Discard dictation"
- **Parameters Schema:**
*None*

---

#### <a name="end_dictation"></a> `end_dictation`
**Description:** Finish and save the current dictation memo.

- **Execution File:** [modules/dictation/plugin.py:L69](../modules/dictation/plugin.py#L69) (Handler: `handle_end`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `end_dictation` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Finish saving this dictation", "End dictation and save memo"
- **Parameters Schema:**
*None*

---

#### <a name="query_document"></a> `query_document`
**Description:** Ask a question about a specific document file (PDF, DOCX, PPTX, XLSX, TXT, MD). Summarizes the file or retrieves specific information from it.

- **Execution File:** [modules/document_intel/plugin.py:L127](../modules/document_intel/plugin.py#L127) (Handler: `_handle_query_document`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `query_document` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Summarize paper.pdf", "What does this Excel spreadsheet say about revenue?", "Ask document about system requirements"
- **Parameters Schema:**
*None*

---

#### <a name="research_topic"></a> `research_topic`
**Description:** Run an agentic internet research session on a topic. Uses a classifier → researcher loop → writer pipeline (inspired by Vane). Searches a public SearxNG pool across web/academic/social categories with per-instance circuit-breakers and DuckDuckGo HTML as a last-resort fallback. Scrapes top sources and synthesizes a briefing with numbered [N] citations to ~/Documents/friday-research/<topic>/. Modes: speed/balanced/quality (default: balanced). Use for 'research X', 'find research papers about X', 'do a deep dive on X', or 'put together a briefing on X'.

- **Execution File:** [modules/research_agent/plugin.py:L56](../modules/research_agent/plugin.py#L56) (Handler: `handle_research`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `write` | Latency: `background`
- **Trigger Commands / Invocation:** `research_topic` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Research the impact of quantum computing on cryptography", "Do a deep dive research briefing on next.js architectures", "Find research papers about solar sails"
- **Parameters Schema:**
*None*

---

#### <a name="search_workspace"></a> `search_workspace`
**Description:** Search across all indexed documents and notes in the workspace. Finds relevant content from any previously indexed file.

- **Execution File:** [modules/document_intel/plugin.py:L196](../modules/document_intel/plugin.py#L196) (Handler: `_handle_search_workspace`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `search_workspace` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Search my workspace for project plans", "Find notes about API tokens across my indexed documents"
- **Parameters Schema:**
*None*

---

#### <a name="set_voice_mode"></a> `set_voice_mode`
**Description:** Switch voice listening mode between persistent, wake-word, on-demand, or manual.

- **Execution File:** [modules/voice_io/plugin.py:L155](../modules/voice_io/plugin.py#L155) (Handler: `set_voice_mode`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `set_voice_mode` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run set voice mode", "Can you trigger set voice mode?", "How do I use set voice mode?"
- **Parameters Schema:**
*None*

---

#### <a name="start_dictation"></a> `start_dictation`
**Description:** Start a long-form dictation session. While active, FRIDAY captures everything spoken into a timestamped memo file in ~/Documents/friday-memos. Use when the user asks to take a memo, start dictation, or begin a journal entry.

- **Execution File:** [modules/dictation/plugin.py:L64](../modules/dictation/plugin.py#L64) (Handler: `handle_start`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `start_dictation` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Start a long-form dictation session", "Begin a voice memo", "Take a journal entry"
- **Parameters Schema:**
*None*

---

### System & Desktop Controls

#### <a name="compare_screenshots"></a> `compare_screenshots`
**Description:** Compare two screenshots and explain what changed or is different.

- **Execution File:** [modules/vision/plugin.py:L405](../modules/vision/plugin.py#L405) (Handler: `_handle_compare_screenshots`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `compare_screenshots` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run compare screenshots", "Can you trigger compare screenshots?", "How do I use compare screenshots?"
- **Parameters Schema:**
*None*

---

#### <a name="confirm_no"></a> `confirm_no`
**Description:** User declines or cancels a pending action (no, nope, cancel).

- **Execution File:** [modules/system_control/plugin.py:L485](../modules/system_control/plugin.py#L485) (Handler: `handle_no`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `confirm_no` (Direct intent/routing), "stop that" (Voice/Text Alias), "cancel" (Voice/Text Alias), "no" (Voice/Text Alias), "nope" (Voice/Text Alias), `r"^(?:no|nope|cancel|stop)$"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "No", "Nope", "Cancel", "Stop that"
- **Parameters Schema:**
*None*

---

#### <a name="confirm_yes"></a> `confirm_yes`
**Description:** User confirms a pending action (yes, sure, ok, open it).

- **Execution File:** [modules/system_control/plugin.py:L453](../modules/system_control/plugin.py#L453) (Handler: `handle_yes`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `confirm_yes` (Direct intent/routing), "okay" (Voice/Text Alias), "sure" (Voice/Text Alias), "yeah" (Voice/Text Alias), "yes" (Voice/Text Alias), "open it" (Voice/Text Alias), "do it" (Voice/Text Alias), `r"^(?:yes|yeah|yep|sure|okay|ok|open it|do it)$"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Yes", "Yeah", "Do it", "Sure", "Okay"
- **Parameters Schema:**
*None*

---

#### <a name="debug_code_screenshot"></a> `debug_code_screenshot`
**Description:** Read a screenshot of code, a terminal error, or a stack trace and explain the issue.

- **Execution File:** [modules/vision/plugin.py:L357](../modules/vision/plugin.py#L357) (Handler: `_handle_debug_code`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `slow`
- **Trigger Commands / Invocation:** `debug_code_screenshot` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run debug code screenshot", "Can you trigger debug code screenshot?", "How do I use debug code screenshot?"
- **Parameters Schema:**
*None*

---

#### <a name="get_active_window"></a> `get_active_window`
**Description:** Return the name and title of the currently focused application window.

- **Execution File:** [modules/system_control/plugin.py:L320](../modules/system_control/plugin.py#L320) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_active_window` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get active window", "Can you trigger get active window?", "How do I use get active window?"
- **Parameters Schema:**
*None*

---

#### <a name="get_battery"></a> `get_battery`
**Description:** Check the current battery percentage and whether it is charging.

- **Execution File:** [modules/system_control/plugin.py:L131](../modules/system_control/plugin.py#L131) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_battery` (Direct intent/routing), "battery status" (Voice/Text Alias), "battery level" (Voice/Text Alias), "battery percent" (Voice/Text Alias), `r"\b(?:battery\s+(?:status|level|percent(?:age)?|charge|life|remaining)|(?:what(?:'s| is)\s+(?:my\s+|the\s+)?battery)|how('s|\s+is)\s+(?:my\s+|the\s+)?battery)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Battery status", "What is my battery level?", "How's my battery?"
- **Parameters Schema:**
*None*

---

#### <a name="get_clipboard"></a> `get_clipboard`
**Description:** Read the current clipboard text content.

- **Execution File:** [modules/system_control/plugin.py:L304](../modules/system_control/plugin.py#L304) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_clipboard` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get clipboard", "Can you trigger get clipboard?", "How do I use get clipboard?"
- **Parameters Schema:**
*None*

---

#### <a name="get_cpu_ram"></a> `get_cpu_ram`
**Description:** Show current CPU and RAM usage statistics.

- **Execution File:** [modules/system_control/plugin.py:L138](../modules/system_control/plugin.py#L138) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_cpu_ram` (Direct intent/routing), "memory usage" (Voice/Text Alias), "cpu usage" (Voice/Text Alias), "ram usage" (Voice/Text Alias), `r"\b(?:cpu\s+(?:usage|load|status)|ram\s+(?:usage|status|free)|memory\s+(?:usage|load|status|free))\b"` (Regex Pattern), `r"\bsystem\s+(?:usage|load|performance)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "CPU usage", "RAM usage", "Memory usage"
- **Parameters Schema:**
*None*

---

#### <a name="get_friday_status"></a> `get_friday_status`
**Description:** Report FRIDAY runtime status, including model readiness and disabled optional skills.

- **Execution File:** [modules/system_control/plugin.py:L593](../modules/system_control/plugin.py#L593) (Handler: `handle_friday_status`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_friday_status` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get friday status", "Can you trigger get friday status?", "How do I use get friday status?"
- **Parameters Schema:**
*None*

---

#### <a name="get_system_status"></a> `get_system_status`
**Description:** Report overall system health: CPU usage, RAM usage, and battery level.

- **Execution File:** [modules/system_control/plugin.py:L117](../modules/system_control/plugin.py#L117) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_system_status` (Direct intent/routing), "system health" (Voice/Text Alias), "system status" (Voice/Text Alias), `r"\b(?:system status|system health)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "System status", "System health"
- **Parameters Schema:**
*None*

---

#### <a name="launch_app"></a> `launch_app`
**Description:** Open or launch a desktop application by name (e.g. firefox, chrome, calculator, nautilus).

- **Execution File:** [modules/system_control/plugin.py:L343](../modules/system_control/plugin.py#L343) (Handler: `handle_launch_app`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `launch_app` (Direct intent/routing), "start" (Voice/Text Alias), "open" (Voice/Text Alias), "launch" (Voice/Text Alias), `r"\b(?:open|launch|start|bring up)\s+(?!file\b|folder\b|the\s+folder\b)[a-z0-9][\w\-\s,]*(?:\band\b\s*[a-z0-9][\w\-\s]*)*"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Open Firefox", "Launch calculator", "Start Chrome"
- **Parameters Schema:**
*None*

---

#### <a name="list_folder_contents"></a> `list_folder_contents`
**Description:** List the visible files inside a folder.

- **Execution File:** [modules/system_control/plugin.py:L444](../modules/system_control/plugin.py#L444) (Handler: `handle_list_folder_contents`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `list_folder_contents` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run list folder contents", "Can you trigger list folder contents?", "How do I use list folder contents?"
- **Parameters Schema:**
*None*

---

#### <a name="manage_file"></a> `manage_file`
**Description:** Create, write, append, or read a text file. You can also save the last assistant answer into a file.

- **Execution File:** [modules/system_control/plugin.py:L418](../modules/system_control/plugin.py#L418) (Handler: `handle_manage_file`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `manage_file` (Direct intent/routing), "save that to" (Voice/Text Alias), "new file" (Voice/Text Alias), "create file" (Voice/Text Alias), "make file" (Voice/Text Alias), "save it to" (Voice/Text Alias), "write that to" (Voice/Text Alias), "write it to" (Voice/Text Alias), `r"\b(?:create|make)\s+(?:a\s+)?file\b"` (Regex Pattern), `r"\b(?:write|save|append|add)\s+(?:it|that|this|the answer|the response)\s+(?:to|into|in)\s+\S+"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Create a file", "Write this response to output.txt"
- **Parameters Schema:**
*None*

---

#### <a name="open_file"></a> `open_file`
**Description:** Open a specific file using the default application.

- **Execution File:** [modules/system_control/plugin.py:L421](../modules/system_control/plugin.py#L421) (Handler: `handle_open_file`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `open_file` (Direct intent/routing), "open file" (Voice/Text Alias), `r"\bopen\s+(?:the\s+)?file\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Open the file notes.txt"
- **Parameters Schema:**
*None*

---

#### <a name="open_folder"></a> `open_folder`
**Description:** Open a folder in the system file manager.

- **Execution File:** [modules/system_control/plugin.py:L447](../modules/system_control/plugin.py#L447) (Handler: `handle_open_folder`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `open_folder` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run open folder", "Can you trigger open folder?", "How do I use open folder?"
- **Parameters Schema:**
*None*

---

#### <a name="open_url"></a> `open_url`
**Description:** Open a URL in the default web browser.

- **Execution File:** [modules/system_control/plugin.py:L331](../modules/system_control/plugin.py#L331) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `external` | Latency: `interactive`
- **Trigger Commands / Invocation:** `open_url` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run open url", "Can you trigger open url?", "How do I use open url?"
- **Parameters Schema:**
*None*

---

#### <a name="read_file"></a> `read_file`
**Description:** Read or preview the contents of a file.

- **Execution File:** [modules/system_control/plugin.py:L424](../modules/system_control/plugin.py#L424) (Handler: `handle_read_file`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `read_file` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run read file", "Can you trigger read file?", "How do I use read file?"
- **Parameters Schema:**
*None*

---

#### <a name="recall_personal_fact"></a> `recall_personal_fact`
**Description:** Recall a stored fact about the user.

- **Execution File:** [modules/system_control/plugin.py:L525](../modules/system_control/plugin.py#L525) (Handler: `handle_recall_personal_fact`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `recall_personal_fact` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run recall personal fact", "Can you trigger recall personal fact?", "How do I use recall personal fact?"
- **Parameters Schema:**
*None*

---

#### <a name="record_personal_fact"></a> `record_personal_fact`
**Description:** Store a fact about the user (name, location, role, etc.).

- **Execution File:** [modules/system_control/plugin.py:L504](../modules/system_control/plugin.py#L504) (Handler: `handle_record_personal_fact`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `record_personal_fact` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run record personal fact", "Can you trigger record personal fact?", "How do I use record personal fact?"
- **Parameters Schema:**
*None*

---

#### <a name="search_file"></a> `search_file`
**Description:** Search for a file by name on the filesystem.

- **Execution File:** [modules/system_control/plugin.py:L415](../modules/system_control/plugin.py#L415) (Handler: `handle_search_file`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `search_file` (Direct intent/routing), "find file" (Voice/Text Alias), "locate file" (Voice/Text Alias), "search file" (Voice/Text Alias), `r"\b(?:find|search|locate)\s+(?:for\s+)?(?:file\s+)?\S+"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Find file important.txt", "Search for paper.pdf"
- **Parameters Schema:**
*None*

---

#### <a name="select_file_candidate"></a> `select_file_candidate`
**Description:** Choose one file from a pending list of candidates.

- **Execution File:** [modules/system_control/plugin.py:L450](../modules/system_control/plugin.py#L450) (Handler: `handle_select_file_candidate`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `select_file_candidate` (Direct intent/routing), "first one" (Voice/Text Alias), "this one" (Voice/Text Alias), "option 1" (Voice/Text Alias), "that one" (Voice/Text Alias), "second one" (Voice/Text Alias), "option 2" (Voice/Text Alias), `r"^(?:the\s+)?(?:first|second|third|fourth|fifth|last)\s+(?:one|file)$"` (Regex Pattern), `r"^(?:the\s+)?(?:this|that)\s+(?:one|file)$"` (Regex Pattern), `r"^(?:option\s+)?\d+$"` (Regex Pattern), `r"^(?:the\s+)?(?:pdf|txt|md|json|csv|py|docx)\s+one$"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Please run select file candidate", "Can you trigger select file candidate?", "How do I use select file candidate?"
- **Parameters Schema:**
*None*

---

#### <a name="set_clipboard"></a> `set_clipboard`
**Description:** Write text to the system clipboard.

- **Execution File:** [modules/system_control/plugin.py:L310](../modules/system_control/plugin.py#L310) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `set_clipboard` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run set clipboard", "Can you trigger set clipboard?", "How do I use set clipboard?"
- **Parameters Schema:**
*None*

---

#### <a name="set_volume"></a> `set_volume`
**Description:** Control system audio volume.

- **Execution File:** [modules/system_control/plugin.py:L368](../modules/system_control/plugin.py#L368) (Handler: `handle_set_volume`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `set_volume` (Direct intent/routing), "volume up" (Voice/Text Alias), "mute" (Voice/Text Alias), "decrease volume" (Voice/Text Alias), "increase volume" (Voice/Text Alias), "volume down" (Voice/Text Alias), `r"\b(?:volume|mute|unmute)\b"` (Regex Pattern), `r"\b(?:increase|decrease|turn)\s+volume\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Volume up", "Increase volume", "Mute", "Turn down volume"
- **Parameters Schema:**
*None*

---

#### <a name="shutdown_assistant"></a> `shutdown_assistant`
**Description:** Close the application and say goodbye.

- **Execution File:** [modules/system_control/plugin.py:L549](../modules/system_control/plugin.py#L549) (Handler: `handle_shutdown`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `critical` | Latency: `interactive`
- **Trigger Commands / Invocation:** `shutdown_assistant` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run shutdown assistant", "Can you trigger shutdown assistant?", "How do I use shutdown assistant?"
- **Parameters Schema:**
*None*

---

#### <a name="summarize_file"></a> `summarize_file`
**Description:** Summarize the contents of a file offline.

- **Execution File:** [modules/system_control/plugin.py:L427](../modules/system_control/plugin.py#L427) (Handler: `handle_summarize_file`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `summarize_file` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run summarize file", "Can you trigger summarize file?", "How do I use summarize file?"
- **Parameters Schema:**
*None*

---

#### <a name="take_screenshot"></a> `take_screenshot`
**Description:** Capture the current screen and save it as an image file.

- **Execution File:** [modules/system_control/plugin.py:L335](../modules/system_control/plugin.py#L335) (Handler: `handle_take_screenshot`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `take_screenshot` (Direct intent/routing), "screen shot" (Voice/Text Alias), "capture screen" (Voice/Text Alias), `r"\b(?:take|capture|grab|snap|get|make)\s+(?:a\s+|another\s+|the\s+)?(?:screenshot|screen\s*shot|screen\s+capture)\b"` (Regex Pattern), `r"^(?:please\s+)?screen\s*shot(?:\s+please)?[.!?]?$"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Take a screenshot", "Capture the screen", "Screen shot"
- **Parameters Schema:**
*None*

---

### Tasks, Goals & Triggers

#### <a name="add_clipboard_trigger"></a> `add_clipboard_trigger`
**Description:** Monitor the clipboard and fire an event when its content changes.

- **Execution File:** [modules/triggers/plugin.py:L103](../modules/triggers/plugin.py#L103) (Handler: `handle_add_clipboard`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `add_clipboard_trigger` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run add clipboard trigger", "Can you trigger add clipboard trigger?", "How do I use add clipboard trigger?"
- **Parameters Schema:**
*None*

---

#### <a name="add_cron_trigger"></a> `add_cron_trigger`
**Description:** Schedule a repeating trigger that fires every N seconds.

- **Execution File:** [modules/triggers/plugin.py:L89](../modules/triggers/plugin.py#L89) (Handler: `handle_add_cron`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `add_cron_trigger` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run add cron trigger", "Can you trigger add cron trigger?", "How do I use add cron trigger?"
- **Parameters Schema:**
*None*

---

#### <a name="add_file_watch_trigger"></a> `add_file_watch_trigger`
**Description:** Watch a file or directory for changes and fire an event when anything changes.

- **Execution File:** [modules/triggers/plugin.py:L96](../modules/triggers/plugin.py#L96) (Handler: `handle_add_file_watch`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `add_file_watch_trigger` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run add file watch trigger", "Can you trigger add file watch trigger?", "How do I use add file watch trigger?"
- **Parameters Schema:**
*None*

---

#### <a name="complete_goal"></a> `complete_goal`
**Description:** Mark a goal as completed.

- **Execution File:** [modules/goals/plugin.py:L244](../modules/goals/plugin.py#L244) (Handler: `handle_complete`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `complete_goal` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run complete goal", "Can you trigger complete goal?", "How do I use complete goal?"
- **Parameters Schema:**
*None*

---

#### <a name="create_goal"></a> `create_goal`
**Description:** Create a new goal in the OKR hierarchy. Levels: objective, key_result, milestone, task, daily_action. Time horizons: life, yearly, quarterly, monthly, weekly, daily.

- **Execution File:** [modules/goals/plugin.py:L157](../modules/goals/plugin.py#L157) (Handler: `handle_create`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `create_goal` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run create goal", "Can you trigger create goal?", "How do I use create goal?"
- **Parameters Schema:**
*None*

---

#### <a name="end_focus_session"></a> `end_focus_session`
**Description:** End the active focus session early.

- **Execution File:** [modules/focus_session/plugin.py:L85](../modules/focus_session/plugin.py#L85) (Handler: `handle_end`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `end_focus_session` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run end focus session", "Can you trigger end focus session?", "How do I use end focus session?"
- **Parameters Schema:**
*None*

---

#### <a name="focus_session_status"></a> `focus_session_status`
**Description:** Report whether a focus session is active and how much time is left.

- **Execution File:** [modules/focus_session/plugin.py:L92](../modules/focus_session/plugin.py#L92) (Handler: `handle_status`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `focus_session_status` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run focus session status", "Can you trigger focus session status?", "How do I use focus session status?"
- **Parameters Schema:**
*None*

---

#### <a name="get_date"></a> `get_date`
**Description:** Tell the user today's date.

- **Execution File:** [modules/task_manager/plugin.py:L235](../modules/task_manager/plugin.py#L235) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_date` (Direct intent/routing), "what day is it" (Voice/Text Alias), "tell me the date" (Voice/Text Alias), "today's date" (Voice/Text Alias), "current date" (Voice/Text Alias), `r"\b(?:today(?:'s)? date|what day is it|current date|tell me(?: the)? date)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Today's date", "What day is it?", "What is the date?"
- **Parameters Schema:**
*None*

---

#### <a name="get_goal_detail"></a> `get_goal_detail`
**Description:** Get detailed information about a specific goal including progress history.

- **Execution File:** [modules/goals/plugin.py:L226](../modules/goals/plugin.py#L226) (Handler: `handle_detail`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_goal_detail` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get goal detail", "Can you trigger get goal detail?", "How do I use get goal detail?"
- **Parameters Schema:**
*None*

---

#### <a name="get_time"></a> `get_time`
**Description:** Tell the user the current local time.

- **Execution File:** [modules/task_manager/plugin.py:L229](../modules/task_manager/plugin.py#L229) (Handler: `<lambda>`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `get_time` (Direct intent/routing), "what time is it" (Voice/Text Alias), "tell me the time" (Voice/Text Alias), "current time" (Voice/Text Alias), `r"\b(?:what(?:'s| is)? the time|what time is it|current time|tell me(?: the)? time)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "What time is it?", "Current time", "Tell me the time"
- **Parameters Schema:**
*None*

---

#### <a name="list_goals"></a> `list_goals`
**Description:** List active goals, optionally filtered by level or health.

- **Execution File:** [modules/goals/plugin.py:L202](../modules/goals/plugin.py#L202) (Handler: `handle_list`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `list_goals` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run list goals", "Can you trigger list goals?", "How do I use list goals?"
- **Parameters Schema:**
*None*

---

#### <a name="list_reminders"></a> `list_reminders`
**Description:** Read upcoming reminders with their scheduled date and time.

- **Execution File:** [modules/task_manager/plugin.py:L1087](../modules/task_manager/plugin.py#L1087) (Handler: `handle_list_reminders`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `list_reminders` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run list reminders", "Can you trigger list reminders?", "How do I use list reminders?"
- **Parameters Schema:**
*None*

---

#### <a name="list_triggers"></a> `list_triggers`
**Description:** List all currently active triggers.

- **Execution File:** [modules/triggers/plugin.py:L117](../modules/triggers/plugin.py#L117) (Handler: `handle_list`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `list_triggers` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run list triggers", "Can you trigger list triggers?", "How do I use list triggers?"
- **Parameters Schema:**
*None*

---

#### <a name="pause_goal"></a> `pause_goal`
**Description:** Pause a goal temporarily.

- **Execution File:** [modules/goals/plugin.py:L252](../modules/goals/plugin.py#L252) (Handler: `handle_pause`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `pause_goal` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run pause goal", "Can you trigger pause goal?", "How do I use pause goal?"
- **Parameters Schema:**
*None*

---

#### <a name="read_notes"></a> `read_notes`
**Description:** Read back the most recent saved notes.

- **Execution File:** [modules/task_manager/plugin.py:L638](../modules/task_manager/plugin.py#L638) (Handler: `handle_read_notes`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `read_notes` (Direct intent/routing), "read notes" (Voice/Text Alias), "show notes" (Voice/Text Alias), "my notes" (Voice/Text Alias), `r"\b(?:read|show|list)\s+(?:my\s+)?notes\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Read my notes", "Show notes", "List notes"
- **Parameters Schema:**
*None*

---

#### <a name="remove_trigger"></a> `remove_trigger`
**Description:** Stop and remove an active trigger.

- **Execution File:** [modules/triggers/plugin.py:L109](../modules/triggers/plugin.py#L109) (Handler: `handle_remove`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `critical` | Latency: `interactive`
- **Trigger Commands / Invocation:** `remove_trigger` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run remove trigger", "Can you trigger remove trigger?", "How do I use remove trigger?"
- **Parameters Schema:**
*None*

---

#### <a name="save_note"></a> `save_note`
**Description:** Save a quick note or piece of text for later retrieval.

- **Execution File:** [modules/task_manager/plugin.py:L597](../modules/task_manager/plugin.py#L597) (Handler: `handle_save_note`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `save_note` (Direct intent/routing), "remember this" (Voice/Text Alias), "note down" (Voice/Text Alias), "save note" (Voice/Text Alias), `r"\b(?:save note|note down|remember this|remember that)\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Save note write down ideas", "Remember this"
- **Parameters Schema:**
*None*

---

#### <a name="set_reminder"></a> `set_reminder`
**Description:** Set a personal time-based reminder that FRIDAY will announce at a future time. Use for 'remind me to [action]' phrases — e.g. 'remind me to call John at 3pm', 'remind me in 10 minutes to take a break'. Not for structured meetings or appointments with explicit event titles.

- **Execution File:** [modules/task_manager/plugin.py:L243](../modules/task_manager/plugin.py#L243) (Handler: `handle_set_reminder`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `set_reminder` (Direct intent/routing), "set reminder" (Voice/Text Alias), "remind me" (Voice/Text Alias), `r"\bremind me\b"` (Regex Pattern), `r"\bset (?:a )?reminder\b"` (Regex Pattern)
- **Example Trigger Queries (Natural Language):** "Remind me to buy milk", "Set a reminder"
- **Parameters Schema:**
*None*

---

#### <a name="start_focus_session"></a> `start_focus_session`
**Description:** Start a focus / pomodoro session. Mutes notifications, pauses media, and announces when the session ends. Default 25 minutes.

- **Execution File:** [modules/focus_session/plugin.py:L76](../modules/focus_session/plugin.py#L76) (Handler: `handle_start`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `start_focus_session` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run start focus session", "Can you trigger start focus session?", "How do I use start focus session?"
- **Parameters Schema:**
*None*

---

#### <a name="update_goal"></a> `update_goal`
**Description:** Advance a goal's score (0.0-1.0) or update its status.

- **Execution File:** [modules/goals/plugin.py:L180](../modules/goals/plugin.py#L180) (Handler: `handle_update`)
- **Metadata:** Connectivity: `local` | Permission: `always_ok` | Side-Effect: `read` | Latency: `interactive`
- **Trigger Commands / Invocation:** `update_goal` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run update goal", "Can you trigger update goal?", "How do I use update goal?"
- **Parameters Schema:**
*None*

---

### Web & Browser Automation

#### <a name="browser_media_control"></a> `browser_media_control`
**Description:** Control active browser playback such as pause, resume, or next.

- **Execution File:** [modules/browser_automation/plugin.py:L180](../modules/browser_automation/plugin.py#L180) (Handler: `handle_browser_media_control`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `browser_media_control` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run browser media control", "Can you trigger browser media control?", "How do I use browser media control?"
- **Parameters Schema:**
*None*

---

#### <a name="open_browser_url"></a> `open_browser_url`
**Description:** Open a website in a controlled browser session.

- **Execution File:** [modules/browser_automation/plugin.py:L109](../modules/browser_automation/plugin.py#L109) (Handler: `handle_open_browser_url`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `open_browser_url` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run open browser url", "Can you trigger open browser url?", "How do I use open browser url?"
- **Parameters Schema:**
*None*

---

#### <a name="play_youtube"></a> `play_youtube`
**Description:** Search for a video on YouTube and start playback in a controlled browser session.

- **Execution File:** [modules/browser_automation/plugin.py:L127](../modules/browser_automation/plugin.py#L127) (Handler: `handle_play_youtube`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `play_youtube` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run play youtube", "Can you trigger play youtube?", "How do I use play youtube?"
- **Parameters Schema:**
*None*

---

#### <a name="play_youtube_music"></a> `play_youtube_music`
**Description:** Search for a song on YouTube Music and start playback in a controlled browser session.

- **Execution File:** [modules/browser_automation/plugin.py:L145](../modules/browser_automation/plugin.py#L145) (Handler: `handle_play_youtube_music`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `play_youtube_music` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run play youtube music", "Can you trigger play youtube music?", "How do I use play youtube music?"
- **Parameters Schema:**
*None*

---

#### <a name="search_google"></a> `search_google`
**Description:** Search Google for the given query and open the results in a new browser tab.

- **Execution File:** [modules/browser_automation/plugin.py:L163](../modules/browser_automation/plugin.py#L163) (Handler: `handle_search_google`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `write` | Latency: `interactive`
- **Trigger Commands / Invocation:** `search_google` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run search google", "Can you trigger search google?", "How do I use search google?"
- **Parameters Schema:**
*None*

---

### Workspace & File Management

#### <a name="cancel_calendar_event"></a> `cancel_calendar_event`
**Description:** Cancel or delete a Google Calendar event by title, time, or 'the next one'.

- **Execution File:** [modules/workspace_agent/extension.py:L425](../modules/workspace_agent/extension.py#L425) (Handler: `_handle_cancel_event`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `critical` | Latency: `slow`
- **Trigger Commands / Invocation:** `cancel_calendar_event` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run cancel calendar event", "Can you trigger cancel calendar event?", "How do I use cancel calendar event?"
- **Parameters Schema:**
*None*

---

#### <a name="check_unread_emails"></a> `check_unread_emails`
**Description:** List unread emails in the user's Gmail inbox (sender, subject, date).

- **Execution File:** [modules/workspace_agent/extension.py:L236](../modules/workspace_agent/extension.py#L236) (Handler: `_handle_check_unread_emails`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `check_unread_emails` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run check unread emails", "Can you trigger check unread emails?", "How do I use check unread emails?"
- **Parameters Schema:**
*None*

---

#### <a name="create_calendar_event"></a> `create_calendar_event`
**Description:** Create a new Google Calendar event.

- **Execution File:** [modules/workspace_agent/extension.py:L329](../modules/workspace_agent/extension.py#L329) (Handler: `_handle_create_event`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `critical` | Latency: `slow`
- **Trigger Commands / Invocation:** `create_calendar_event` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run create calendar event", "Can you trigger create calendar event?", "How do I use create calendar event?"
- **Parameters Schema:**
*None*

---

#### <a name="daily_briefing"></a> `daily_briefing`
**Description:** Morning briefing: unread email summary + today's calendar.

- **Execution File:** [modules/workspace_agent/extension.py:L814](../modules/workspace_agent/extension.py#L814) (Handler: `_handle_daily_briefing`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `daily_briefing` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run daily briefing", "Can you trigger daily briefing?", "How do I use daily briefing?"
- **Parameters Schema:**
*None*

---

#### <a name="get_calendar_agenda"></a> `get_calendar_agenda`
**Description:** Get upcoming calendar events for the next N days.

- **Execution File:** [modules/workspace_agent/extension.py:L306](../modules/workspace_agent/extension.py#L306) (Handler: `_handle_calendar_agenda`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_calendar_agenda` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get calendar agenda", "Can you trigger get calendar agenda?", "How do I use get calendar agenda?"
- **Parameters Schema:**
*None*

---

#### <a name="get_calendar_today"></a> `get_calendar_today`
**Description:** Get today's Google Calendar events.

- **Execution File:** [modules/workspace_agent/extension.py:L292](../modules/workspace_agent/extension.py#L292) (Handler: `_handle_calendar_today`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_calendar_today` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get calendar today", "Can you trigger get calendar today?", "How do I use get calendar today?"
- **Parameters Schema:**
*None*

---

#### <a name="get_calendar_week"></a> `get_calendar_week`
**Description:** Get this week's Google Calendar events.

- **Execution File:** [modules/workspace_agent/extension.py:L299](../modules/workspace_agent/extension.py#L299) (Handler: `_handle_calendar_week`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `get_calendar_week` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run get calendar week", "Can you trigger get calendar week?", "How do I use get calendar week?"
- **Parameters Schema:**
*None*

---

#### <a name="read_email"></a> `read_email`
**Description:** Read the full body of a specific Gmail message by id.

- **Execution File:** [modules/workspace_agent/extension.py:L278](../modules/workspace_agent/extension.py#L278) (Handler: `_handle_read_email`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `read_email` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run read email", "Can you trigger read email?", "How do I use read email?"
- **Parameters Schema:**
*None*

---

#### <a name="read_latest_email"></a> `read_latest_email`
**Description:** Read the body of the most recent unread email in Gmail.

- **Execution File:** [modules/workspace_agent/extension.py:L257](../modules/workspace_agent/extension.py#L257) (Handler: `_handle_read_latest_email`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `read_latest_email` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run read latest email", "Can you trigger read latest email?", "How do I use read latest email?"
- **Parameters Schema:**
*None*

---

#### <a name="search_drive"></a> `search_drive`
**Description:** Search Google Drive for files by name or content.

- **Execution File:** [modules/workspace_agent/extension.py:L675](../modules/workspace_agent/extension.py#L675) (Handler: `_handle_search_drive`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `search_drive` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run search drive", "Can you trigger search drive?", "How do I use search drive?"
- **Parameters Schema:**
*None*

---

#### <a name="summarize_inbox"></a> `summarize_inbox`
**Description:** Summarize all unread Gmail emails into a single spoken paragraph — sender, topic, and key details from every message.

- **Execution File:** [modules/workspace_agent/extension.py:L710](../modules/workspace_agent/extension.py#L710) (Handler: `_handle_summarize_inbox`)
- **Metadata:** Connectivity: `online` | Permission: `always_ok` | Side-Effect: `read` | Latency: `slow`
- **Trigger Commands / Invocation:** `summarize_inbox` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run summarize inbox", "Can you trigger summarize inbox?", "How do I use summarize inbox?"
- **Parameters Schema:**
*None*

---

#### <a name="update_calendar_event"></a> `update_calendar_event`
**Description:** Modify an existing Google Calendar event — rename it, reschedule it, or update its description. Identifies the event by title, time, or 'the next one'.

- **Execution File:** [modules/workspace_agent/extension.py:L383](../modules/workspace_agent/extension.py#L383) (Handler: `_handle_update_event`)
- **Metadata:** Connectivity: `online` | Permission: `ask_first` | Side-Effect: `critical` | Latency: `slow`
- **Trigger Commands / Invocation:** `update_calendar_event` (Direct intent/routing)
- **Example Trigger Queries (Natural Language):** "Please run update calendar event", "Can you trigger update calendar event?", "How do I use update calendar event?"
- **Parameters Schema:**
*None*

---