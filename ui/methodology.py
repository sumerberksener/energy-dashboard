"""Methodology tab content — surfaces the per-metric definitions, the
signal logic, and the spread/switching formulas in one place.
"""
from __future__ import annotations

import streamlit as st

from config import (
    COAL_CALORIFIC_MWH_PER_T,
    COAL_EFFICIENCY,
    COAL_EMISSION_FACTOR,
    GAS_EFFICIENCY,
    GAS_EMISSION_FACTOR,
    METRICS,
    PERCENTILE_HIGH,
    PERCENTILE_LOW,
    SIGMA_EXTENDED,
    STALE_AFTER_DAYS,
    ZSCORE_OUTSIZED,
)


def render() -> None:
    st.markdown("### Cross-commodity thesis")
    st.write(
        "European power-curve risk is set by **gas tightness** (TTF level + EU storage), "
        "**carbon level** (EUA), and the **clean-spread regime** that ties them together. "
        "When the clean spark exceeds the clean dark, gas is the marginal European fuel and "
        "TTF moves transmit directly into the power curve. When dark dominates, coal+carbon "
        "shocks set the regime instead. Storage trajectory vs the 5-yr seasonal average "
        "tells you whether the gas-side risk is symmetric or skewed."
    )

    st.markdown("### Metrics tracked")
    for metric in METRICS:
        with st.expander(f"{metric.short_name} — {metric.name}", expanded=False):
            st.write(metric.definition)
            st.caption(f"Source: {metric.source} · Unit: {metric.unit}")

    st.markdown("### Plant assumptions (clean spark / clean dark / switching TTF)")
    st.markdown(
        f"- **Gas (CCGT)**: η = {GAS_EFFICIENCY:.2f}, "
        f"emission factor = {GAS_EMISSION_FACTOR} tCO₂/MWh thermal\n"
        f"- **Hard coal plant**: η = {COAL_EFFICIENCY:.2f}, "
        f"emission factor = {COAL_EMISSION_FACTOR} tCO₂/MWh thermal, "
        f"calorific value = {COAL_CALORIFIC_MWH_PER_T:.3f} MWh/t"
    )
    st.markdown("**Formulas**")
    st.code(
        "Clean Spark    = Power − Gas/η_gas − Carbon × (EF_gas / η_gas)\n"
        "Clean Dark     = Power − Coal_EUR/η_coal − Carbon × (EF_coal / η_coal)\n"
        "Switching TTF  = η_gas · ( Coal_EUR/η_coal "
        "+ (EF_coal/η_coal − EF_gas/η_gas) · EUA )\n\n"
        "Coal_EUR per MWh thermal = (Coal_USD/t / EURUSD) / 6.978",
        language="text",
    )

    st.markdown("### Indicative Cal+1 power (seasonality projection)")
    st.markdown(
        "Free daily EEX Cal-Year settlement is not accessible without a paid "
        "feed (Bloomberg, Refinitiv, ICE Endex direct). The dashboard's Cal+1 "
        "line is **a model-derived seasonality projection, not a market quote**. "
        "Method: for each historical date, find the realised DA price exactly "
        "1 year later (with a ±3-day window) and report the rolling 30-day mean "
        "of those forward realisations. The DA − Cal+1 spread reads as a "
        "front-vs-back regime indicator (backwardation vs contango). Caveats: "
        "backward-looking, mean-reverting, doesn't price in current expectations "
        "of carbon / weather / demand — a real Cal+1 quote does. Replace with "
        "EEX settlement when a paid feed is available."
    )

    st.markdown("### Rule-based signal thresholds")
    st.markdown(
        f"- **Percentile rank (5y)**: ≥ {PERCENTILE_HIGH} → 'historically high'; "
        f"≤ {PERCENTILE_LOW} → 'historically low'\n"
        f"- **Extension from 50d MA**: |σ| ≥ {SIGMA_EXTENDED} → 'extended above/below trend'\n"
        f"- **Daily-move z-score (vs 60d)**: |z| ≥ {ZSCORE_OUTSIZED} → 'outsized move'\n"
        f"- **Storage seasonal deviation**: pp difference vs same-day historical mean\n"
        f"- **Data freshness**: > {STALE_AFTER_DAYS} days old triggers a STALE flag"
    )

    st.markdown("### AI workflow")
    st.markdown(
        "Two-pass design: **(1) extract** — Claude returns strict JSON "
        "(themes, risk flags, watchlist, top takeaway) grounded in the metric "
        "snapshot. **(2) narrate** — a second Claude pass writes 3–5 sentence "
        "prose using *only* the extract JSON. Reduces hallucination; produces "
        "structured artefacts that are reusable in the dashboard. Every call is "
        "logged to `ai/logs/<date>.jsonl` with prompt SHA, full text, token usage, "
        "and latency. Falls back to a deterministic rule-based string when the "
        "API key is missing or a call fails — pipeline always emits output."
    )
