"""Derived cross-commodity metrics.

These bridge the public inputs into trading-relevant signals:
- Clean Spark Spread — gas-fired plant margin
- Clean Dark Spread — coal-fired plant margin (coal is a fundamentals input only)
- Switching TTF — gas price at which CCGT and coal plant break even
- Renewable share — wind+solar forecast / load forecast
- DE−GB power spread — Continent-vs-Island day-ahead differential

Plant assumptions (η, EF, calorific) live in config.py for auditable single-source.
"""
from __future__ import annotations

import pandas as pd

from config import (
    COAL_CALORIFIC_MWH_PER_T,
    COAL_EFFICIENCY,
    COAL_EMISSION_FACTOR,
    GAS_EFFICIENCY,
    GAS_EMISSION_FACTOR,
)


def align_daily(dfs: list[pd.DataFrame], ffill_limit: int = 5) -> list[pd.DataFrame]:
    """Reindex multiple daily DataFrames to a common date union, ffill small gaps."""
    if not dfs:
        return []
    union = sorted(set().union(*[df.index for df in dfs if df is not None]))
    if not union:
        return [pd.DataFrame(columns=["value"]) for _ in dfs]
    idx = pd.DatetimeIndex(union)
    return [df.reindex(idx).ffill(limit=ffill_limit) for df in dfs]


def clean_spark_spread(
    power: pd.DataFrame,
    gas: pd.DataFrame,
    carbon: pd.DataFrame,
) -> pd.DataFrame:
    """CSS = Power − Gas / η_gas − Carbon × (EF_gas / η_gas)"""
    if any(df is None or df.empty for df in (power, gas, carbon)):
        return pd.DataFrame(columns=["value"])
    p, g, c = align_daily([power, gas, carbon])
    eff_emission = GAS_EMISSION_FACTOR / GAS_EFFICIENCY
    df = pd.DataFrame(index=p.index)
    df["value"] = p["value"] - g["value"] / GAS_EFFICIENCY - c["value"] * eff_emission
    df.index.name = "date"
    df.attrs["formula"] = (
        f"P - G/{GAS_EFFICIENCY:.2f} - C × {eff_emission:.3f}  "
        f"(η_gas={GAS_EFFICIENCY}, EF_gas={GAS_EMISSION_FACTOR} tCO2/MWh_th)"
    )
    return df.dropna()


def clean_dark_spread(
    power: pd.DataFrame,
    coal_usd_t: pd.DataFrame,
    carbon: pd.DataFrame,
    eurusd: pd.DataFrame,
) -> pd.DataFrame:
    """CDS = Power − Coal_EUR_per_MWh_th / η_coal − Carbon × (EF_coal / η_coal)"""
    if any(df is None or df.empty for df in (power, coal_usd_t, carbon, eurusd)):
        return pd.DataFrame(columns=["value"])
    p, coal, c, fx = align_daily([power, coal_usd_t, carbon, eurusd])
    coal_eur_per_mwh_th = (coal["value"] / fx["value"]) / COAL_CALORIFIC_MWH_PER_T
    eff_emission = COAL_EMISSION_FACTOR / COAL_EFFICIENCY
    df = pd.DataFrame(index=p.index)
    df["value"] = p["value"] - coal_eur_per_mwh_th / COAL_EFFICIENCY - c["value"] * eff_emission
    df.index.name = "date"
    df.attrs["formula"] = (
        f"P - (Coal_USD/FX/{COAL_CALORIFIC_MWH_PER_T:.2f})/{COAL_EFFICIENCY:.2f} "
        f"- C × {eff_emission:.3f}  (η_coal={COAL_EFFICIENCY}, EF_coal={COAL_EMISSION_FACTOR})"
    )
    return df.dropna()


def fuel_switch_indicator(clean_spark: pd.DataFrame, clean_dark: pd.DataFrame) -> pd.DataFrame:
    """CDS − CSS: positive ⇒ coal in-the-money vs gas, negative ⇒ gas wins."""
    if any(df is None or df.empty for df in (clean_spark, clean_dark)):
        return pd.DataFrame(columns=["value"])
    cs, cd = align_daily([clean_spark, clean_dark])
    df = pd.DataFrame(index=cs.index)
    df["value"] = cd["value"] - cs["value"]
    df.index.name = "date"
    return df.dropna()


def switching_ttf(
    coal_usd_t: pd.DataFrame,
    carbon: pd.DataFrame,
    eurusd: pd.DataFrame,
) -> pd.DataFrame:
    """Switching TTF = η_gas · ( Coal_EUR/η_coal + (EF_coal/η_coal − EF_gas/η_gas) · EUA )

    The TTF gas price at which a CCGT exactly matches a hard-coal plant in
    the merit order. TTF − Switching TTF is fuel-switch headroom in EUR/MWh.
    Computed on demand for the regime strip; not a registered top-row metric.
    """
    if any(df is None or df.empty for df in (coal_usd_t, carbon, eurusd)):
        return pd.DataFrame(columns=["value"])
    coal, c, fx = align_daily([coal_usd_t, carbon, eurusd])
    coal_eur_per_mwh_th = (coal["value"] / fx["value"]) / COAL_CALORIFIC_MWH_PER_T
    diff = COAL_EMISSION_FACTOR / COAL_EFFICIENCY - GAS_EMISSION_FACTOR / GAS_EFFICIENCY
    df = pd.DataFrame(index=coal.index)
    df["value"] = GAS_EFFICIENCY * (coal_eur_per_mwh_th / COAL_EFFICIENCY + diff * c["value"])
    df.index.name = "date"
    df.attrs["formula"] = (
        f"η_gas·(Coal_EUR/η_coal + (EF_coal/η_coal − EF_gas/η_gas)·EUA)"
    )
    return df.dropna()


def renewable_share_of_load(
    wind_solar_forecast: pd.DataFrame,
    load_forecast: pd.DataFrame,
) -> pd.DataFrame:
    """Wind+solar / load × 100 (%). Already aligned daily series in MW."""
    if any(df is None or df.empty for df in (wind_solar_forecast, load_forecast)):
        return pd.DataFrame(columns=["value"])
    rs, ld = align_daily([wind_solar_forecast, load_forecast])
    df = pd.DataFrame(index=rs.index)
    df["value"] = (rs["value"] / ld["value"]) * 100.0
    df.index.name = "date"
    return df.dropna()


def power_spread(
    a: pd.DataFrame,
    b: pd.DataFrame,
) -> pd.DataFrame:
    """Generic power spread: A − B, both in EUR/MWh on the same day grid."""
    if any(df is None or df.empty for df in (a, b)):
        return pd.DataFrame(columns=["value"])
    da, db = align_daily([a, b])
    df = pd.DataFrame(index=da.index)
    df["value"] = da["value"] - db["value"]
    df.index.name = "date"
    return df.dropna()


def ttf_jkm_spread(
    ttf_eur_per_mwh: pd.DataFrame,
    jkm_usd_per_mmbtu: pd.DataFrame,
    eurusd: pd.DataFrame,
) -> pd.DataFrame:
    """TTF − JKM spread (EUR/MWh) — the Europe-vs-Asia LNG arbitrage signal.

    Positive ⇒ TTF rich vs JKM ⇒ LNG cargoes prefer Europe (bearish for European
    gas tightness when sustained). Negative ⇒ JKM rich ⇒ Asia draws cargoes,
    potentially tightening Europe.

    Conversion: JKM_USD_per_MMBtu × 3.41214 / EURUSD = JKM in EUR/MWh.
    All three inputs are aligned on the daily grid before subtraction.
    """
    from data.fetchers import MMBTU_PER_MWH

    if any(df is None or df.empty for df in (ttf_eur_per_mwh, jkm_usd_per_mmbtu, eurusd)):
        return pd.DataFrame(columns=["value"])
    ttf, jkm, fx = align_daily([ttf_eur_per_mwh, jkm_usd_per_mmbtu, eurusd])
    jkm_eur_per_mwh = jkm["value"] * MMBTU_PER_MWH / fx["value"]
    df = pd.DataFrame(index=ttf.index)
    df["value"] = ttf["value"] - jkm_eur_per_mwh
    df.index.name = "date"
    df.attrs["formula"] = (
        "TTF (EUR/MWh) − JKM (USD/MMBtu × 3.41214 / EURUSD)  "
        "(positive ⇒ TTF rich, LNG flows favour Europe)"
    )
    return df.dropna()


# Trading-day horizons (business days). Used by `seasonality_projection` and
# the multi-tenor curve strip in ui/curve.py. Calendar-day windows for the
# anchor lookup are derived as round((bdays / 252) * 365) so all five horizons
# share the same projection method.
HORIZON_BDAYS: dict[str, int] = {
    "w1":   5,    # Week-ahead     ≈ 5 business days
    "m1":  21,    # Month-ahead    ≈ 21 business days
    "q1":  65,    # Quarter-ahead  ≈ 65 business days
    "cal1": 252,  # Year-ahead     ≈ 252 business days
    "cal2": 504,  # Two-years-ahead ≈ 504 business days
}


def seasonality_projection(
    da_power: pd.DataFrame,
    *,
    horizon_bdays: int,
    window_days: int = 3,
    smoothing_window: int = 30,
) -> pd.DataFrame:
    """Indicative forward-tenor projection from DA seasonality.

    Model-derived **proxy** for a forward power price at any horizon — explicitly
    NOT a market quote. We don't have free access to EEX settlement curves; this
    is the closest honest substitute when only spot data is available. Trading
    desks should treat the output as direction-correct and level-indicative only.

    Method: for each historical date `t`, find the realised DA print at
    `t + N business days` (with a `±window_days` calendar-day search window to
    handle weekends/holidays) and take its mean, then apply a `smoothing_window`-
    day rolling mean to dampen single-day spikes. The calendar-day offset used
    for the lookup is `round((horizon_bdays / 252) * 365)` — i.e. the same
    horizon expressed as calendar days, so W+1 = 7, M+1 = 30, Q+1 = ~94,
    Cal+1 = 365, Cal+2 = 730.

    Seasonality assumption (load-bearing, document this when shipping):
        Future power realises with a price level similar to what was historically
        observed at the same calendar offset, modulo a 30-day smoothing window.
        This holds tolerably well for short tenors where weather and load shape
        dominate, and degrades for long tenors where regime shifts (carbon
        policy, fuel-price step-changes, structural supply changes) matter more
        than seasonality. Cal+1 / Cal+2 readings are most useful as a
        backwardation/contango regime tell, not as a forecast of absolute level.

    Caveats:
    - Backward-looking: projects via realised seasonality, not market expectations.
      A real forward prices in current expectations of carbon, gas, weather, demand.
    - Mean-reversion bias: averaging dampens regime shifts that would show up
      immediately in a real forward.
    - Useful for: "is today's DA elevated vs what same-tenor realisation has
      typically looked like in this calendar window?"

    Args:
        da_power: tidy daily DA power series with a "value" column.
        horizon_bdays: forward horizon in business days. See HORIZON_BDAYS.
        window_days: ± calendar-day search window around the horizon anchor.
        smoothing_window: rolling-mean window applied to the projection series.

    Returns:
        Tidy DataFrame indexed on the *anchor date* (i.e. each row's value is
        the historical realisation at +horizon from that anchor). Empty when
        the input is shorter than the horizon.
    """
    if da_power is None or da_power.empty:
        return pd.DataFrame(columns=["value"])
    s = da_power["value"].dropna().sort_index()

    # Calendar-day offset matched to business-day horizon so the projection
    # works the same regardless of which tenor is requested.
    horizon_cal_days = max(1, round((horizon_bdays / 252.0) * 365.0))
    if len(s) < horizon_cal_days + 1:
        return pd.DataFrame(columns=["value"])

    rows = []
    for date in s.index:
        target = date + pd.Timedelta(days=horizon_cal_days)
        window = s[(s.index >= target - pd.Timedelta(days=window_days)) &
                   (s.index <= target + pd.Timedelta(days=window_days))]
        if window.empty:
            continue
        rows.append({"date": date, "value": float(window.mean())})

    if not rows:
        return pd.DataFrame(columns=["value"])
    proj = pd.DataFrame(rows).set_index("date")
    proj.index.name = "date"
    proj.index = pd.to_datetime(proj.index)
    proj["value"] = proj["value"].rolling(smoothing_window, min_periods=1).mean()
    proj.attrs["model_note"] = (
        f"Indicative DA-implied {horizon_bdays}-bday-ahead level via seasonality. "
        f"Not a market quote — direction-correct, level-indicative only."
    )
    proj.attrs["horizon_bdays"] = horizon_bdays
    return proj.dropna()


def cal1_seasonality_projection(
    da_power: pd.DataFrame,
    *,
    lookback_years: int = 5,
    smoothing_window: int = 30,
) -> pd.DataFrame:
    """Backwards-compatible Cal+1 wrapper around `seasonality_projection`.

    Kept as a named entry point because external callers (the desk-note
    template, the regime strip, parquet snapshot keys) still reference
    `de_cal1_proj` by name. Internally re-anchored on the generalised function
    so all forward horizons share one implementation.
    """
    del lookback_years  # accepted for API parity; horizon is fixed at 1y
    return seasonality_projection(
        da_power,
        horizon_bdays=HORIZON_BDAYS["cal1"],
        smoothing_window=smoothing_window,
    )
