"""Yahoo Finance wrapper via lazy-imported `yfinance`.

We don't add `yfinance` to `requirements.txt` — the capability is
genuinely optional, and a missing dep should not break boot. If the lib
isn't installed, the handler returns an actionable install hint.

When present, yfinance scrapes Yahoo's public endpoints (no API key)
and gives us quote, history, info, and earnings out of the box.
"""
from __future__ import annotations

from core.logger import logger


def _import_yfinance():
    try:
        import yfinance as yf  # noqa: PLC0415
        return yf
    except ImportError:
        return None


def quote(ticker: str) -> dict | None:
    """Return latest quote for *ticker*."""
    yf = _import_yfinance()
    if yf is None:
        return None
    if not ticker or not ticker.strip():
        return None
    try:
        t = yf.Ticker(ticker.strip().upper())
        # `.fast_info` is the lightweight quote endpoint that doesn't hit
        # the heavy fundamentals API; falls back to .info on errors.
        try:
            fi = t.fast_info
            return {
                "ticker": ticker.upper(),
                "name": getattr(t, "info", {}).get("longName", ticker.upper()) if hasattr(t, "info") else ticker.upper(),
                "last_price": _safe_num(getattr(fi, "last_price", None)),
                "previous_close": _safe_num(getattr(fi, "previous_close", None)),
                "open": _safe_num(getattr(fi, "open", None)),
                "day_high": _safe_num(getattr(fi, "day_high", None)),
                "day_low": _safe_num(getattr(fi, "day_low", None)),
                "currency": getattr(fi, "currency", "") or "",
                "market_cap": _safe_num(getattr(fi, "market_cap", None)),
            }
        except Exception:
            info = getattr(t, "info", {}) or {}
            return {
                "ticker": ticker.upper(),
                "name": info.get("longName") or ticker.upper(),
                "last_price": info.get("regularMarketPrice"),
                "previous_close": info.get("regularMarketPreviousClose"),
                "open": info.get("regularMarketOpen"),
                "day_high": info.get("regularMarketDayHigh"),
                "day_low": info.get("regularMarketDayLow"),
                "currency": info.get("currency", ""),
                "market_cap": info.get("marketCap"),
            }
    except Exception as exc:
        logger.warning("[yfinance] quote failed for %r: %s", ticker, exc)
        return None


def _safe_num(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Capability handler
# ---------------------------------------------------------------------------


def handle_yfinance_quote(raw_text: str, args: dict) -> str:
    yf = _import_yfinance()
    if yf is None:
        return (
            "The `yfinance` package isn't installed. "
            "Run `pip install yfinance` in the FRIDAY venv to enable stock quotes."
        )
    ticker = (args.get("ticker") or args.get("symbol") or "").strip()
    if not ticker and raw_text:
        # Pull a ticker-looking token from the text (1-5 uppercase letters).
        import re as _re  # noqa: PLC0415
        m = _re.search(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b", raw_text)
        if m:
            ticker = m.group(1)
    if not ticker:
        return "Which ticker symbol? Try 'quote MSFT' or 'price of AAPL'."
    q = quote(ticker)
    if q is None:
        return f"Couldn't fetch a quote for {ticker.upper()}."
    cur = q.get("currency") or ""
    price = q.get("last_price")
    prev = q.get("previous_close")
    change = ""
    if price is not None and prev:
        delta = price - prev
        pct = (delta / prev * 100.0) if prev else 0.0
        sign = "+" if delta >= 0 else ""
        change = f" ({sign}{delta:.2f} / {sign}{pct:.2f}%)"
    parts = [f"**{q['name']} ({q['ticker']})**"]
    if price is not None:
        parts.append(f"Last: {price:.2f} {cur}{change}")
    if q.get("open") is not None and q.get("day_high") is not None and q.get("day_low") is not None:
        parts.append(f"Range today: {q['day_low']:.2f} – {q['day_high']:.2f} (open {q['open']:.2f})")
    mc = q.get("market_cap")
    if mc:
        # Render market cap in human units.
        if mc >= 1e12:
            parts.append(f"Market cap: ${mc/1e12:.2f}T")
        elif mc >= 1e9:
            parts.append(f"Market cap: ${mc/1e9:.2f}B")
        elif mc >= 1e6:
            parts.append(f"Market cap: ${mc/1e6:.2f}M")
    return "\n".join(parts)
