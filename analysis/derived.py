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
