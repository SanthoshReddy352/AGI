#!/usr/bin/env python3
"""Intent eval harness — measures the deterministic IntentRecognizer layer.

FRIDAY's routing is a 5-layer hybrid (regex → keyword scorer → fuzzy → embedding
→ LLM planner). This harness exercises the **first, deterministic layer**
(`core.intent_recognizer.IntentRecognizer.plan`) against a golden corpus of
utterances and reports per-domain precision / recall. It is intentionally
**model-free and deterministic** so it can gate CI: it never loads a GGUF model,
an embedder, or the network.

The corpus lives in ``tests/intent_corpus/*.yaml`` — one file per domain. Each
case is one of:

    - say: "set brightness to 60"      # positive: must route to `tool`
      tool: set_brightness
      args: {level: 60}                # optional: asserted as a subset of args

    - say: "the battery in my car died"  # negative: must NOT route to `not`
      not: set_brightness

    - say: "what is the capital of France"  # negative: no deterministic route
      no_match: true

Run it directly for a human-readable report (exit 1 on any failure):

    python scripts/diagnostics/intent_eval.py
    python scripts/diagnostics/intent_eval.py --domain system_control --verbose

`tests/test_intent_eval.py` imports :func:`run_eval` for the CI gate.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

CORPUS_DIR = os.path.join(_PROJECT_ROOT, "tests", "intent_corpus")


# ---------------------------------------------------------------------------
# Corpus loading
# ---------------------------------------------------------------------------
@dataclass
class Case:
    say: str
    domain: str
    expect_tool: str | None = None      # positive expectation
    expect_args: dict = field(default_factory=dict)
    forbid_tool: str | None = None      # negative: must not route here
    no_match: bool = False              # negative: must produce no route

    @property
    def is_negative(self) -> bool:
        return self.no_match or self.forbid_tool is not None


def load_corpus(corpus_dir: str = CORPUS_DIR, domain_filter: str | None = None) -> list[Case]:
    import yaml

    cases: list[Case] = []
    if not os.path.isdir(corpus_dir):
        return cases
    for fname in sorted(os.listdir(corpus_dir)):
        if not fname.endswith((".yaml", ".yml")):
            continue
        domain = os.path.splitext(fname)[0]
        if domain_filter and domain_filter not in domain:
            continue
        with open(os.path.join(corpus_dir, fname), encoding="utf-8") as fh:
            doc = yaml.safe_load(fh) or {}
        doc_domain = doc.get("domain", domain)
        for raw in doc.get("cases", []) or []:
            cases.append(
                Case(
                    say=raw["say"],
                    domain=doc_domain,
                    expect_tool=raw.get("tool"),
                    expect_args=raw.get("args") or {},
                    forbid_tool=raw.get("not"),
                    no_match=bool(raw.get("no_match", False)),
                )
            )
    return cases


def corpus_tools(cases: list[Case]) -> set[str]:
    """Every tool referenced by the corpus — registered so each parser is live."""
    tools: set[str] = set()
    for c in cases:
        if c.expect_tool:
            tools.add(c.expect_tool)
        if c.forbid_tool:
            tools.add(c.forbid_tool)
    return tools


# ---------------------------------------------------------------------------
# Recognizer construction (model-free)
# ---------------------------------------------------------------------------
def make_recognizer(tools):
    """Build an IntentRecognizer wired to a stub router with `tools` registered.

    Uses a real :class:`core.dialog_state.DialogState` (all-None defaults) and
    `assistant_context=None` so the session-RAG document path stays inert.
    """
    from core.dialog_state import DialogState
    from core.intent_recognizer import IntentRecognizer

    router = SimpleNamespace(
        _tools_by_name={t: object() for t in tools},
        dialog_state=DialogState(),
        assistant_context=None,
        context_store=None,
        session_id=None,
    )
    return IntentRecognizer(router)


def route_of(recognizer, text: str):
    """Return (tool, args) for the first planned action, or (None, {})."""
    try:
        actions = recognizer.plan(text)
    except Exception as exc:  # pragma: no cover - defensive
        return ("__error__", {"error": str(exc)})
    if not actions:
        return (None, {})
    first = actions[0]
    return (first.get("tool"), dict(first.get("args") or {}))


# ---------------------------------------------------------------------------
# Conflict / overlap detection
#
# The deterministic layer is a hand-ordered chain of ~50 parsers; the first
# one that matches wins. That makes ordering load-bearing and fragile: if two
# parsers both match an utterance, a future reorder silently changes routing.
# These helpers run EACH parser independently (via the shared
# `_clause_parsers()`) so we can surface every multi-matcher utterance and any
# latent poaching the current ordering happens to mask.
# ---------------------------------------------------------------------------
def parser_matches(recognizer, text: str) -> list[tuple[str, str]]:
    """Return [(parser_name, tool), ...] for every parser that matches `text`,
    in chain order. Mirrors the clause prep `plan()` does (normalize + clean),
    but bypasses the plan-level knowledge-question / doc-question gates so we
    see the raw parser behavior."""
    from core.text_normalize import normalize_for_routing

    cleaned = recognizer._clean_text(normalize_for_routing(text))
    clause_lower = cleaned.lower().strip()
    hits: list[tuple[str, str]] = []
    for parser in recognizer._clause_parsers():
        try:
            action = parser(cleaned, clause_lower, {})
        except Exception:
            action = None
        if action and action.get("tool"):
            hits.append((parser.__name__, action["tool"]))
    return hits


def analyze_conflicts(corpus_dir: str = CORPUS_DIR, domain_filter: str | None = None):
    """Return (overlaps, poaches).

    overlaps: list of (say, [(parser, tool), ...]) where >1 parser matched.
    poaches:  list of (say, forbidden_tool, parser) where a `not:` negative is
              produced by SOME parser (latent — would route there if reordered).
    """
    cases = load_corpus(corpus_dir, domain_filter)
    recognizer = make_recognizer(corpus_tools(cases))
    overlaps, poaches = [], []
    for case in cases:
        hits = parser_matches(recognizer, case.say)
        if len(hits) > 1:
            overlaps.append((case.say, hits))
        if case.forbid_tool:
            for parser_name, tool in hits:
                if tool == case.forbid_tool:
                    poaches.append((case.say, case.forbid_tool, parser_name))
    return overlaps, poaches


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
@dataclass
class Failure:
    case: Case
    got_tool: str | None
    reason: str


@dataclass
class DomainStat:
    pos_total: int = 0
    pos_pass: int = 0
    neg_total: int = 0
    neg_pass: int = 0


def _args_match(expected: dict, got: dict) -> bool:
    """Expected args must appear as a subset of the produced args (string-compared)."""
    for key, val in expected.items():
        if key not in got or str(got[key]).strip().lower() != str(val).strip().lower():
            return False
    return True


def run_eval(corpus_dir: str = CORPUS_DIR, domain_filter: str | None = None):
    """Run the corpus. Returns (stats_by_domain, failures, case_count)."""
    cases = load_corpus(corpus_dir, domain_filter)
    recognizer = make_recognizer(corpus_tools(cases))

    stats: dict[str, DomainStat] = {}
    failures: list[Failure] = []

    for case in cases:
        stat = stats.setdefault(case.domain, DomainStat())
        got_tool, got_args = route_of(recognizer, case.say)

        if case.is_negative:
            stat.neg_total += 1
            if case.no_match:
                ok = got_tool is None
                reason = f"expected no route, got '{got_tool}'"
            else:  # forbid_tool
                ok = got_tool != case.forbid_tool
                reason = f"must not route to '{case.forbid_tool}'"
            if ok:
                stat.neg_pass += 1
            else:
                failures.append(Failure(case, got_tool, reason))
            continue

        # positive
        stat.pos_total += 1
        if got_tool != case.expect_tool:
            failures.append(Failure(case, got_tool, f"expected '{case.expect_tool}'"))
            continue
        if case.expect_args and not _args_match(case.expect_args, got_args):
            failures.append(
                Failure(case, got_tool, f"args mismatch: expected ⊇ {case.expect_args}, got {got_args}")
            )
            continue
        stat.pos_pass += 1

    return stats, failures, len(cases)


# ---------------------------------------------------------------------------
# Reporting / CLI
# ---------------------------------------------------------------------------
def _fmt_pct(num: int, den: int) -> str:
    return f"{(100.0 * num / den):5.1f}%" if den else "   n/a"


def print_report(stats, failures, case_count, verbose=False) -> None:
    print(f"\nIntent eval — {case_count} cases across {len(stats)} domains\n")
    print(f"{'domain':<32} {'recall':>8} {'neg-acc':>8}")
    print("-" * 50)
    tot = DomainStat()
    for domain in sorted(stats):
        s = stats[domain]
        tot.pos_total += s.pos_total
        tot.pos_pass += s.pos_pass
        tot.neg_total += s.neg_total
        tot.neg_pass += s.neg_pass
        print(f"{domain:<32} {_fmt_pct(s.pos_pass, s.pos_total):>8} {_fmt_pct(s.neg_pass, s.neg_total):>8}")
    print("-" * 50)
    print(f"{'TOTAL':<32} {_fmt_pct(tot.pos_pass, tot.pos_total):>8} {_fmt_pct(tot.neg_pass, tot.neg_total):>8}")
    print(
        f"\npositives: {tot.pos_pass}/{tot.pos_total}   "
        f"negatives: {tot.neg_pass}/{tot.neg_total}   "
        f"failures: {len(failures)}"
    )
    if failures and (verbose or len(failures) <= 40):
        print("\nFailures:")
        for f in failures:
            print(f"  [{f.case.domain}] {f.case.say!r} → got {f.got_tool!r} ({f.reason})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FRIDAY intent eval harness")
    parser.add_argument("--domain", help="only run domains whose filename contains this")
    parser.add_argument("--verbose", action="store_true", help="list every failure")
    parser.add_argument("--conflicts", action="store_true",
                        help="report parser overlaps + latent poaching instead of running the eval")
    args = parser.parse_args(argv)

    if args.conflicts:
        overlaps, poaches = analyze_conflicts(domain_filter=args.domain)
        print(f"\nParser overlap report — {len(overlaps)} multi-matcher utterance(s)\n")
        for say, hits in overlaps:
            chain = " > ".join(f"{p}->{t}" for p, t in hits)
            print(f"  {say!r}\n      {chain}")
        print(f"\nLatent poaching — {len(poaches)} case(s) where a forbidden tool is produced by some parser")
        for say, tool, parser_name in poaches:
            print(f"  {say!r} -> {tool} (via {parser_name})")
        return 1 if poaches else 0

    stats, failures, case_count = run_eval(domain_filter=args.domain)
    print_report(stats, failures, case_count, verbose=args.verbose)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
