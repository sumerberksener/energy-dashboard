"""AI narrative generation: two-pass (extract → narrate) with single-pass + rule-based fallback.

Three layers of robustness:
1. **Two-pass (default)**: Claude pass 1 returns strict JSON (themes, risk flags,
   watchlist, top driver, top takeaway). Claude pass 2 writes prose grounded
   *only* in pass-1 JSON. Reduces hallucination and produces reusable
   structured artefacts (`output/<date>/data/ai_themes.json`).
2. **Single-pass**: one Claude call straight to prose. Used when invoked with
   `single_pass=True` (CLI: `--single-pass`). Faster, cheaper, but no extract.
3. **Rule-based fallback**: deterministic string built from the snapshot when
   no `ANTHROPIC_API_KEY` is set or any Claude call fails. The pipeline
   always emits output; AI is an enhancement, not a hard dependency.

All Claude calls are logged to `ai/logs/<date>.jsonl` via `ai/client.py`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import anthropic
import pandas as pd

from ai.client import AIClient, NARRATE_MODEL, NoAPIKey, load_prompt
from analysis import stats
from analysis.signals import morning_brief, signal_for
from config import METRICS_BY_KEY, STALE_AFTER_DAYS

log = logging.getLogger(__name__)


@dataclass
class NarrativeResult:
    text: str
    source: str        # "claude-two-pass" | "claude" | "rule-based" | "rule-based-fallback"
    model: str | None
    log_path: str | None
    error: str | None
    top_takeaway: str | None = None
    extract: dict[str, Any] | None = None
    extract_log_path: str | None = None


def _snapshot(
    data: dict[str, pd.DataFrame],
    news: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the JSON-serialisable payload sent to the model.

    Includes the structured news block when provided so the narrative pass
    can synthesise geopolitics + numbers in one shot.
    """
    out: dict[str, Any] = {
        "metrics": {},
        "freshness": {"any_stale": False, "stale_metrics": []},
    }
    if news is not None:
        out["news"] = news
    for key, df in data.items():
        # Skip auxiliary derived series (de_cal1_proj, switching_ttf, de_gb_spread,
        # eurusd) — they're internal helpers, not registered metrics.
        if key not in METRICS_BY_KEY:
            continue
        if df is None or df.empty:
            out["metrics"][key] = {"available": False}
            continue
        meta = METRICS_BY_KEY[key]
        sig = signal_for(key, df)
        latest_dt = df.index.max()
        days_old = stats.days_since_latest(df)
        stale = stats.is_stale(df, STALE_AFTER_DAYS)

        entry: dict[str, Any] = {
            "available": True,
            "name": meta.short_name,
            "unit": meta.unit,
            "as_of": latest_dt.strftime("%Y-%m-%d") if pd.notna(latest_dt) else None,
            "days_old": days_old,
            "is_stale": stale,
            "latest": _round(stats.latest(df)),
            "percentile_rank_5y": _round(stats.percentile_rank(df), 0),
            "extension_50d_sigma": _round(stats.extension_sigma(df, 50), 2),
            "headline": sig.headline,
        }
        if meta.delta_unit == "abs":
            entry["daily_change_abs"] = _round(stats.daily_change_abs(df))
            entry["weekly_change_abs"] = _round(stats.change_over_abs(df, 5, smooth_window=5, skip_below_abs=5))
            entry["monthly_change_abs"] = _round(stats.change_over_abs(df, 21))
            entry["delta_unit"] = meta.unit
        else:
            entry["daily_change_pct"] = _round(stats.daily_change_pct(df))
            entry["weekly_change_pct"] = _round(stats.change_over_pct(df, 5, smooth_window=5, skip_below_abs=5))
            entry["monthly_change_pct"] = _round(stats.change_over_pct(df, 21))
            entry["delta_unit"] = "pct"

        out["metrics"][key] = entry
        if stale:
            out["freshness"]["any_stale"] = True
            out["freshness"]["stale_metrics"].append({
                "key": key, "as_of": entry["as_of"], "days_old": days_old,
            })

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
    """Deterministic narrative for when the AI path is unavailable."""
    parts: list[str] = []

    ttf = snapshot["metrics"].get("ttf", {})
    storage = snapshot["metrics"].get("storage", {})
    eua = snapshot["metrics"].get("eua", {})
    cs = snapshot["metrics"].get("clean_spark", {})
    cd = snapshot["metrics"].get("clean_dark", {})
    de_pow = snapshot["metrics"].get("de_power", {})
    gb_pow = snapshot["metrics"].get("gb_power", {})
    rs = snapshot["metrics"].get("renewable_share", {})

    if ttf.get("available"):
        parts.append(
            f"TTF prints at {ttf['latest']} EUR/MWh "
            f"({ttf.get('percentile_rank_5y', 0):.0f}th-pctile of 5y)."
        )
    if storage.get("available") and storage.get("latest") is not None:
        parts.append(f"EU storage stands at {storage['latest']:.1f}% full.")
    if eua.get("available"):
        parts.append(
            f"EUA at {eua['latest']} EUR/t "
            f"({eua.get('percentile_rank_5y', 0):.0f}th-pctile)."
        )
    if rs.get("available") and rs.get("latest") is not None:
        parts.append(
            f"DE renewable share forecast at {rs['latest']:.1f}% of load."
        )
    if (
        cs.get("available") and cd.get("available")
        and cs.get("latest") is not None and cd.get("latest") is not None
    ):
        diff = cd["latest"] - cs["latest"]
        switch = "coal in-the-money vs gas" if diff > 0 else (
            "gas in-the-money vs coal" if diff < 0 else "spreads at parity"
        )
        parts.append(
            f"Clean spark at {cs['latest']:+.1f} and clean dark at {cd['latest']:+.1f} "
            f"EUR/MWh — {switch}."
        )
    if de_pow.get("available") and gb_pow.get("available"):
        gap = de_pow["latest"] - gb_pow["latest"]
        parts.append(
            f"DE day-ahead at {de_pow['latest']:.1f} vs GB at "
            f"{gb_pow['latest']:.1f} EUR/MWh ({gap:+.1f} cross-border spread)."
        )
    elif de_pow.get("available"):
        parts.append(
            f"DE day-ahead at {de_pow['latest']:.1f} EUR/MWh anchors the front-curve."
        )
    if not parts:
        return (
            "Insufficient data to generate a desk note. Confirm API tokens are "
            "configured and the upstream sources are reachable."
        )
    parts.append(
        "Power-curve implication: regime is set by the prevailing fuel-switch, "
        "storage stance, and renewables forecast above."
    )
    return " ".join(parts)


def _rule_based_top_takeaway(snapshot: dict[str, Any]) -> str | None:
    """Single-sentence headline used when AI is unavailable."""
    cs = snapshot["metrics"].get("clean_spark", {})
    cd = snapshot["metrics"].get("clean_dark", {})
    storage = snapshot["metrics"].get("storage", {})
    rs = snapshot["metrics"].get("renewable_share", {})

    bits: list[str] = []
    if cs.get("available") and cd.get("available") and cs.get("latest") is not None:
        diff = cd["latest"] - cs["latest"]
        bits.append("Coal in-the-money" if diff > 0 else "Gas in-the-money")
    if storage.get("available") and storage.get("latest") is not None:
        bits.append(f"storage {storage['latest']:.0f}%")
    if rs.get("available") and rs.get("latest") is not None:
        bits.append(f"renewables {rs['latest']:.0f}% of load")
    if not bits:
        return None
    return "; ".join(bits) + "."


# --- Two-pass workflow ------------------------------------------------------


def _parse_extract_json(text: str) -> dict[str, Any]:
    """Parse the extract pass output. Tolerates accidental code fences."""
    t = text.strip()
    if t.startswith("```"):
        # Drop a possible leading ```json line and trailing ``` fence.
        t = "\n".join(line for line in t.splitlines() if not line.strip().startswith("```"))
    return json.loads(t)


def _generate_two_pass(
    ai_client: AIClient,
    snapshot: dict[str, Any],
) -> NarrativeResult:
    """Pass 1 returns structured JSON; pass 2 writes prose from that JSON."""
    snapshot_json = json.dumps(snapshot, indent=2, sort_keys=True)
    extract_system = load_prompt("extract_v1")
    narrate_system = load_prompt("narrate_v1")

    # --- Pass 1: extract ----
    # Bumped from 1024 -> 2048 after the schema grew (scenarios block,
    # watchlist_dated block). The earlier limit was clipping responses
    # mid-string, which surfaced as JSONDecodeError on the first pass and
    # often forced the rule-based fallback after the retry also clipped.
    extract_result = ai_client.generate(
        system_prompt=extract_system,
        user_message=snapshot_json,
        purpose="extract",
        max_tokens=2048,
    )
    try:
        extract = _parse_extract_json(extract_result.text)
    except json.JSONDecodeError as e:
        log.warning("Extract pass returned invalid JSON (%s); retrying once with corrective hint", e)
        retry = ai_client.generate(
            system_prompt=extract_system,
            user_message=(
                f"{snapshot_json}\n\n"
                "REMINDER: respond with strict JSON only. First char `{`, last `}`. No markdown."
            ),
            purpose="extract_retry",
            max_tokens=2048,
        )
        try:
            extract = _parse_extract_json(retry.text)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Extract pass returned non-JSON twice; last response: {retry.text[:200]!r}"
            )

    # --- Pass 2: narrate ----
    # Cost-aware tiering: the narrate pass writes the executive summary the
    # trader reads first. We use NARRATE_MODEL (default Sonnet) here even
    # though the extract pass uses the cheaper Haiku — empirically Sonnet
    # produces measurably better operational call-outs on the same JSON
    # input (see README §AI workflow). A separate client is instantiated
    # so the audit log captures the model swap on the narrate record.
    narrate_input = json.dumps(extract, indent=2, sort_keys=True)
    if NARRATE_MODEL != ai_client.model:
        narrate_client = AIClient(model=NARRATE_MODEL, log_dir=ai_client.log_dir)
    else:
        narrate_client = ai_client
    narrate_result = narrate_client.generate(
        system_prompt=narrate_system,
        user_message=narrate_input,
        purpose="narrate",
        max_tokens=512,
    )

    return NarrativeResult(
        text=narrate_result.text,
        source="claude-two-pass",
        model=narrate_result.model,
        log_path=narrate_result.log_path,
        extract_log_path=extract_result.log_path,
        error=None,
        top_takeaway=extract.get("top_takeaway"),
        extract=extract,
    )


# --- Single-pass workflow (kept as fallback / `--single-pass` flag) --------


def _generate_single_pass(
    ai_client: AIClient,
    snapshot: dict[str, Any],
) -> NarrativeResult:
    user_message = json.dumps(snapshot, indent=2, sort_keys=True)
    system_prompt = load_prompt("desk_note_v1")
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
        top_takeaway=None,
    )


# --- Public entry point ----------------------------------------------------


def generate_narrative(
    data: dict[str, pd.DataFrame],
    *,
    ai_client: AIClient | None = None,
    two_pass: bool = True,
    news: dict[str, Any] | None = None,
) -> NarrativeResult:
    """Produce the desk-note paragraph. Tries two-pass Claude → single-pass → rule-based.

    Optional `news` is the dict form of a NewsThemesResult — the prose pass
    will reference geopolitics if present.
    """
    snapshot = _snapshot(data, news=news)

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
                top_takeaway=_rule_based_top_takeaway(snapshot),
            )

    try:
        if two_pass:
            return _generate_two_pass(ai_client, snapshot)
        return _generate_single_pass(ai_client, snapshot)
    except (anthropic.APIError, RuntimeError) as e:
        log.warning("Claude call failed (%s); using rule-based fallback", e)
        return NarrativeResult(
            text=_rule_based_fallback(snapshot),
            source="rule-based-fallback",
            model=None,
            log_path=None,
            error=f"{type(e).__name__}: {e}",
            top_takeaway=_rule_based_top_takeaway(snapshot),
        )
