"""Generate the AI desk-note narrative grounded in a structured metrics snapshot.

Two paths:
1. Live: build a JSON snapshot from the metric data + signals, send to Claude,
   return the response text along with metadata (model, tokens, log path).
2. Fallback: if ANTHROPIC_API_KEY is absent or the API call fails, return a
   deterministic rule-based string built from the same signals. The CLI and
   the dashboard always produce output; AI is an enhancement, not a hard dep.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic
import pandas as pd

from ai.client import AIClient, NoAPIKey, load_prompt
from analysis import stats
from analysis.signals import morning_brief, signal_for
from config import METRICS_BY_KEY

log = logging.getLogger(__name__)


@dataclass
class NarrativeResult:
    text: str
    source: str        # "claude" | "rule-based" | "rule-based-fallback"
    model: str | None
    log_path: str | None
    error: str | None


def _snapshot(data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Build the JSON-serialisable payload sent to the model.

    Includes only the latest values, key derived stats, and the rule-based
    headlines per metric — keeps the prompt compact and forces the model to
    reason from explicit numbers rather than guess.
    """
    out: dict[str, Any] = {"metrics": {}}
    for key, df in data.items():
        if df is None or df.empty:
            out["metrics"][key] = {"available": False}
            continue
        meta = METRICS_BY_KEY[key]
        sig = signal_for(key, df)
        latest_dt = df.index.max()
        out["metrics"][key] = {
            "available": True,
            "name": meta.short_name,
            "unit": meta.unit,
            "as_of": latest_dt.strftime("%Y-%m-%d") if pd.notna(latest_dt) else None,
            "latest": _round(stats.latest(df)),
            "daily_change_pct": _round(stats.daily_change_pct(df)),
            "weekly_change_pct": _round(stats.change_over_pct(df, 5)),
            "monthly_change_pct": _round(stats.change_over_pct(df, 21)),
            "percentile_rank_5y": _round(stats.percentile_rank(df), 0),
            "extension_50d_sigma": _round(stats.extension_sigma(df, 50), 2),
            "headline": sig.headline,
        }
    out["aggregate_brief"] = morning_brief(data)
    return out


def _round(x: Any, digits: int = 2):
    if x is None:
        return None
    try:
        return round(float(x), digits)
    except (TypeError, ValueError):
        return None


def _rule_based_fallback(snapshot: dict[str, Any]) -> str:
    """Deterministic narrative used when the AI path is unavailable.

    Composes a 3-4 sentence paragraph from the same signals an LLM would see —
    less fluent, but reproducible and free.
    """
    parts: list[str] = []

    ttf = snapshot["metrics"].get("ttf", {})
    storage = snapshot["metrics"].get("storage", {})
    eua = snapshot["metrics"].get("eua", {})
    cs = snapshot["metrics"].get("clean_spark", {})
    cd = snapshot["metrics"].get("clean_dark", {})
    power = snapshot["metrics"].get("de_power", {})

    if ttf.get("available"):
        parts.append(
            f"TTF prints at {ttf['latest']} EUR/MWh "
            f"({ttf.get('percentile_rank_5y', 0):.0f}th-pctile of 5y)."
        )

    if storage.get("available") and storage.get("latest") is not None:
        parts.append(
            f"EU storage stands at {storage['latest']:.1f}% full."
        )

    if eua.get("available"):
        parts.append(
            f"EUA at {eua['latest']} EUR/t "
            f"({eua.get('percentile_rank_5y', 0):.0f}th-pctile)."
        )

    if (
        cs.get("available") and cd.get("available")
        and cs.get("latest") is not None and cd.get("latest") is not None
    ):
        diff = cd["latest"] - cs["latest"]
        if diff > 0:
            switch = "coal in-the-money vs gas"
        elif diff < 0:
            switch = "gas in-the-money vs coal"
        else:
            switch = "spreads at parity"
        parts.append(
            f"Clean spark at {cs['latest']:+.1f} and clean dark at {cd['latest']:+.1f} "
            f"EUR/MWh — {switch}."
        )

    if power.get("available"):
        parts.append(
            f"DE day-ahead at {power['latest']:.1f} EUR/MWh anchors the front-curve."
        )

    if not parts:
        return (
            "Insufficient data to generate a desk note. Confirm API tokens are "
            "configured and the upstream sources are reachable."
        )

    parts.append(
        "Power-curve implication: regime is set by the prevailing fuel-switch "
        "and storage stance above."
    )
    return " ".join(parts)


def generate_narrative(
    data: dict[str, pd.DataFrame],
    *,
    ai_client: AIClient | None = None,
) -> NarrativeResult:
    """Produce the desk-note paragraph. Tries Claude; falls back on any failure."""
    snapshot = _snapshot(data)
    user_message = json.dumps(snapshot, indent=2, sort_keys=True)

    if ai_client is None:
        try:
            ai_client = AIClient()
        except NoAPIKey:
            return NarrativeResult(
                text=_rule_based_fallback(snapshot),
                source="rule-based",
                model=None,
                log_path=None,
                error="ANTHROPIC_API_KEY not set; using rule-based fallback",
            )

    system_prompt = load_prompt("desk_note_v1")

    try:
        result = ai_client.generate(
            system_prompt=system_prompt,
            user_message=user_message,
            purpose="desk_note_narrative",
        )
        return NarrativeResult(
            text=result.text,
            source="claude",
            model=result.model,
            log_path=result.log_path,
            error=None,
        )
    except anthropic.APIError as e:
        log.warning("Claude call failed (%s); using rule-based fallback", e)
        return NarrativeResult(
            text=_rule_based_fallback(snapshot),
            source="rule-based-fallback",
            model=None,
            log_path=None,
            error=f"{type(e).__name__}: {e}",
        )
