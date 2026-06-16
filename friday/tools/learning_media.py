"""Learning-Room media tools: Mermaid diagrams, online images, HTML simulations.

Each writes a file under ``data/media/`` (served read-only at ``/api/media``) and
returns markdown that renders inline in the chat/Learning Room. Every file is a
downloadable artifact; when produced inside a learning topic it's also recorded
against that topic for the insights view.

Degrade gracefully: a missing ``mmdc`` or a failed network fetch returns a clear
error, never a crash.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from friday.core.interactive import record_artifact
from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

_MEDIA = Path("data/media")
_TIMEOUT = 12


def _media_dir(kind: str) -> Path:
    d = _MEDIA / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mmdc() -> str | None:
    return shutil.which("mmdc") or (
        str(Path.home() / ".npm-global/bin/mmdc")
        if (Path.home() / ".npm-global/bin/mmdc").exists() else None)


def _locate_output(out_path: Path) -> Path | None:
    """The file mmdc actually produced: the requested path, or the `-1`-suffixed
    variant some mermaid-cli versions emit. None when nothing was written."""
    if out_path.exists():
        return out_path
    suffixed = out_path.with_name(f"{out_path.stem}-1{out_path.suffix}")
    return suffixed if suffixed.exists() else None


#: Returned with every render failure: the model must degrade honestly, never
#: invent an /api/media/... link — a fabricated URL renders as a broken image.
_NO_FAKE_LINKS = (" Do NOT write an image markdown link yourself — image links may only "
                  "come from successful tool results. Either retry once with simpler "
                  "mermaid (less text, basic 'graph TD') or continue the lesson without "
                  "this diagram.")


def _render_diagram(args: dict) -> ToolResult:
    code = (args.get("mermaid") or "").strip()
    title = (args.get("title") or "Diagram").strip()
    if not code:
        return ToolResult(ok=False, content="", error="'mermaid' diagram code is required")
    mmdc = _mmdc()
    if not mmdc:
        return ToolResult(ok=False, content="",
                          error="Diagrams need mermaid-cli. Install: npm i -g @mermaid-js/mermaid-cli"
                                + _NO_FAKE_LINKS)

    out_dir = _media_dir("diagrams")
    name = f"{uuid.uuid4().hex}.png"
    out_path = out_dir / name
    produced: Path | None = None
    last_err = ""
    # mmdc/puppeteer fails transiently under load — one retry absorbs most of it.
    for attempt in (1, 2):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "d.mmd"
            src.write_text(code, encoding="utf-8")
            cfg = Path(tmp) / "pp.json"
            cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
            env = dict(os.environ)
            # Use the system Chromium for puppeteer if mmdc's bundled one is absent.
            for cand in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
                if Path(cand).exists():
                    env.setdefault("PUPPETEER_EXECUTABLE_PATH", cand)
                    break
            # 4× scale on a 2048×1536 canvas for crisp, downloadable artifacts.
            cmd = [mmdc, "-i", str(src), "-o", str(out_path),
                   "-w", "2048", "-H", "1536", "-s", "4", "-b", "white", "-p", str(cfg)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                                      env=env, encoding="utf-8", errors="replace")
                last_err = (proc.stderr or "").strip()[:200]
            except subprocess.TimeoutExpired:
                last_err = "diagram render timed out"
                continue
            produced = _locate_output(out_path)
            if proc.returncode == 0 and produced is not None:
                break
            produced = None
            logger.warning("[learning_media] mmdc attempt %d failed: %s", attempt, last_err[:300])
    if produced is None:
        return ToolResult(ok=False, content="",
                          error=f"diagram render failed: {last_err}." + _NO_FAKE_LINKS)
    if produced != out_path:  # normalize the `-1`-suffixed name to the URL we return
        produced.rename(out_path)

    url = f"/api/media/diagrams/{name}"
    record_artifact("diagram", url, title)
    content = f"![{title}]({url})\n\n*{title}* · [⬇ Download diagram]({url})"
    return ToolResult(ok=True, content=content, data={"url": url, "kind": "diagram"})


def _fetch_image(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="'query' is required")
    api = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": 1, "license_type": "all"})
    req = urllib.request.Request(api, headers={"User-Agent": "FRIDAY-LearningRoom/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"image search failed: {exc}")
    results = payload.get("results") or []
    if not results:
        return ToolResult(ok=True, content=f"No images found for “{query}”.")
    hit = results[0]
    img_url = hit.get("url")
    creator = hit.get("creator") or "unknown"
    lic = (hit.get("license") or "").upper()
    try:
        ireq = urllib.request.Request(img_url, headers={"User-Agent": "FRIDAY-LearningRoom/2.0"})
        with urllib.request.urlopen(ireq, timeout=_TIMEOUT) as r:
            data = r.read()
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
                   "image/gif": "gif"}.get(r.headers.get("Content-Type", "").split(";")[0], "jpg")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"image download failed: {exc}")
    name = f"{uuid.uuid4().hex}.{ext}"
    (_media_dir("images") / name).write_bytes(data)
    url = f"/api/media/images/{name}"
    record_artifact("image", url, hit.get("title") or query)
    caption = f"*{hit.get('title') or query}* — by {creator}" + (f" ({lic})" if lic else "")
    content = f"![{query}]({url})\n\n{caption} · [⬇ Download]({url})"
    return ToolResult(ok=True, content=content, data={"url": url, "kind": "image"})


def _render_simulation(args: dict) -> ToolResult:
    html = args.get("html") or ""
    title = (args.get("title") or "Interactive simulation").strip()
    if "<" not in html:
        return ToolResult(ok=False, content="", error="'html' (a self-contained HTML document) is required")
    name = f"{uuid.uuid4().hex}.html"
    (_media_dir("sims") / name).write_text(html, encoding="utf-8")
    url = f"/api/media/sims/{name}"
    record_artifact("simulation", url, title)
    # The Learning Room renders /api/media/sims/* links as a sandboxed iframe card.
    content = f"[▶ Open interactive simulation — {title}]({url})"
    return ToolResult(ok=True, content=content, data={"url": url, "kind": "simulation"})


def register(registry: ToolRegistry) -> None:
    registry.register(
        "render_diagram",
        "Render a Mermaid diagram to a crisp downloadable image (4× / 2048×1536) and "
        "show it inline. Use for structures, flows, timelines, relationships.",
        {
            "type": "object",
            "properties": {
                "mermaid": {"type": "string", "description": "Mermaid diagram source (e.g. 'graph TD; A-->B')"},
                "title": {"type": "string", "description": "short caption"},
            },
            "required": ["mermaid"],
        },
        _render_diagram,
    )
    registry.register(
        "fetch_image",
        "Find a real, license-clean photo/illustration online (Openverse) and show it "
        "inline as a downloadable artifact. Use to build visual intuition.",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "what to picture, e.g. 'water cycle'"}},
            "required": ["query"],
        },
        _fetch_image,
    )
    registry.register(
        "render_simulation",
        "Save a self-contained interactive HTML/JS simulation (one full <html> document, "
        "all CSS/JS inline) as a downloadable artifact rendered in a sandboxed frame. Use "
        "when motion or interaction teaches better than text.",
        {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "a complete self-contained HTML document"},
                "title": {"type": "string", "description": "short title"},
            },
            "required": ["html"],
        },
        _render_simulation,
    )
