"""Seed Cognee with a coherent set of demo memories so the knowledge graph and the
recall demos look great and are *repeatable*.

It drives the **running Namma app** over HTTP (`/api/memory/*`), so it uses the app's
existing Cognee connection — no second container, no Kuzu-lock clash — and works the
same whether the app is on the self-hosted or the Cognee Cloud backend.

Usage (start the app first: `python -m namma_agent --server`):
    python scripts/seed_demo_memory.py            # add the demo facts (cognify)
    python scripts/seed_demo_memory.py --reset    # FORGET everything first, then seed
    python scripts/seed_demo_memory.py --url http://127.0.0.1:8000

The facts tell one story (a person, their projects, the tools they use, the people
they work with, the event) so the graph has rich, connected entities — and so a
reworded recall ("which engine do I use to store relationships?") visibly beats
keyword search.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

# One connected story → a graph worth showing. Edit freely for your own demo.
FACTS = [
    "I'm Santhosh, an indie developer, and I'm building Namma Agent — a cloud-only "
    "personal AI assistant.",
    "Namma Agent's brain is a Claude model from Anthropic, called over the API.",
    "My favourite programming language is Python; I use it for everything in Namma Agent.",
    "I'm integrating Cognee into Namma Agent to give it a semantic, knowledge-graph memory.",
    "Cognee stores memory across three engines: a vector store, a graph store, and a "
    "relational store.",
    "I'm presenting Namma Agent at the WeMakeDevs x Cognee hackathon.",
    "I prefer Kuzu as the graph database for the self-hosted setup.",
    "My teammate Aria handles the demo narration and the voice features.",
    "I like teaching through the Learning Room, where Namma draws diagrams for every concept.",
]


def post(base: str, path: str, body: dict, timeout: int = 900) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get(base: str, path: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    args = sys.argv[1:]
    reset = "--reset" in args
    base = "http://127.0.0.1:8000"
    if "--url" in args:
        base = args[args.index("--url") + 1].rstrip("/")

    try:
        status = get(base, "/api/memory/status")
    except Exception as exc:  # noqa: BLE001
        print(f"Can't reach Namma at {base} — start it first "
              f"(`python -m namma_agent --server`). ({exc})")
        return 1
    if not status.get("connected"):
        print("Namma is up but Cognee isn't connected. Settings → MCP → Cognee → "
              "Register / Reconnect, then re-run.")
        return 1
    print(f"Connected to Namma at {base} (Cognee online).")

    if reset:
        print("Resetting memory (forget everything)…")
        print("  ", post(base, "/api/memory/forget", {"everything": True}, timeout=120))

    for i, fact in enumerate(FACTS, 1):
        t0 = time.time()
        out = post(base, "/api/memory/remember", {"text": fact, "permanent": True})
        ok = out.get("ok")
        msg = (out.get("content") or out.get("error") or "").splitlines()
        print(f"[{i}/{len(FACTS)}] ({time.time()-t0:.0f}s) ok={ok} {msg[0][:90] if msg else ''}")

    g = get(base, "/api/memory/graph", timeout=180)
    print(f"\nGraph now: {len(g.get('nodes', []))} entities · {len(g.get('edges', []))} links.")
    print("Open the Memory tab → it should be rich and connected.")
    print("Try Ask my memory: 'which engine do I use to store relationships?' / 'who do I work with?'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
