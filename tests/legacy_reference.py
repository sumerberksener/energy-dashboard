"""Verbatim copies of the pre-fix code paths, used as the reference for the
regression tests ("the brief for healthy sources is unchanged").

Source: commit 7f71374 (2026-10-27, the last green scheduled run), files
scripts/generate_brief.py lines 58-125 (`_safe_fetch`, `fetch_all`) and
data/news.py lines 56-109 (`fetch_headlines`, renamed here to
`legacy_fetch_headlines`). Nothing below was edited except that rename, the
imports, and em/en dashes in comments and docstrings turned into hyphens. Do not "fix" this file; it exists to be the old behaviour.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

from analysis import derived as derived_metrics
from data import fetchers
from data.news import (  # unchanged helpers the old function used
    DEFAULT_FEEDS,
    MAX_AGE_DAYS_DEFAULT,
    _clean_summary,
    _parse_published,
)

log = logging.getLogger("brief")


# --- scripts/generate_brief.py @ 7f71374, lines 58-125 ----------------------

def _safe_fetch(name: str, fn, *args):
    try:
        df = fn(*args)
        if df is None or df.empty:
            log.warning("%s: empty result", name)
            return pd.DataFrame(columns=["value"])
        return df
    except Exception as e:
        log.warning("%s: fetch failed (%s)", name, e)
        return pd.DataFrame(columns=["value"])


def fetch_all() -> dict[str, pd.DataFrame]:
    primaries = {
        "ttf": _safe_fetch("ttf", fetchers.fetch_ttf),
        "eua": _safe_fetch("eua", fetchers.fetch_eua),
        "coal": _safe_fetch("coal", fetchers.fetch_coal),
        "de_power": _safe_fetch(
            "de_power", fetchers.fetch_de_power, os.environ.get("ENTSOE_TOKEN")
        ),
        "gb_power": _safe_fetch(
            "gb_power", fetchers.fetch_gb_power, os.environ.get("ENTSOE_TOKEN")
        ),
        "renewable_share": _safe_fetch(
            "renewable_share", fetchers.fetch_renewable_share, os.environ.get("ENTSOE_TOKEN")
        ),
        "storage": _safe_fetch(
            "storage", fetchers.fetch_storage, os.environ.get("AGSI_TOKEN")
        ),
    }
    eurusd = _safe_fetch("eurusd", fetchers.fetch_eurusd)

    primaries["clean_spark"] = derived_metrics.clean_spark_spread(
        primaries["de_power"], primaries["ttf"], primaries["eua"]
    )
    primaries["clean_dark"] = derived_metrics.clean_dark_spread(
        primaries["de_power"], primaries["coal"], primaries["eua"], eurusd
    )
    # Section 5's "DA / Cal+1 (model)" + multi-tenor curve-shape sentence read
    # from these. All five horizons share `seasonality_projection` so the
    # methodology is consistent across tenors. Without them the forward-curve
    # indications silently disappear from the desk note.
    for label, bdays in derived_metrics.HORIZON_BDAYS.items():
        primaries[f"de_{label}_proj"] = derived_metrics.seasonality_projection(
            primaries["de_power"], horizon_bdays=bdays,
        )
    # TTF - JKM spread (LNG arb signal) - Cobblestone trades pipeline + LNG.
    # JKM is fetched as USD/MMBtu; spread converts to EUR/MWh comparable basis.
    primaries["jkm"] = _safe_fetch("jkm", fetchers.fetch_jkm)
    primaries["ttf_jkm_spread"] = derived_metrics.ttf_jkm_spread(
        primaries["ttf"], primaries["jkm"], eurusd
    )
    # Cross-border physical flows - Cobblestone's "Power Transportation"
    # pillar. Three corridors that read continental flow direction.
    for from_zone, to_zone in fetchers.INTERCONNECTORS:
        key = f"flow_{from_zone.lower().replace('_lu','').replace('_','')}_" \
              f"{to_zone.lower().replace('_lu','').replace('_','')}"
        primaries[key] = _safe_fetch(
            key, fetchers.fetch_cross_border_flow,
            os.environ.get("ENTSOE_TOKEN"), from_zone, to_zone,
        )
    # Weather forecasts at regional centroids - Energy Meteorologists pillar.
    for label, (lat, lon) in fetchers.WEATHER_LOCATIONS.items():
        primaries[f"weather_{label.lower()}"] = _safe_fetch(
            f"weather_{label.lower()}", fetchers.fetch_weather_forecast,
            lat, lon, label,
        )
    return primaries


# --- data/news.py @ 7f71374, lines 56-109 -----------------------------------

def legacy_fetch_headlines(
    feeds: list[tuple[str, str]] | None = None,
    max_age_days: int = MAX_AGE_DAYS_DEFAULT,
    max_per_feed: int = 12,
    max_total: int = 40,
) -> pd.DataFrame:
    """Fetch headlines from RSS feeds, filter by recency, return a tidy DF.

    `feedparser` is the only third-party dependency here - it handles RSS,
    Atom, and the various date encodings these sources use without a fight.
    Network errors per feed are logged and soft-failed - one bad feed never
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
