"""SourcesPlugin — registers the 7 free Python-portable research source tools.

Each backed by a small module in this package:

  - wikipedia.py        → wikipedia_summary, wikipedia_search
  - arxiv.py            → arxiv_search
  - hackernews.py       → hackernews_top, hackernews_search
  - pubmed.py           → pubmed_search
  - newspaper.py        → newspaper_extract (trafilatura-backed cleaner)
  - yfinance.py         → yfinance_quote   (lazy import; optional dep)
  - pdf_text.py         → pdf_text_search  (lazy import; optional dep)

Origin: ported from the GetStream ai-agent-tools-catalog after auditing
its 84 entries — most were SaaS-paywalled or already-implemented; these
7 were genuinely free + pure-Python + non-duplicative.

The plugin only registers capabilities — the heavy lifting lives in
each tool's module so they're independently testable.
"""
from __future__ import annotations

from core.plugin_manager import FridayPlugin
from core.logger import logger

from . import wikipedia as _wikipedia
from . import arxiv as _arxiv
from . import hackernews as _hackernews
from . import pubmed as _pubmed
from . import newspaper as _newspaper
from . import yfinance as _yfinance
from . import pdf_text as _pdf


class SourcesPlugin(FridayPlugin):
    def __init__(self, app):
        super().__init__(app)
        self.name = "Sources"
        self.on_load()

    def on_load(self):
        register = self.app.register_capability

        register(
            {
                "name": "wikipedia_summary",
                "description": "Fetch the Wikipedia REST summary for a topic.",
                "parameters": {"query": "string — topic to look up"},
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_wikipedia.handle_wikipedia_summary),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "wikipedia_search",
                "description": "List Wikipedia article titles matching a query.",
                "parameters": {
                    "query": "string — search terms",
                    "limit": "int — max titles (default 5)",
                },
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_wikipedia.handle_wikipedia_search),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "arxiv_search",
                "description": "Search arXiv for papers matching a query.",
                "parameters": {
                    "query": "string — search query",
                    "max_results": "int — max papers (default 5)",
                },
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_arxiv.handle_arxiv_search),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "hackernews_top",
                "description": "List top stories on Hacker News right now.",
                "parameters": {"limit": "int — max stories (default 10)"},
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_hackernews.handle_hackernews_top),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "hackernews_search",
                "description": "Search Hacker News stories via Algolia.",
                "parameters": {
                    "query": "string — search terms",
                    "limit": "int — max stories (default 8)",
                },
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_hackernews.handle_hackernews_search),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "pubmed_search",
                "description": "Search PubMed for medical/biomedical literature.",
                "parameters": {
                    "query": "string — search query",
                    "max_results": "int — max papers (default 5)",
                },
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_pubmed.handle_pubmed_search),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "newspaper_extract",
                "description": (
                    "Fetch a URL and return ONLY the main article body "
                    "(nav / footer / ads stripped, via trafilatura)."
                ),
                "parameters": {"url": "string — URL to extract"},
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_newspaper.handle_newspaper_extract),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "yfinance_quote",
                "description": "Look up the latest quote / company info for a stock ticker.",
                "parameters": {"ticker": "string — stock ticker symbol (e.g. MSFT)"},
                "connectivity": "online",
                "permission_mode": "online_permission",
            },
            _wrap(_yfinance.handle_yfinance_quote),
            metadata={"side_effect_level": "read"},
        )
        register(
            {
                "name": "pdf_text_search",
                "description": "Search the contents of local PDF files for a query.",
                "parameters": {
                    "query": "string — text to search for",
                    "folder": "string — optional folder to scan (defaults to ~/Documents + ~/Downloads)",
                    "max_results": "int — max matches (default 5)",
                },
                "connectivity": "local",
                "permission_mode": "always_ok",
            },
            _wrap(_pdf.handle_pdf_text_search),
            metadata={"side_effect_level": "read"},
        )

        logger.info("[sources] Plugin loaded — 9 source-tool capabilities registered.")


def _wrap(handler):
    """Capability registry expects `(raw_text, args) -> str`."""
    return lambda raw_text, args: handler(raw_text or "", args or {})
