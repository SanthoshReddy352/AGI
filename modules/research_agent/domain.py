"""Domain-of-research classifier for deep-mode dispatch.

Returns a `Domains` namedtuple-ish dict telling deep.py which source
plugins to invoke alongside the default Wikipedia anchor + web search.

This is intentionally regex-based (cheap, deterministic, debuggable).
A small chat model could classify too, but adding an LLM call inside
the planner would push the deep-mode wall-clock past 120s on top of
the synthesis call we already make.

Detected domains (any combination):
  - "academic"   → +arxiv_search (tech / ML / physics / math papers)
  - "medical"    → +pubmed_search
  - "finance"    → +yfinance_quote (a ticker is also extracted)
  - "tech_buzz"  → +hackernews_search (current discussion / opinion)
  - "general"    → no extra sources (still uses wiki + web)
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Domains:
    academic: bool = False
    medical: bool = False
    finance: bool = False
    tech_buzz: bool = False
    ticker: str = ""        # populated when finance is True

    def active_sources(self) -> list[str]:
        """Return canonical source-tool names this topic should use, in
        priority order. The writer renders them in this order, too."""
        out = ["wikipedia_summary", "web_search"]
        if self.academic:
            out.append("arxiv_search")
        if self.medical:
            out.append("pubmed_search")
        if self.tech_buzz:
            out.append("hackernews_search")
        if self.finance:
            out.append("yfinance_quote")
        return out


# ---------------------------------------------------------------------------
# Pattern catalog — tuned to fire on the obvious keywords without
# false-positives on common chatter ("research paper" is academic;
# "papers for my homework" should NOT be).
# ---------------------------------------------------------------------------

_ACADEMIC_RE = re.compile(
    r"\b("
    r"arxiv|paper(?:s)?|preprint|literature\s+review|"
    r"transformer(?:s)?|llm(?:s)?|attention\s+head|self.attention|"
    r"scaling\s+law(?:s)?|emergent\s+(?:ability|abilities)|"
    r"rotary\s+position|rope\s+embedding|positional\s+encoding|"
    r"mixture\s+of\s+experts|moe\b|"
    r"benchmark(?:s)?|ablation(?:s)?|"
    r"neural\s+network(?:s)?|deep\s+learning|diffusion\s+model(?:s)?|"
    r"reinforcement\s+learning|rlhf|rlaif|"
    r"theorem|proof|conjecture|"
    r"semiconductor|quantum\s+(?:computing|annealing|hardware)"
    r")\b",
    re.IGNORECASE,
)

_MEDICAL_RE = re.compile(
    r"\b("
    r"pubmed|clinical(?:\s+trial)?|disease(?:s)?|syndrome(?:s)?|"
    r"vaccine(?:s)?|drug(?:s)?|pharma|treatment(?:s)?|therapy|therapies|"
    r"covid|sars|alzheimer|parkinson|cancer|tumou?r(?:s)?|"
    r"crispr|cas\s*9|gene(?:s)?\s+(?:editing|therapy)|"
    r"biomarker(?:s)?|cohort\s+study|meta.analysis|"
    r"mrna|antibody|antibodies|protein\s+folding"
    r")\b",
    re.IGNORECASE,
)

_FINANCE_RE = re.compile(
    r"\b("
    r"stock(?:s)?|ticker(?:s)?|equity|equities|share\s+price|"
    r"market\s+cap|earnings|dividend(?:s)?|"
    r"price\s+of\s+([A-Z]{1,5})|"  # captures ticker
    r"quote\s+([A-Z]{1,5})|"        # captures ticker
    r"\$([A-Z]{1,5})\b|"            # $MSFT style
    r"valuation|p/e\s+ratio|market\s+cap"
    r")",
)

_TECH_BUZZ_RE = re.compile(
    r"\b("
    r"hacker\s*news|hn\s+discussion|hn\s+buzz|"
    r"developer\s+sentiment|launch\s+thread|"
    r"open[\s-]?source\s+(?:release|launch|trend|community)|"
    r"trending\s+on\s+github|tech\s+twitter|hn\s+take"
    r")\b",
    re.IGNORECASE,
)

_TICKER_RE = re.compile(r"\b([A-Z]{2,5}(?:\.[A-Z]{1,3})?)\b")


def classify(topic: str) -> Domains:
    """Run the regex catalog over *topic*; populate Domains flags."""
    if not topic:
        return Domains()
    text = topic.strip()
    dom = Domains()

    if _ACADEMIC_RE.search(text):
        dom.academic = True
    if _MEDICAL_RE.search(text):
        dom.medical = True
    if _TECH_BUZZ_RE.search(text):
        dom.tech_buzz = True

    fin_match = _FINANCE_RE.search(text)
    if fin_match:
        dom.finance = True
        # Pull the captured ticker group if present.
        for grp in fin_match.groups():
            if grp and grp.isupper() and 1 <= len(grp.replace(".", "")) <= 5:
                dom.ticker = grp
                break
        if not dom.ticker:
            # Fall back to any standalone uppercase token (~ticker shape).
            tm = _TICKER_RE.search(text)
            if tm:
                dom.ticker = tm.group(1)

    return dom
