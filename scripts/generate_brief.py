"""Headless CLI: pulls public data, generates charts, calls the AI, writes a desk note.

Usage:
    python scripts/generate_brief.py [--out-root output]

Outputs (under output/<YYYY-MM-DD>/):
    desk_note_<YYYY-MM-DD>.md   1–3 page Markdown desk note (the deliverable)
    data/snapshot.csv           today's pivot table of all metrics
    data/<metric>.csv           full 5-year history per metric
    charts/01_*.png             three generated charts referenced by the note

The CLI is the automated reporting workflow described in the brief; the
Streamlit app at app.py is the interactive view of the same data.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless — no display
import matplotlib.pyplot as plt
import pandas as pd

# Make repo importable when run as `python scripts/generate_brief.py`
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ai.narrative import generate_narrative  # noqa: E402
from analysis import derived as derived_metrics  # noqa: E402
from analysis import stats  # noqa: E402
from analysis.signals import cross_market_tag, signal_for  # noqa: E402
from config import (  # noqa: E402
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    METRICS,
    METRICS_BY_KEY,
    STALE_AFTER_DAYS,
    SUBMISSION_TITLE,
)
from data import fetchers  # noqa: E402

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
    primaries["switching_ttf"] = derived_metrics.switching_ttf(
        primaries["coal"], primaries["eua"], eurusd
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
            "value": stats.latest(df),
            "unit": metric.unit,
            "percentile_5y": stats.percentile_rank(df),
        }
        if metric.delta_unit == "abs":
            row["daily_change_abs"] = stats.daily_change_abs(df)
            row["weekly_change_abs"] = stats.change_over_abs(df, 5, smooth_window=5)
            row["monthly_change_abs"] = stats.change_over_abs(df, 21)
        else:
            row["daily_change_pct"] = stats.daily_change_pct(df)
            row["weekly_change_pct"] = stats.change_over_pct(df, 5, smooth_window=5)
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
    fig, ax = plt.subplots(figsize=(10, 5))
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
    fig, ax = plt.subplots(figsize=(10, 5))
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
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(s.index, s["value"], color="#40a02b", linewidth=2)
    _setup_axes(ax, "EUA December Carbon Futures — 2Y", "EUR/tCO2")
    fig.tight_layout()
    p = charts_dir / "03_eua_carbon.png"
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
        w1 = stats.change_over_abs(df, 5, smooth_window=5)
        d1_s = _fmt_abs(d1)
        w1_s = _fmt_abs(w1)
    else:
        d1 = stats.daily_change_pct(df)
        w1 = stats.change_over_pct(df, 5, smooth_window=5)
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
    L(f"_Generated by `scripts/generate_brief.py`. AI narrative via Anthropic Claude._")
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
          f"Numbers below should be read with this in mind. The free-data sources "
          f"for these series are flaky — see methodology section.")
        L("")

    L("## 1 · Executive summary")
    L("")
    if narrative.top_takeaway:
        L(f"**TL;DR — {narrative.top_takeaway}**")
        L("")
    L(narrative.text)
    L("")
    if narrative.source == "claude" or narrative.source == "claude-two-pass":
        passes = "two-pass extract→narrate" if narrative.source == "claude-two-pass" else "single-pass"
        L(f"_Generated by **{narrative.model}** via Anthropic API ({passes}). "
          f"Prompts/responses logged to `ai/logs/`._")
    else:
        L(f"_Rule-based fallback ({narrative.error or 'no API key'}). Set "
          f"`ANTHROPIC_API_KEY` to enable Claude-generated narratives._")
    L("")

    L("## 2 · Monitor metrics")
    L("")
    L("| Metric | As of | Latest | Unit | 1d Δ | 1w Δ | 5y pctile | Headline |")
    L("|---|---|---:|---|---:|---:|---:|---|")
    for metric in METRICS:
        L(_row(metric, data.get(metric.key)))
    L("")
    L(f"_Spreads (Clean Spark, Clean Dark) report absolute change in EUR/MWh "
      f"because pct-change is mathematically meaningless across zero. Other metrics "
      f"report pct change. Full 5-year history per metric in `data/<metric>.csv`. "
      f"Today's pivot in `{snap_csv.relative_to(today_dir)}`._")
    L("")

    L("## 3 · Gas tightness")
    L("")
    ttf = data.get("ttf")
    storage = data.get("storage")
    if ttf is not None and not ttf.empty:
        sig = signal_for("ttf", ttf)
        L(f"**TTF front-month** prints at {stats.latest(ttf):.2f} EUR/MWh — _{sig.headline}_.  ")
        L(sig.observation)
        L("")
    if storage is not None and not storage.empty:
        sig = signal_for("storage", storage)
        sd = stats.seasonal_deviation_pp(storage)
        sd_text = f" ({sd:+.1f} pp vs 5-yr seasonal avg)" if sd is not None else ""
        L(f"**EU storage** at {stats.latest(storage):.1f}% full{sd_text} — _{sig.headline}_.  ")
        L(sig.observation)
        L("")
    elif ttf is None or ttf.empty:
        L("> _TTF and EU Storage data unavailable — verify network and `AGSI_TOKEN`._")
        L("")
    else:
        L("> _EU Storage requires the free GIE AGSI+ API token. Set `AGSI_TOKEN` in "
          "the environment to populate the storage view._")
        L("")
    chart = next((c for c in charts if c.name.startswith("02_")), None)
    if chart:
        L(f"![Gas vs Storage]({chart.relative_to(today_dir)})")
        L("")

    L("## 4 · Carbon supply / policy signal")
    L("")
    eua = data.get("eua")
    if eua is not None and not eua.empty:
        sig = signal_for("eua", eua)
        L(f"**EUA December** prints at {stats.latest(eua):.2f} EUR/tCO2 — _{sig.headline}_.  ")
        L(sig.observation)
        L("")
        L("Carbon is the marginal-cost lever: a euro of EUA adds ~0.37 EUR/MWh to gas-fired and "
          "~0.85 EUR/MWh to coal-fired generation cost. Strength here compresses the dark spread "
          "faster than the spark, accelerating fuel switching toward gas.")
        L("")
    chart = next((c for c in charts if c.name.startswith("03_")), None)
    if chart:
        L(f"![EUA Carbon]({chart.relative_to(today_dir)})")
        L("")

    L("## 5 · Power-curve implications")
    L("")
    de = data.get("de_power")
    cs = data.get("clean_spark")
    cd = data.get("clean_dark")

    have_power = de is not None and not de.empty
    have_spreads = (cs is not None and not cs.empty
                    and cd is not None and not cd.empty)
    if not have_power and not have_spreads:
        L("> _DE Power and the derived clean spark/dark spreads require the free "
          "ENTSO-E API token. This section will populate once `ENTSOE_TOKEN` is "
          "set in the environment._")
        L("")

    if have_power:
        sig = signal_for("de_power", de)
        L(f"**DE day-ahead baseload** at {stats.latest(de):.2f} EUR/MWh — _{sig.headline}_.")
        L("")
    if have_spreads:
        cs_l = stats.latest(cs)
        cd_l = stats.latest(cd)
        diff = cd_l - cs_l
        if diff > 5:
            switch = "**Coal is firmly in-the-money vs gas** — coal-fired plants set the marginal cost"
        elif diff > 0:
            switch = "Coal slightly in-the-money vs gas — fuel switching is borderline"
        elif diff > -5:
            switch = "Gas slightly in-the-money vs coal — TTF moves transmit to power"
        else:
            switch = "**Gas is firmly in-the-money vs coal** — TTF is the dominant power-curve driver"
        L(f"Clean spark **{cs_l:+.2f}** · clean dark **{cd_l:+.2f}** EUR/MWh. {switch}.")
        L("")
        L("When the dark spread sits above the spark, coal-fired generation clears the merit order "
          "ahead of gas; the curve is then sensitive to coal+carbon shocks. When the spark dominates, "
          "gas anchors the curve and TTF moves transmit directly into Cal+1 power.")
        L("")
    chart = next((c for c in charts if c.name.startswith("01_")), None)
    if chart:
        L(f"![Clean Spreads]({chart.relative_to(today_dir)})")
        L("")

    tag = cross_market_tag(data)
    if tag:
        L(f"> **Cross-market regime tag:** {tag}")
        L("")

    L("## 6 · Methodology & sources")
    L("")
    L("- TTF, EUA: ICE settlements via Yahoo Finance / stooq")
    L("- DE Day-Ahead Power: ENTSO-E Transparency Platform (DE_LU bidding zone, hourly resampled to daily mean)")
    L("- EU Gas Storage: GIE AGSI+ (% full, country = EU aggregate)")
    L("- Coal: ICE Newcastle (proxy for API2; ~0.85 historical correlation). "
      "**Known limitation**: the Yahoo Newcastle ticker has been observed to lag — "
      "the freshness flag in section 2 surfaces this when it occurs. Resolved by a "
      "paid feed (Argus, Refinitiv) for production use.")
    L("- Clean spark: P − G/η_gas − C × EF_gas/η_gas, η_gas = 0.50, EF_gas = 0.184 t/MWh_th")
    L("- Clean dark: P − Coal_EUR/η_coal − C × EF_coal/η_coal, η_coal = 0.40, EF_coal = 0.34 t/MWh_th, "
      "with API2/Newcastle USD/t converted via EUR/USD and a 6.978 MWh_th/t calorific value")
    L("- AI narrative: prompt at `ai/prompts/desk_note_v1.md`, full request/response logs in `ai/logs/<date>.jsonl`")
    L("")
    L("_Observations are rule-based and informational, not investment advice._")
    L("")

    md_path = today_dir / f"desk_note_{today_str}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the daily energy desk note.")
    parser.add_argument(
        "--out-root", default="output",
        help="Output base directory relative to repo root (default: output).",
    )
    parser.add_argument(
        "--single-pass", action="store_true",
        help="Use single-pass AI narrative (default: two-pass extract→narrate).",
    )
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

    print("[1/5] Fetching public data ...")
    data = fetch_all()
    for metric in METRICS:
        df = data.get(metric.key)
        if df is not None and not df.empty:
            print(f"   ✓ {metric.short_name:14s} {len(df):>5} rows · "
                  f"latest {df.index.max().date()} = {df['value'].iloc[-1]:.2f} {metric.unit}")
        else:
            print(f"   ✗ {metric.short_name:14s} no data")

    print("\n[2/5] Writing cleaned dataset CSVs ...")
    snap_csv = write_csvs(data, data_dir)
    print(f"   ✓ {snap_csv.relative_to(today_dir)}")

    # Also save the structured snapshot the AI receives — useful audit artifact
    # even when the AI fallback path runs.
    from ai.narrative import _snapshot  # internal helper; deliberately re-used
    snap_json = data_dir / "ai_snapshot.json"
    snap_json.write_text(
        json.dumps(_snapshot(data), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"   ✓ {snap_json.relative_to(today_dir)}")

    print("\n[3/5] Generating charts ...")
    charts = [
        plot_clean_spreads(data, charts_dir),
        plot_gas_vs_storage(data, charts_dir),
        plot_eua_carbon(data, charts_dir),
    ]
    charts = [c for c in charts if c]
    for c in charts:
        print(f"   ✓ {c.relative_to(today_dir)}")

    print(f"\n[4/5] Calling AI for narrative ({'single-pass' if args.single_pass else 'two-pass'}) ...")
    narrative = generate_narrative(data, two_pass=not args.single_pass)
    print(f"   source: {narrative.source}" + (f" · model: {narrative.model}" if narrative.model else ""))
    if narrative.error:
        print(f"   note:   {narrative.error}")
    if narrative.top_takeaway:
        print(f"   tldr:   {narrative.top_takeaway}")
    print(f"   text:   {narrative.text[:200]}{'...' if len(narrative.text) > 200 else ''}")

    # Persist the structured extract from pass 1 (if two-pass succeeded).
    if narrative.extract is not None:
        themes_path = data_dir / "ai_themes.json"
        themes_path.write_text(
            json.dumps(narrative.extract, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"   ✓ extract saved: {themes_path.relative_to(today_dir)}")

    print("\n[5/5] Composing Markdown desk note ...")
    md_path = build_markdown(data, narrative, charts, snap_csv, today_dir, today)
    print(f"   ✓ {md_path.relative_to(out_root)}")

    print(f"\n✅ Done.  Open: {md_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
