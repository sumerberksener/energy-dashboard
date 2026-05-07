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
    # Section 5's "DA / Cal+1 (model)" line consumes this; without it the
    # forward-curve indication silently disappears from the desk note.
    primaries["de_cal1_proj"] = derived_metrics.cal1_seasonality_projection(
        primaries["de_power"]
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
    L("")
    chart = next((c for c in charts if c.name.startswith("02_")), None)
    if chart:
        L(f"![Gas vs Storage]({chart.relative_to(today_dir)})")
        L("")

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
          f"This is the bridge from gas + carbon fundamentals to gas-fired plant economics; "
          f"sustained positive spark = gas is in-the-money and TTF moves transmit directly "
          f"into the power curve.")
        L("")
        if coal is not None and not coal.empty and stats.is_stale(coal, STALE_AFTER_DAYS):
            L(f"_The dark spread (and any coal-vs-gas merit-order claim) is suppressed "
              f"this morning: coal data is {stats.days_since_latest(coal)} days old "
              f"(last {coal.index.max().date()}), so the merit-order signal is indicative "
              f"not current. Spark alone carries the regime read above._")
            L("")

    # Forward curve from cal1_seasonality_projection — the brief's "Day-Ahead to curve"
    # output. Model-derived (see Methodology), not a market quote.
    if (de is not None and not de.empty and cal1 is not None and not cal1.empty):
        de_l = stats.latest(de)
        cal1_l = stats.latest(cal1)
        spread = de_l - cal1_l
        if spread > 1:
            curve_regime = "**backwardation**"
        elif spread < -1:
            curve_regime = "**contango**"
        else:
            curve_regime = "flat"
        L(f"**DA / Cal+1 (model)** at {de_l:.2f} / {cal1_l:.2f} EUR/MWh; spread "
          f"{spread:+.2f} EUR/MWh — {curve_regime}. Front absorbs storage and outage shocks; "
          f"Cal+1 reflects the structural carbon-and-fuel trajectory. Cal+1 here is a "
          f"backward-looking seasonality projection — see Methodology.")
        L("")

    chart = next((c for c in charts if c.name.startswith("01_")), None)
    if chart:
        L(f"![Clean Spreads]({chart.relative_to(today_dir)})")
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
        L("_Scenarios are illustrative, not forecasts. Magnitudes sized off "
          "historical sensitivity of TTF / DE Power to comparable shocks; AI-generated "
          "from the extract pass on today's news flow + metric snapshot._")
        L("")

    # Section 6 — Short-term drivers
    L("## 6 · Short-term drivers")
    L("")
    rs = data.get("renewable_share")
    if rs is not None and not rs.empty:
        sig = signal_for("renewable_share", rs)
        rs_last = stats.latest(rs)
        L(f"**DE wind + solar forecast** at {rs_last:.1f}% of load — _{sig.headline}_. "
          f"Largest day-ahead price driver after gas: high share compresses the residual-load "
          f"curve and pushes prices down (or negative); low share lifts gas-fired plants into "
          f"the merit order, making TTF + EUA the binding constraint.")
        L("")
    # Chart 05 (renewable share) intentionally omitted from the desk note for
    # the page-count fit; PNG remains in `charts/` for the dashboard.

    # Section 7 — Today's themes (compressed: 1-line backdrop + 2-4 watchlist bullets,
    # no per-headline table; full structured news in output/<date>/data/ai_news_themes.json).
    L("## 7 · Today's themes")
    L("")
    if news_themes is not None and (news_themes.geopolitics_summary or news_themes.themes):
        if news_themes.geopolitics_summary:
            L(f"**Backdrop**: {news_themes.geopolitics_summary}")
            L("")
        if news_themes.watchlist:
            L("**Watchlist (1–4 weeks)**")
            for w in news_themes.watchlist[:4]:
                L(f"- {w}")
            L("")
        n_themes = len(news_themes.themes) if news_themes.themes else 0
        if news_themes.source.startswith("claude"):
            L(f"_{n_themes} structured themes (tag · commodity · polarity · why) "
              f"in `data/ai_news_themes.json` — generated by **{news_themes.model}** from "
              f"{news_themes.n_headlines_in} headlines._")
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

    # Section 8 — single line; full methodology in README. Saves a page.
    L("## 8 · Methodology")
    L("")
    L("See **README §Methodology** in the repo for sources, plant assumptions, formulas, "
      "signal thresholds, AI workflow, and the policy fact-pack used for Section 4. "
      "Every number above is auditable via the snapshot JSONs in this directory.")
    L("")
    L("_Observations are rule-based and informational, not investment advice._")
    L("")

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
        "-V", "geometry:margin=0.6in",
        "-V", "mainfont=Helvetica",
        "-V", "fontsize=10pt",
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
