"""News + geopolitics ingestion.

Pulls headlines from public RSS/Atom feeds covering global energy markets
and EU policy. Each headline is a candidate for the AI theme-extraction pass
(`ai/news_themes.py`), which structures them into a JSON object the desk
note can render as a "Today's themes" section.

Pure pandas, no Streamlit dependency. Returns a tidy DataFrame:
    columns: source, published_at, title, summary, link
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

log = logging.getLogger(__name__)


# Free, public RSS/Atom feeds. Order = priority. Each is best-effort: if a
# feed is down or blocks the user-agent, the others still produce output.
DEFAULT_FEEDS: list[tuple[str, str]] = [
    # --- European-focused (priority for desk relevance) -----------------
    ("Reuters Energy", "https://www.reuters.com/business/energy/feed/"),
    ("Reuters Sustainability", "https://www.reuters.com/sustainability/feed/"),
    ("Politico EU Energy", "https://www.politico.eu/section/energy/feed/"),
    ("S&P Commodity Insights — Electric Power",
     "https://www.spglobal.com/commodityinsights/en/rss-feed/electric-power"),
    ("S&P Commodity Insights — Natural Gas",
     "https://www.spglobal.com/commodityinsights/en/rss-feed/natural-gas"),
    ("Gasworld", "https://www.gasworld.com/feed"),
    ("Montel News", "https://www.montelnews.com/news.rss"),
    ("ENTSO-E News", "https://www.entsoe.eu/news/feed/"),
    ("Bruegel Energy", "https://www.bruegel.org/topic/energy-climate/feed"),
    ("Bruegel All", "https://www.bruegel.org/all-articles.rss"),
    ("Bruegel Blog", "https://www.bruegel.org/blog-post/feed"),
    ("Euractiv Energy", "https://www.euractiv.com/section/energy-environment/feed/"),
    # --- Global-energy (secondary; surfaces only if EU-relevant) --------
    ("IEA News", "https://www.iea.org/news/feed"),
    ("EIA Today in Energy", "https://www.eia.gov/rss/todayinenergy.xml"),
    ("EIA Natural Gas Weekly", "https://www.eia.gov/rss/naturalgas.xml"),
    # --- Removed (US-only domestic noise that crowded out EU items) -----
    # EIA Petroleum Weekly was dropping low-relevance US-domestic items
    # into the "Today's themes" section. The Claude theme-extraction
    # prompt filters for EU relevance, but with too many US sources the
    # 5-theme cap was being eaten by them. Removed; reinstate if a
    # specific Brent / refined-products thesis ever needs the data.
]

# Headlines older than this are filtered out — energy news goes stale fast,
# but a 10-day window catches weekly publications (EIA Natural Gas Weekly).
MAX_AGE_DAYS_DEFAULT = 10


def fetch_headlines(
    feeds: list[tuple[str, str]] | None = None,
    max_age_days: int = MAX_AGE_DAYS_DEFAULT,
    max_per_feed: int = 12,
    max_total: int = 40,
) -> pd.DataFrame:
    """Fetch headlines from RSS feeds, filter by recency, return a tidy DF.

    `feedparser` is the only third-party dependency here — it handles RSS,
    Atom, and the various date encodings these sources use without a fight.
    Network errors per feed are logged and soft-failed — one bad feed never
    breaks the brief.
    """
    import feedparser

    feeds = feeds or DEFAULT_FEEDS
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    rows: list[dict] = []

    for source_name, url in feeds:
        try:
            parsed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"})
        except Exception as e:
            log.warning("news feed %s failed: %s", source_name, e)
            continue
        if parsed.bozo and not parsed.entries:
            log.info("news feed %s bozo flag set, no entries: %s",
                     source_name, getattr(parsed, "bozo_exception", ""))
            continue

        kept = 0
        for entry in parsed.entries:
            published = _parse_published(entry)
            if published is None:
                continue
            if published < cutoff:
                continue
            rows.append({
                "source": source_name,
                "published_at": published,
                "title": (entry.get("title") or "").strip(),
                "summary": _clean_summary(entry.get("summary", "")),
                "link": entry.get("link", ""),
            })
            kept += 1
            if kept >= max_per_feed:
                break

    if not rows:
        return pd.DataFrame(columns=["source", "published_at", "title", "summary", "link"])

    df = pd.DataFrame(rows)
    df = df.sort_values("published_at", ascending=False).head(max_total).reset_index(drop=True)
    return df


def _parse_published(entry) -> datetime | None:
    """Best-effort extraction of a tz-aware UTC datetime from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            return pd.to_datetime(raw, utc=True).to_pydatetime()
        except Exception:
            return None
    return None


def _clean_summary(s: str, max_chars: int = 260) -> str:
    """Strip HTML tags and clamp length so we don't blow the AI prompt budget."""
    if not s:
        return ""
    import re
    no_tags = re.sub(r"<[^>]+>", "", s)
    collapsed = re.sub(r"\s+", " ", no_tags).strip()
    if len(collapsed) > max_chars:
        return collapsed[: max_chars - 1].rstrip() + "…"
    return collapsed
