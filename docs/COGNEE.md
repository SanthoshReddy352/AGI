# Cognee Enhanced Memory (optional)

Namma Agent can use **[Cognee](https://www.cognee.ai)** — an open-source AI memory
engine — to add **semantic + knowledge-graph memory** on top of the built-in
SQLite/FTS5 store. It's **opt-in** and **non-destructive**: with it off, Namma
behaves exactly as before.

> Built for the WeMakeDevs × Cognee hackathon. Full design & status live in
> [`Cognee_Implementation.md`](../Cognee_Implementation.md).

---

## How it integrates (important)

Cognee runs **fully containerized** and Namma talks to it through its built-in
**MCP client**. Consequences:

- **No new Python dependencies.** Nothing is added to
  [`namma_agent/requirements.txt`](../namma_agent/requirements.txt). Cognee's heavy
  native stack lives inside its Docker image, never in Namma's venv. (This also
  sidesteps Python 3.14 wheel issues.)
- **Cannot degrade Namma.** It's isolated in a container, opt-in, and falls back to
  SQLite/FTS5 if unavailable.
- **The only prerequisite is Docker.**

```
Namma Agent (your venv)                     Docker
  └─ MCP client ──(docker run -i, stdio)──▶ cognee/cognee-mcp  (remember/recall/forget…)
                                              └─ HTTP ─▶ ollama  (LLM + embeddings, free/local)
                                              └─ files ─▶ LanceDB (vectors) · Kuzu (graph) · SQLite
```

**Models (fully local / free):** extraction LLM `llama3.2:3b` and embeddings
`nomic-embed-text`, both served by a local **Ollama** container. No API keys, no
cloud calls — the strongest "Best Use of Open Source" story.

---

## Prerequisites

- **Docker Desktop** (running). Everything else is pulled by the setup script.
- ~30 GB free disk (the Cognee MCP image is large; models add ~2.3 GB).

No OpenAI/Groq/Google key is required for the local setup.

---

## Setup (one command)

From the project root:

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_cognee.ps1
```

**Linux / macOS / Git-Bash:**
```bash
bash scripts/setup_cognee.sh
```

This will: start the Ollama container ([`docker-compose.cognee.yml`](../docker-compose.cognee.yml)),
pull `nomic-embed-text` + `llama3.2:3b`, pull `cognee/cognee-mcp:main`, and create
`.env.cognee` from the example.

<details>
<summary>Manual steps (what the script does)</summary>

```bash
docker compose -f docker-compose.cognee.yml up -d
docker exec namma-cognee-ollama ollama pull nomic-embed-text
docker exec namma-cognee-ollama ollama pull llama3.2:3b
docker pull cognee/cognee-mcp:main
cp .env.cognee.example .env.cognee
```
</details>

---

## Register Cognee in Namma

1. Open Namma → **Settings → MCP → Config**.
2. Paste (adjust the `--env-file` path to your OS; on Windows it's `D:/AGI/.env.cognee`):

```json
{
  "servers": [
    {
      "name": "cognee",
      "command": ["docker","run","-i","--rm","--network","agi_default",
                  "--env-file","D:/AGI/.env.cognee",
                  "-v","cognee-data:/cognee-data","cognee/cognee-mcp:main"],
      "enabled": true,
      "connect_timeout": 90,
      "call_timeout": 900
    }
  ]
}
```

3. Click **Save & reconnect**.
4. Go to **Settings → MCP → Servers** — you should see `cognee` connected with its
   tools (`remember`, `recall`, `forget`, …), each toggleable.

`connect_timeout`/`call_timeout` matter: Cognee cold-starts in ~20 s and graph
builds (`cognify`) can take minutes on CPU — the defaults (60 s / 120 s) are too
short, so the entry overrides them.

---

## Using it

Once connected, the assistant can call:

- **`mcp_cognee_remember`** — store knowledge. *Without* a `session_id` it runs the
  full graph build (`cognify`); *with* a `session_id` it's a fast session-cache
  write (no LLM).
- **`mcp_cognee_recall`** — semantic / graph search (finds things by meaning, not
  just keywords).
- **`mcp_cognee_forget`** — delete a dataset or everything.

> **Performance note:** on a CPU-only machine, a full `cognify` is slow
> (minutes per document). For a smooth demo, **pre-build memory ahead of time** and
> show fast `recall` live. Use session memory for fast interactive writes.

---

## Troubleshooting (hard-won)

| Symptom | Cause / Fix |
|---|---|
| `server closed the connection` on connect | Cognee cold start (~20 s) > default 15 s timeout. Set `connect_timeout: 90` in the MCP entry (done above). |
| `None is not a local folder ... huggingface.co/models` | Ollama embedding engine needs a tokenizer name. Set `HUGGINGFACE_TOKENIZER=nomic-ai/nomic-embed-text-v1.5` (in `.env.cognee`). |
| `Embedding connection test timed out after 30s` | False failure; real calls work. Set `COGNEE_SKIP_CONNECTION_TEST=true` (in `.env.cognee`). |
| Embedding/LLM calls can't reach Ollama | Don't use `host.docker.internal`. Run cognee on `--network agi_default` and use the service name `http://namma-cognee-ollama:11434` (already configured). |
| `cognify` runs ~5 min then `status=errored`, "404 page not found" in logs | **LLM endpoint missing `/v1`.** cognee POSTs to `{LLM_ENDPOINT}/chat/completions`, so the endpoint must end in `/v1` (e.g. `http://namma-cognee-ollama:11434/v1`). The ~288s was instructor retry-backoff, not compute. |
| `cognify` errors, "405 Method Not Allowed" / "Attempt to decode JSON" on embeddings | **Embedding endpoint must be the full `/api/embed` URL** — cognee POSTs the payload directly to `EMBEDDING_ENDPOINT` (no path appending). Bare `…:11434` hits Ollama's root → 405. |
| `cognify` errors, "validation error for SummarizedContent" | The **extraction model is too weak** to produce cognee's structured JSON. `llama3.2:3b` fails; use Groq `llama-3.3-70b-versatile` (fast) or a local `qwen2.5:7b`+. |
| `cognify` slow/errored with Groq free tier | Possible **rate limits** on bursts. Fine for pre-building small docs; for live use keep extraction to short inputs or upgrade tier. |
| Memory doesn't persist across restarts | **Fixed.** Set `DATA_ROOT_DIRECTORY` / `SYSTEM_ROOT_DIRECTORY` / `CACHE_ROOT_DIRECTORY` to paths under the mounted `cognee-data` volume (in `.env.cognee`), and pre-create those dirs with write perms (the setup script does this — the volume is root-owned, Cognee runs non-root). Verified surviving container restarts. |
| `PermissionError: Permission denied` creating `/cognee-data/...` | The volume is root-owned and Cognee runs non-root. Run: `docker run --rm -v cognee-data:/cognee-data busybox sh -c "mkdir -p /cognee-data/{system,data,cache} && chmod -R 777 /cognee-data"` (the setup script does this). |

---

## Cloud track (Cognee Cloud)

For the "Best Use of Cognee Cloud" submission, point Namma at managed Cognee Cloud
instead of the local stack — **same Namma code, same Memory tab**, only the single
`cognee` MCP server entry differs. The cloud owns its own DB + embeddings, so no
Ollama / Kuzu / volume is involved.

**One-click in the UI (recommended):** Settings → MCP → **Cognee → Backend** →
choose **Cognee Cloud**, paste your instance URL (`https://<instance>.cognee.ai`) +
API key, and click **Connect to Cognee Cloud**. Namma writes the key to the
gitignored `.env.cognee.cloud` (never into `config.local.yaml`) and registers:

```
docker run -i --rm --env-file .env.cognee.cloud \
  cognee/cognee-mcp:main --serve-url https://<instance>.cognee.ai
```

`cognee-mcp` calls `cognee.serve()` at startup, so **all ops route to the cloud**.
The container is named `namma_cognee` so switching backends force-removes the old
one first (no orphaned container holding the Kuzu lock) — **switching no longer needs
an app restart**. Switch back any time with **Self-hosted** in the same panel.

**The knowledge-graph view works on cloud too.** In serve mode the container's
`visualize_graph_ui` can't reach a local DB, so Namma instead syncs the graph from
the Cognee Cloud REST API (`GET /api/v1/datasets/{id}/graph`, `X-Api-Key` auth) and
renders the same Obsidian-style canvas. Self-hosted keeps using `visualize_graph_ui`.

**Credentials:** sign up at platform.cognee.ai (dev plan code `COGNEE-35`) for the
instance URL + API key. The key lives only in `.env.cognee.cloud` (gitignored).
