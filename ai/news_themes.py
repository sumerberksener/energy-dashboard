"""Orchestrate the news → themes pipeline.

Calls Claude once with the raw headline list and the news_themes_v1 prompt,
parses the strict-JSON response, returns a NewsThemesResult that the
generate_brief.py CLI renders as a "Today's themes" section.

Always returns a result object — even when no API key is set or the network
fetch fails, it falls back to a structured-empty payload so the brief never
breaks because of news ingestion.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic
import pandas as pd

from ai.client import AIClient, NoAPIKey, load_prompt

log = logging.getLogger(__name__)


@dataclass
class NewsThemesResult:
    geopolitics_summary: str = ""
    themes: list[dict[str, Any]] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)
    source: str = "rule-based"   # "claude" | "rule-based" | "rule-based-fallback"
    model: str | None = None
    log_path: str | None = None
    error: str | None = None
    n_headlines_in: int = 0


def _headlines_to_user_message(headlines: pd.DataFrame) -> str:
    """Render the headline DataFrame as a compact JSON list for the prompt."""
    rows = []
    for _, h in headlines.iterrows():
        rows.append({
            "source": h.get("source", ""),
            "published_at": str(h.get("published_at", "")),
            "title": h.get("title", ""),
            "summary": h.get("summary", "") or "",
            "link": h.get("link", ""),
        })
    return json.dumps({"headlines": rows}, indent=2, ensure_ascii=False)


def _parse_json(text: str) -> dict[str, Any]:
    t = text.strip()
    if t.startswith("```"):
        t = "\n".join(line for line in t.splitlines() if not line.strip().startswith("```"))
    return json.loads(t)


def extract_themes(
    headlines: pd.DataFrame,
    *,
    ai_client: AIClient | None = None,
) -> NewsThemesResult:
    """Run the news → themes extraction. Always returns a result object."""
    n = 0 if headlines is None else len(headlines)

    if headlines is None or headlines.empty:
        return NewsThemesResult(
            geopolitics_summary="No headlines fetched today (RSS sources unavailable or empty).",
            source="rule-based",
            n_headlines_in=0,
        )

    if ai_client is None:
        try:
            ai_client = AIClient()
        except NoAPIKey:
            # Without an LLM we still return the raw headlines so the brief
            # can show them as-is rather than dropping news entirely.
            themes = [
                {
                    "headline": str(row.get("title", ""))[:120],
                    "source": row.get("source", ""),
                    "tag": "uncategorised",
                    "commodity": "mixed",
                    "polarity": "neutral",
                    "why_it_matters": "(no AI extraction — set ANTHROPIC_API_KEY)",
                    "horizon": "days",
                    "link": row.get("link", ""),
                }
                for _, row in headlines.head(5).iterrows()
            ]
            return NewsThemesResult(
                geopolitics_summary="(news theme extraction unavailable — no API key set)",
                themes=themes,
                source="rule-based",
                n_headlines_in=n,
                error="ANTHROPIC_API_KEY not set",
            )

    user_msg = _headlines_to_user_message(headlines)
    system_prompt = load_prompt("news_themes_v1")

    try:
        result = ai_client.generate(
            system_prompt=system_prompt,
            user_message=user_msg,
            purpose="news_themes",
            max_tokens=1500,
        )
        try:
            parsed = _parse_json(result.text)
        except json.JSONDecodeError:
            retry = ai_client.generate(
                system_prompt=system_prompt,
                user_message=(
                    f"{user_msg}\n\nREMINDER: respond with strict JSON only. "
                    "First char `{`, last `}`. No markdown."
                ),
                purpose="news_themes_retry",
                max_tokens=1500,
            )
            parsed = _parse_json(retry.text)

        return NewsThemesResult(
            geopolitics_summary=parsed.get("geopolitics_summary", "") or "",
            themes=parsed.get("themes", []) or [],
            watchlist=parsed.get("watchlist", []) or [],
            source="claude",
            model=result.model,
            log_path=result.log_path,
            n_headlines_in=n,
        )
    except (anthropic.APIError, RuntimeError) as e:
        log.warning("news theme extraction failed: %s", e)
        return NewsThemesResult(
            geopolitics_summary=f"(news theme extraction failed: {type(e).__name__})",
            source="rule-based-fallback",
            n_headlines_in=n,
            error=str(e),
        )
