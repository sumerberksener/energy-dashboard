"""Derived cross-commodity metrics: clean spark and clean dark spreads.

These are the bridge from gas/carbon fundamentals to power-curve risk —
they're the metric most directly tied to the brief's thesis. Formulas
below use industry-standard plant assumptions (see config.py).
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
    """CSS = Power − Gas / η_gas − Carbon × (EF_gas / η_gas)

    Power, Gas in EUR/MWh; Carbon in EUR/tCO2.
    Returns a DataFrame with a 'value' column in EUR/MWh.
    """
    if any(df is None or df.empty for df in (power, gas, carbon)):
        return pd.DataFrame(columns=["value"])

    p, g, c = align_daily([power, gas, carbon])
    eff_emission = GAS_EMISSION_FACTOR / GAS_EFFICIENCY  # tCO2 per MWh_electric
    df = pd.DataFrame(index=p.index)
    df["value"] = (
        p["value"]
        - g["value"] / GAS_EFFICIENCY
        - c["value"] * eff_emission
    )
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
    """CDS = Power − Coal_EUR_per_MWh_thermal / η_coal − Carbon × (EF_coal / η_coal)

    Coal price is converted from USD/t to EUR/MWh_thermal via FX and the
    calorific value (MWh_th per tonne).
    """
    if any(df is None or df.empty for df in (power, coal_usd_t, carbon, eurusd)):
        return pd.DataFrame(columns=["value"])

    p, coal, c, fx = align_daily([power, coal_usd_t, carbon, eurusd])
    coal_eur_per_mwh_th = (coal["value"] / fx["value"]) / COAL_CALORIFIC_MWH_PER_T
    eff_emission = COAL_EMISSION_FACTOR / COAL_EFFICIENCY
    df = pd.DataFrame(index=p.index)
    df["value"] = (
        p["value"]
        - coal_eur_per_mwh_th / COAL_EFFICIENCY
        - c["value"] * eff_emission
    )
    df.index.name = "date"
    df.attrs["formula"] = (
        f"P - (Coal_USD/FX/{COAL_CALORIFIC_MWH_PER_T:.2f})/{COAL_EFFICIENCY:.2f} "
        f"- C × {eff_emission:.3f}  (η_coal={COAL_EFFICIENCY}, EF_coal={COAL_EMISSION_FACTOR} tCO2/MWh_th)"
    )
    return df.dropna()


def fuel_switch_indicator(clean_spark: pd.DataFrame, clean_dark: pd.DataFrame) -> pd.DataFrame:
    """CDS − CSS: positive ⇒ coal in-the-money vs gas, negative ⇒ gas wins.

    Not displayed as a standalone metric, but surfaced in narrative + signals.
    """
    if any(df is None or df.empty for df in (clean_spark, clean_dark)):
        return pd.DataFrame(columns=["value"])
    cs, cd = align_daily([clean_spark, clean_dark])
    df = pd.DataFrame(index=cs.index)
    df["value"] = cd["value"] - cs["value"]
    df.index.name = "date"
    return df.dropna()
