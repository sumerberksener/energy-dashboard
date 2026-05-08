"""Headless CLI: pulls public data, generates charts, calls the AI, writes a desk note.

Usage:
    python scripts/generate_brief.py [--out-root output] [--single-pass] [--no-news] [--pdf]

Outputs (under output/<YYYY-MM-DD>/):
    desk_note_<YYYY-MM-DD>.md      1–3 page Markdown desk note (the deliverable)
    desk_note_<YYYY-MM-DD>.pdf     PDF render (when --pdf and pandoc available)
    data/snapshot.csv              today's pivot table of all metrics
    data/<metric>.csv              full multi-year history per metric
    data/ai_snapshot.json          exact JSON payload sent to Claude (extract pass)
    data/ai_themes.json            structured extract output (themes, risk flags, top takeaway)
    data/ai_news_themes.json       structured news extraction (geopolitics, themes, watchlist)
    charts/01_*.png … charts/05_*.png   generated charts referenced by the note
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ai.narrative import generate_narrative  # noqa: E402
from ai.news_themes import extract_themes  # noqa: E402
from analysis import derived as derived_metrics  # noqa: E402
from analysis import stats  # noqa: E402
from analysis.signals import cross_market_tag, signal_for  # noqa: E402
from config import (  # noqa: E402
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    FUNDAMENTALS_METRICS,
    METRICS,
    METRICS_BY_KEY,
    STALE_AFTER_DAYS,
    SUBMISSION_TITLE,
    TOP_ROW_METRICS,
)
from data import fetchers, news  # noqa: E402

log = logging.getLogger("brief")


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
    # TTF − JKM spread (LNG arb signal) — Cobblestone trades pipeline + LNG.
    # JKM is fetched as USD/MMBtu; spread converts to EUR/MWh comparable basis.
    primaries["jkm"] = _safe_fetch("jkm", fetchers.fetch_jkm)
    primaries["ttf_jkm_spread"] = derived_metrics.ttf_jkm_spread(
        primaries["ttf"], primaries["jkm"], eurusd
    )
    return primaries


def write_csvs(data: dict[str, pd.DataFrame], data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for metric in METRICS:
        df = data.get(metric.key)
        if df is None or df.empty:
            continue
        df.to_csv(data_dir / f"{metric.key}.csv")
        days_old = stats.days_since_latest(df)
        stale = stats.is_stale(df, STALE_AFTER_DAYS)
        row = {
            "metric": metric.short_name,
            "as_of": df.index.max().strftime("%Y-%m-%d"),
            "days_old": days_old,
            "is_stale": stale,
            "is_fundamentals_input": metric.is_fundamentals_input,
            "value": stats.latest(df),
            "unit": metric.unit,
            "percentile_5y": stats.percentile_rank(df),
        }
        if metric.delta_unit == "abs":
            row["daily_change_abs"] = stats.daily_change_abs(df)
            row["weekly_change_abs"] = stats.change_over_abs(df, 5, smooth_window=5, skip_below_abs=5)
            row["monthly_change_abs"] = stats.change_over_abs(df, 21)
        else:
            row["daily_change_pct"] = stats.daily_change_pct(df)
            row["weekly_change_pct"] = stats.change_over_pct(df, 5, smooth_window=5, skip_below_abs=5)
            row["monthly_change_pct"] = stats.change_over_pct(df, 21)
        rows.append(row)
    snap = pd.DataFrame(rows)
    snap_path = data_dir / "snapshot.csv"
    snap.to_csv(snap_path, index=False)
    return snap_path


# --- Charts -----------------------------------------------------------------


def _setup_axes(ax, title: str, ylabel: str):
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def plot_clean_spreads(data: dict[str, pd.DataFrame], charts_dir: Path) -> Path | None:
    cs = data.get("clean_spark")
    cd = data.get("clean_dark")
    if (cs is None or cs.empty) and (cd is None or cd.empty):
        return None
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=1)
    fig, ax = plt.subplots(figsize=(6, 2.8))
    if cs is not None and not cs.empty:
        s = cs[cs.index >= cutoff]
        ax.plot(s.index, s["value"], color="#fab387", label="Clean Spark", linewidth=2)
    if cd is not None and not cd.empty:
        s = cd[cd.index >= cutoff]
        ax.plot(s.index, s["value"], color="#f38ba8", label="Clean Dark", linewidth=2)
    ax.axhline(0, color="grey", linestyle="--", linewidth=0.8)
    _setup_axes(ax, "Clean Spark vs Clean Dark — Day-Ahead, 1Y", "EUR/MWh")
    ax.legend(loc="best", frameon=False)
    fig.tight_layout()
    p = charts_dir / "01_clean_spreads.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


def plot_gas_vs_storage(data: dict[str, pd.DataFrame], charts_dir: Path) -> Path | None:
    ttf = data.get("ttf")
    storage = data.get("storage")
    if (ttf is None or ttf.empty) and (storage is None or storage.empty):
        return None
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=2)
    fig, ax = plt.subplots(figsize=(6, 2.8))
    if ttf is not None and not ttf.empty:
        s = ttf[ttf.index >= cutoff]
        ax.plot(s.index, s["value"], color="#f9b500", label="TTF (lhs)", linewidth=2)
    _setup_axes(ax, "TTF Gas vs EU Storage — 2Y", "TTF EUR/MWh")
    if storage is not None and not storage.empty:
        ax2 = ax.twinx()
        s = storage[storage.index >= cutoff]
        ax2.plot(s.index, s["value"], color="#cba6f7", label="Storage (rhs)",
                 linewidth=2, alpha=0.85)
        ax2.set_ylabel("Storage % full")
        ax2.set_ylim(0, 100)
        ax2.spines["top"].set_visible(False)
    fig.tight_layout()
    p = charts_dir / "02_gas_storage.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


def plot_eua_carbon(data: dict[str, pd.DataFrame], charts_dir: Path) -> Path | None:
    eua = data.get("eua")
    if eua is None or eua.empty:
        return None
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=2)
    s = eua[eua.index >= cutoff]
    fig, ax = plt.subplots(figsize=(6, 2.8))
    ax.plot(s.index, s["value"], color="#40a02b", linewidth=2)
    _setup_axes(ax, "EUA December Carbon Futures — 2Y", "EUR/tCO2")
    fig.tight_layout()
    p = charts_dir / "03_eua_carbon.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


def plot_de_gb_power(data: dict[str, pd.DataFrame], charts_dir: Path) -> Path | None:
    de = data.get("de_power")
    gb = data.get("gb_power")
    if (de is None or de.empty) and (gb is None or gb.empty):
        return None
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=1)
    fig, ax = plt.subplots(figsize=(6, 2.8))
    if de is not None and not de.empty:
        s = de[de.index >= cutoff]
        ax.plot(s.index, s["value"], color="#89b4fa", label="DE Power", linewidth=2)
    if gb is not None and not gb.empty:
        s = gb[gb.index >= cutoff]
        ax.plot(s.index, s["value"], color="#74c7ec", label="GB Power", linewidth=2)
    _setup_axes(ax, "DE vs GB Day-Ahead Power — 1Y", "EUR/MWh")
    ax.legend(loc="best", frameon=False)
    fig.tight_layout()
    p = charts_dir / "04_de_gb_power.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


def plot_renewable_share(data: dict[str, pd.DataFrame], charts_dir: Path) -> Path | None:
    rs = data.get("renewable_share")
    if rs is None or rs.empty:
        return None
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=1)
    s = rs[rs.index >= cutoff]
    fig, ax = plt.subplots(figsize=(6, 2.8))
    ax.plot(s.index, s["value"], color="#94e2d5", linewidth=2)
    ax.fill_between(s.index, 0, s["value"], color="#94e2d5", alpha=0.15)
    _setup_axes(ax, "DE Wind + Solar Forecast Share of Load — 1Y", "% of load")
    ax.set_ylim(bottom=0)
    fig.tight_layout()
    p = charts_dir / "05_renewable_share.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    return p


# --- Markdown desk note -----------------------------------------------------


def _row(metric, df) -> str:
    if df is None or df.empty:
        return f"| {metric.short_name} | — | — | {metric.unit} | — | — | — | (no data) |"
    sig = signal_for(metric.key, df)
    last = stats.latest(df)
    p = stats.percentile_rank(df)
    as_of = df.index.max().strftime("%Y-%m-%d")
    if stats.is_stale(df, STALE_AFTER_DAYS):
        as_of = f"{as_of} ⚠ STALE"

    if metric.delta_unit == "abs":
        d1 = stats.daily_change_abs(df)
        w1 = stats.change_over_abs(df, 5, smooth_window=5, skip_below_abs=5)
        d1_s = _fmt_abs(d1)
        w1_s = _fmt_abs(w1)
    else:
        d1 = stats.daily_change_pct(df)
        w1 = stats.change_over_pct(df, 5, smooth_window=5, skip_below_abs=5)
        d1_s = _fmt_pct(d1)
        w1_s = _fmt_pct(w1)

    return (
        f"| {metric.short_name} | {as_of} | {last:,.2f} | {metric.unit} | "
        f"{d1_s} | {w1_s} | {_fmt_int(p)} | {sig.headline} |"
    )


def _fmt_pct(x):
    return f"{x:+.2f}%" if x is not None else "—"


def _fmt_abs(x):
    return f"{x:+.2f}" if x is not None else "—"


def _fmt_int(x):
    return f"{x:.0f}" if x is not None else "—"


def build_markdown(
    data: dict[str, pd.DataFrame],
    narrative,
    news_themes,
    charts: list[Path],
    snap_csv: Path,
    today_dir: Path,
    today_str: str,
) -> Path:
    lines: list[str] = []
    L = lines.append

    L(f"# {SUBMISSION_TITLE}")
    L("")
    L(f"**Daily desk brief — {today_str}**  ")
    L(f"_Author: {AUTHOR_NAME} · {AUTHOR_EMAIL}_  ")
    L(f"_Generated by `scripts/generate_brief.py`. AI narrative + news themes via Anthropic Claude._")
    L("")

    # Freshness preamble — list any stale series before anything else.
    stale = []
    for metric in METRICS:
        df = data.get(metric.key)
        if df is None or df.empty:
            continue
        if stats.is_stale(df, STALE_AFTER_DAYS):
            stale.append(
                f"{metric.short_name} (last {df.index.max().date()}, "
                f"{stats.days_since_latest(df)}d old)"
            )
    if stale:
        L(f"> ⚠ **Data-freshness caveat**: {'; '.join(stale)}. "
          f"Numbers below should be read with this in mind.")
        L("")

    # Section 1 — Executive summary
    L("## 1 · Executive summary")
    L("")
    if narrative.top_takeaway:
        L(f"**TL;DR — {narrative.top_takeaway}**")
        L("")
    L(narrative.text)
    L("")
    if narrative.source.startswith("claude"):
        passes = "two-pass extract→narrate" if narrative.source == "claude-two-pass" else "single-pass"
        L(f"_Generated by **{narrative.model}** via Anthropic API ({passes}). "
          f"Prompts/responses logged to `ai/logs/`._")
    else:
        L(f"_Rule-based fallback ({narrative.error or 'no API key'}). Set "
          f"`ANTHROPIC_API_KEY` to enable Claude-generated narratives._")
    L("")

    # Section 2 — Monitor metrics table (top row + fundamentals separately)
    L("## 2 · Monitor metrics")
    L("")
    L("**Primary (cross-commodity headline tiles)**")
    L("")
    L("| Metric | As of | Latest | Unit | 1d Δ | 1w Δ | 5y pctile | Headline |")
    L("|---|---|---:|---|---:|---:|---:|---|")
    for metric in TOP_ROW_METRICS:
        L(_row(metric, data.get(metric.key)))
    L("")
    if FUNDAMENTALS_METRICS:
        L("**Fundamentals inputs** _(feed derived metrics; not separately traded)_")
        L("")
        L("| Metric | As of | Latest | Unit | 1d Δ | 1w Δ | 5y pctile | Headline |")
        L("|---|---|---:|---|---:|---:|---:|---|")
        for metric in FUNDAMENTALS_METRICS:
            L(_row(metric, data.get(metric.key)))
        L("")
    L(f"_Spreads → abs EUR/MWh deltas; others → pct. Weekly Δ uses 5d trailing means. "
      f"Full history in `data/<metric>.csv`._")
    L("")

    # Section 3 — Gas + LNG arb
    L("## 3 · Gas + LNG arb")
    L("")
    ttf = data.get("ttf")
    storage = data.get("storage")
    if ttf is not None and not ttf.empty:
        sig = signal_for("ttf", ttf)
        L(f"**TTF front-month** prints at {stats.latest(ttf):.2f} EUR/MWh — _{sig.headline}_.")
    if storage is not None and not storage.empty:
        sig = signal_for("storage", storage)
        sd = stats.seasonal_deviation_pp(storage)
        sd_text = f" ({sd:+.1f} pp vs 5-yr seasonal avg)" if sd is not None else ""
        L(f"**EU storage** at {stats.latest(storage):.1f}% full{sd_text} — _{sig.headline}_.")
    # LNG arb sentence — Cobblestone trades pipeline gas + LNG; TTF − JKM is
    # the cleanest single read on Europe-vs-Asia LNG flow direction.
    ttf_jkm = data.get("ttf_jkm_spread")
    jkm = data.get("jkm")
    if ttf_jkm is not None and not ttf_jkm.empty:
        gap = stats.latest(ttf_jkm)
        side = (
            "TTF richer than JKM — LNG cargoes favour Europe"
            if gap > 0 else
            "JKM richer than TTF — Asia pulls cargoes, marginal European tightening risk"
            if gap < 0 else "TTF and JKM at parity — no clear LNG arbitrage pull"
        )
        jkm_last_str = ""
        if jkm is not None and not jkm.empty:
            jkm_last_str = f" (JKM {stats.latest(jkm):.2f} USD/MMBtu)"
        L(f"**TTF − JKM (LNG arb)** at {gap:+.2f} EUR/MWh{jkm_last_str} — {side}.")
    L("")
    # 02_gas_storage chart intentionally omitted from the rendered note to
    # hold the brief at <=3 pages once Scenarios + This-week-ahead were
    # added. PNG remains in `charts/` for the dashboard / online deck.

    # Section 4 — Carbon (price + supply/policy signal — AI first, fact-pack fallback)
    L("## 4 · Carbon (EU ETS)")
    L("")
    eua = data.get("eua")
    if eua is not None and not eua.empty:
        sig = signal_for("eua", eua)
        L(f"**EUA December** prints at {stats.latest(eua):.2f} EUR/tCO2 — _{sig.headline}_. "
          f"A euro of EUA adds ~0.37 EUR/MWh to gas-fired and ~0.85 EUR/MWh to coal-fired "
          f"generation cost; strength compresses the dark spread faster than the spark.")
        L("")
        # The Cobblestone emissions desk trades across European AND UK markets,
        # so the EU-only price read above is incomplete. One structural
        # sentence acknowledges UKA without fabricating a price (no free,
        # reliable UKA daily print available right now — see Methodology).
        L("**EU vs UK ETS** — Cobblestone's emissions desk trades EUA and UKA. "
          "Post-Brexit auction reform narrowed the UKA discount to EUA from £20+/t to "
          "single-digit £/t; CBAM phase-in pulls UK compliance demand toward parity. "
          "EUA−UKA basis remains a tradable cross-market signal.")
        L("")

    # Supply / policy signal — prefer AI extract, fall back to hand-maintained fact pack.
    # Brief's literal wording: "carbon supply/policy signal".
    cps = (narrative.extract or {}).get("carbon_policy_signal") if narrative.extract else None
    cps_source_kind = None  # "ai-extract" | "fact-pack" | None
    if cps and isinstance(cps, dict) and cps.get("item"):
        cps_source_kind = "ai-extract"
    else:
        try:
            from data import policy_facts
            fact = policy_facts.select()
            if fact is not None:
                cps = {
                    "item": fact.item,
                    "side": fact.side,
                    "polarity": fact.polarity,
                    "source": fact.source,
                    "why_it_matters": fact.why_it_matters,
                }
                cps_source_kind = "fact-pack"
        except Exception as e:
            log.warning("policy_facts fallback unavailable: %s", e)

    if cps and isinstance(cps, dict) and cps.get("item"):
        polarity = cps.get("polarity", "")
        polarity_label = (
            "bullish EUA" if polarity == "bullish-eua"
            else "bearish EUA" if polarity == "bearish-eua"
            else "neutral"
        )
        L(f"**Supply / policy signal** — _{cps['item']}_  ")
        L(f"Side: `{cps.get('side','')}` · Polarity: `{polarity_label}` · Source: {cps.get('source','')}")
        if cps.get("why_it_matters"):
            L("")
            L(cps["why_it_matters"])
        L("")
        if cps_source_kind == "ai-extract":
            L(f"_Surfaced from today's news flow by the AI extract pass "
              f"(`ai/prompts/extract_v1.md` → `carbon_policy_signal`)._")
        else:
            try:
                from data import policy_facts
                stale_age = policy_facts.days_since_review()
                stale_note = (
                    f" Fact pack last reviewed {policy_facts.LAST_REVIEWED} ({stale_age}d ago)."
                )
            except Exception:
                stale_note = ""
            L(f"_No ETS-relevant news surfaced today — falling back to "
              f"`data/policy_facts.py` (hand-maintained structural fact pack).{stale_note}_")
        L("")

    # Chart 03 (EUA Carbon) intentionally omitted from the desk note to stay
    # within the brief's 1–3 page limit; the PNG is still generated and lives
    # in `charts/` for the dashboard, the website, and any deeper drill-down.

    # Section 5 — Power: DA & curve
    L("## 5 · Power — Day-Ahead & curve")
    L("")
    de = data.get("de_power")
    gb = data.get("gb_power")
    cs = data.get("clean_spark")
    coal = data.get("coal")
    cal1 = data.get("de_cal1_proj")

    if de is not None and not de.empty:
        sig = signal_for("de_power", de)
        L(f"**DE day-ahead baseload** at {stats.latest(de):.2f} EUR/MWh — _{sig.headline}_.")
    if gb is not None and not gb.empty:
        sig = signal_for("gb_power", gb)
        L(f"**GB day-ahead baseload** at {stats.latest(gb):.2f} EUR/MWh — _{sig.headline}_.")
    if de is not None and not de.empty and gb is not None and not gb.empty:
        gap = stats.latest(de) - stats.latest(gb)
        side = "DE premium" if gap > 0 else "GB premium"
        L(f"**DE − GB spread** at {gap:+.2f} EUR/MWh ({side}) — drives interconnector flow direction.")
    L("")

    # Anchor on spark spread alone — the Clean Dark / coal-in-the-money assertion
    # depended on coal data that's currently 130+ days stale. Mention coal only as
    # a fundamentals input that is not currently usable. (See task #3 in TASKS.md.)
    if cs is not None and not cs.empty:
        cs_l = stats.latest(cs)
        cs_sig = signal_for("clean_spark", cs)
        L(f"**Clean spark spread** at {cs_l:+.2f} EUR/MWh — _{cs_sig.headline}_. "
          f"Bridge from gas + carbon fundamentals to gas-fired economics; sustained positive "
          f"spark = TTF moves transmit directly into the power curve.")
        L("")
        if coal is not None and not coal.empty and stats.is_stale(coal, STALE_AFTER_DAYS):
            L(f"_Dark spread suppressed: coal data {stats.days_since_latest(coal)}d old "
              f"(last {coal.index.max().date()}); spark alone carries the regime read._")
            L("")

    # Single curve sentence covering DA + all five forward tenors. Merging
    # the prior "DA / Cal+1 (model)" line and the multi-tenor strip into one
    # sentence saves ~3 lines and keeps the brief at <=3 pages once the new
    # UKA + LNG + risk-framing additions land. Source: ui/curve.py helpers
    # so the desk note and the dashboard strip stay in lockstep.
    try:
        from ui.curve import collect_strip_points, classify_curve_regime
        da_lvl, strip_pts = collect_strip_points(data)
    except Exception as e:
        log.info("curve strip unavailable for desk note: %s", e)
        da_lvl, strip_pts = None, []
    if da_lvl is not None and strip_pts:
        shape_label = classify_curve_regime(da_lvl, strip_pts)
        ordered = [("DA", da_lvl), *strip_pts]
        tenor_labels = " → ".join(lab for lab, _ in ordered)
        tenor_levels = " / ".join(f"{lv:.0f}" for _, lv in ordered)
        # DA-vs-Cal+1 spread named explicitly so the regime call is auditable.
        cal1_pt = next((lv for lab, lv in strip_pts if lab == "Cal+1"), None)
        spread_clause = ""
        if cal1_pt is not None:
            spread_clause = f" (DA −Cal+1 spread {da_lvl - cal1_pt:+.0f} EUR/MWh)"
        L(f"**Curve shape:** {tenor_labels} = {tenor_levels} EUR/MWh — "
          f"**{shape_label}**{spread_clause}. Forwards are seasonality projections "
          f"— see Methodology.")
        L("")

    chart = next((c for c in charts if c.name.startswith("01_")), None)
    if chart:
        L(f"![Clean Spreads]({chart.relative_to(today_dir)})")
        L("")

    # This-week-ahead release calendar — static recurring events from
    # data/release_calendar.py, plus AI-extracted dated items if any.
    try:
        from data import release_calendar
        upcoming = release_calendar.select_for_week(max_items=3)
    except Exception as e:
        log.warning("release_calendar unavailable: %s", e)
        upcoming = []

    ai_dated = (narrative.extract or {}).get("watchlist_dated") if narrative.extract else None
    if upcoming or (isinstance(ai_dated, list) and ai_dated):
        L("**This week ahead**")
        L("")
        for ev in upcoming:
            time_str = f" {ev.time_utc} UTC" if ev.time_utc else ""
            L(f"- **{release_calendar.label_weekday(ev.weekday)}**{time_str} — "
              f"{ev.name}: {ev.relevance}")
        if isinstance(ai_dated, list):
            for item in ai_dated[:2]:
                if not isinstance(item, dict):
                    continue
                day = item.get("day_label", "—")
                name = item.get("name", "")
                why = item.get("why", "")
                if name or why:
                    L(f"- **{day}** — {name}{': ' + why if why else ''} "
                      f"_(news-extracted)_")
        L("")

    # Scenarios block — AI-generated Base / Upside / Downside on the
    # dominant geopolitical risk axis. Quantified TTF + DE Power moves.
    scenarios = (narrative.extract or {}).get("scenarios") if narrative.extract else None
    if isinstance(scenarios, dict) and all(
        k in scenarios for k in ("base", "upside", "downside")
    ):
        horizon = scenarios.get("horizon", "24-72h")
        L(f"**Scenarios ({horizon} horizon)**")
        L("")
        L("| | Summary | TTF | DE Power |")
        L("|---|---|---:|---:|")
        for label, key in (("Base", "base"), ("Upside", "upside"), ("Downside", "downside")):
            sc = scenarios.get(key) or {}
            L(
                f"| **{label}** | {sc.get('summary', '—')} "
                f"| {sc.get('ttf_pct', '—')} | {sc.get('de_power_pct', '—')} |"
            )
        L("")
        L("_Illustrative, not forecasts. Magnitudes sized off historical sensitivity; "
          "AI-generated from today's extract pass._")
        L("")

    # Section 6 — folded into the Monitor table renewables row to keep
    # the brief at <=3 pages once the Scenarios + This-week-ahead blocks
    # were added in §5. Section number kept for stable numbering of §7
    # and §8 in the README; section header omitted from the rendered note.
    # Chart 05 (renewable share) intentionally omitted from the desk note for
    # the page-count fit; PNG remains in `charts/` for the dashboard.

    # Section 7 — Today's themes (compressed: 1-line backdrop + 2-4 watchlist bullets,
    # no per-headline table; full structured news in output/<date>/data/ai_news_themes.json).
    L("## 6 · Today's themes")
    L("")
    if news_themes is not None and (news_themes.geopolitics_summary or news_themes.themes):
        # Backdrop sentence intentionally suppressed in the rendered note —
        # the TL;DR + narrative paragraph in §1 already carry the geopolitical
        # picture. Full geopolitics_summary stays in `ai_news_themes.json`.
        if news_themes.watchlist:
            L("**Watchlist (1–4 weeks)**")
            for w in news_themes.watchlist[:2]:
                L(f"- {w}")
            L("")
        n_themes = len(news_themes.themes) if news_themes.themes else 0
        if news_themes.source.startswith("claude"):
            L(f"_{n_themes} structured themes in `data/ai_news_themes.json` — "
              f"**{news_themes.model}** from {news_themes.n_headlines_in} headlines._")
        else:
            L(f"_News themes via rule-based fallback ({news_themes.error or 'no API key'})._")
        L("")
    else:
        L("> _News theme extraction unavailable today. Structured output lands in "
          "`data/ai_news_themes.json` when live._")
        L("")

    tag = cross_market_tag(data)
    if tag:
        L(f"> **Cross-market regime tag:** {tag}")
        L("")

    # Risk framing — paraphrases Cobblestone's 4-pillar risk language
    # ("Disciplined Risk Framework / Integrated Controls / Continuous
    # Monitoring / Operational Reliability") in one short italic line.
    # Recognisable to a Cobblestone reviewer without verbatim copy-paste.
    L("_Risk framing — built within a discipline of clear limits and continuous "
      "monitoring; observations here are framed as risk inputs, not directional "
      "calls. Positioning decisions remain with the desk._")

    # Methodology rolled into a single italic footer line (no horizontal rule,
    # no preceding blank) so the brief sits within 3 pages once §5 Scenarios +
    # watchlist blocks are present. Full methodology lives in README §Methodology.
    L("_Methodology + sources: **README §Methodology**. Numbers auditable via the "
      "snapshot JSONs. Rule-based / informational — not investment advice._")

    md_path = today_dir / f"desk_note_{today_str}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def render_pdf(md_path: Path) -> Path | None:
    """Render the markdown to PDF via pandoc + xelatex if available."""
    if shutil.which("pandoc") is None:
        log.info("pandoc not on PATH; skipping PDF render. Install via `brew install pandoc`.")
        return None
    pdf_path = md_path.with_suffix(".pdf")
    cmd = [
        "pandoc", str(md_path),
        "-o", str(pdf_path),
        "--pdf-engine=xelatex",
        "-V", "geometry:margin=0.5in",
        "-V", "mainfont=Helvetica",
        "-V", "fontsize=9pt",
        f"--resource-path={md_path.parent}",
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
        return pdf_path
    except subprocess.CalledProcessError as e:
        log.warning("pandoc failed: %s", e.stderr[:300] if e.stderr else e)
        return None
    except Exception as e:
        log.warning("PDF render failed: %s", e)
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the daily energy desk note.")
    parser.add_argument("--out-root", default="output",
                        help="Output base directory (default: output).")
    parser.add_argument("--single-pass", action="store_true",
                        help="Use single-pass AI narrative (default: two-pass).")
    parser.add_argument("--no-news", action="store_true",
                        help="Skip news fetching and theme extraction.")
    parser.add_argument("--pdf", action="store_true",
                        help="Also render the desk note to PDF (requires pandoc).")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s · %(message)s",
        datefmt="%H:%M:%S",
    )

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_root = (REPO_ROOT / args.out_root).resolve()
    today_dir = out_root / today
    data_dir = today_dir / "data"
    charts_dir = today_dir / "charts"
    today_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== {SUBMISSION_TITLE} ===")
    print(f"Date: {today}")
    print(f"Out:  {today_dir}\n")

    print("[1/6] Fetching public data ...")
    data = fetch_all()
    for metric in METRICS:
        df = data.get(metric.key)
        suffix = "  (input)" if metric.is_fundamentals_input else ""
        if df is not None and not df.empty:
            print(f"   ✓ {metric.short_name:14s} {len(df):>5} rows · "
                  f"latest {df.index.max().date()} = "
                  f"{df['value'].iloc[-1]:.2f} {metric.unit}{suffix}")
        else:
            print(f"   ✗ {metric.short_name:14s} no data{suffix}")

    print("\n[2/6] Writing cleaned dataset CSVs ...")
    snap_csv = write_csvs(data, data_dir)
    print(f"   ✓ {snap_csv.relative_to(today_dir)}")

    print("\n[3/6] Generating charts ...")
    charts = [
        plot_clean_spreads(data, charts_dir),
        plot_gas_vs_storage(data, charts_dir),
        plot_eua_carbon(data, charts_dir),
        plot_de_gb_power(data, charts_dir),
        plot_renewable_share(data, charts_dir),
    ]
    charts = [c for c in charts if c]
    for c in charts:
        print(f"   ✓ {c.relative_to(today_dir)}")

    # News + theme extraction (skippable for fast iteration)
    news_themes = None
    if not args.no_news:
        print("\n[4/6] Fetching news + extracting themes ...")
        try:
            headlines = news.fetch_headlines()
            print(f"   fetched {len(headlines)} headlines")
            news_themes = extract_themes(headlines)
            print(f"   themes: {len(news_themes.themes)} · source: {news_themes.source}")
            news_path = data_dir / "ai_news_themes.json"
            news_payload = {
                "geopolitics_summary": news_themes.geopolitics_summary,
                "themes": news_themes.themes,
                "watchlist": news_themes.watchlist,
                "source": news_themes.source,
                "model": news_themes.model,
                "n_headlines_in": news_themes.n_headlines_in,
                "error": news_themes.error,
            }
            news_path.write_text(json.dumps(news_payload, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
            print(f"   ✓ {news_path.relative_to(today_dir)}")
        except Exception as e:
            log.warning("news pipeline failed: %s — continuing without news", e)
            news_themes = None
    else:
        print("\n[4/6] News step skipped (--no-news)")

    # Save AI snapshot (the JSON sent to the extract pass)
    from ai.narrative import _snapshot
    news_dict = None
    if news_themes is not None and (news_themes.themes or news_themes.geopolitics_summary):
        news_dict = {
            "geopolitics_summary": news_themes.geopolitics_summary,
            "themes": news_themes.themes,
            "watchlist": news_themes.watchlist,
        }
    snap_json = data_dir / "ai_snapshot.json"
    snap_json.write_text(
        json.dumps(_snapshot(data, news=news_dict), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"   ✓ {snap_json.relative_to(today_dir)}")

    print(f"\n[5/6] Calling AI for narrative ({'single-pass' if args.single_pass else 'two-pass'}) ...")
    narrative = generate_narrative(data, two_pass=not args.single_pass, news=news_dict)
    print(f"   source: {narrative.source}" +
          (f" · model: {narrative.model}" if narrative.model else ""))
    if narrative.error:
        print(f"   note:   {narrative.error}")
    if narrative.top_takeaway:
        print(f"   tldr:   {narrative.top_takeaway}")
    print(f"   text:   {narrative.text[:200]}{'...' if len(narrative.text) > 200 else ''}")

    if narrative.extract is not None:
        themes_path = data_dir / "ai_themes.json"
        themes_path.write_text(
            json.dumps(narrative.extract, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"   ✓ extract saved: {themes_path.relative_to(today_dir)}")

    print("\n[6/6] Composing Markdown desk note ...")
    md_path = build_markdown(data, narrative, news_themes, charts, snap_csv, today_dir, today)
    print(f"   ✓ {md_path.relative_to(out_root)}")

    if args.pdf:
        pdf_path = render_pdf(md_path)
        if pdf_path:
            print(f"   ✓ PDF: {pdf_path.relative_to(out_root)}")

    print(f"\n✅ Done.  Open: {md_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
