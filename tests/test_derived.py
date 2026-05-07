"""Golden-input tests for the analytical heart of the project.

Pins the spark / dark / switching TTF formulas against hand-computed expected
values so they can't silently drift.
"""
from __future__ import annotations

import pandas as pd
import pytest

from analysis import derived
from config import (
    COAL_CALORIFIC_MWH_PER_T,
    COAL_EFFICIENCY,
    COAL_EMISSION_FACTOR,
    GAS_EFFICIENCY,
    GAS_EMISSION_FACTOR,
)


def _frame(values: list[float], dates: list[str]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(dates), name="date")
    return pd.DataFrame({"value": values}, index=idx)


def test_clean_spark_spread_simple():
    """CSS = P − G/η_gas − C × EF_gas/η_gas
    With P=100, G=20, C=50, η=0.50, EF=0.184:
        100 − 20/0.50 − 50 × (0.184/0.50)
      = 100 − 40 − 18.4
      = 41.6
    """
    p = _frame([100.0], ["2026-05-05"])
    g = _frame([20.0], ["2026-05-05"])
    c = _frame([50.0], ["2026-05-05"])

    out = derived.clean_spark_spread(p, g, c)
    assert len(out) == 1
    assert out["value"].iloc[0] == pytest.approx(41.6, abs=1e-9)


def test_clean_dark_spread_simple():
    """CDS = P − Coal_EUR_per_MWh_th/η_coal − C × EF_coal/η_coal
    With P=100, Coal_USD/t=120, EURUSD=1.10, C=50, η_coal=0.40, EF_coal=0.34:
        Coal_EUR = (120/1.10) / 6.978 = 15.633...
        15.633 / 0.40 = 39.083
        50 × (0.34/0.40) = 42.5
        100 − 39.083 − 42.5 = 18.417
    """
    p = _frame([100.0], ["2026-05-05"])
    coal = _frame([120.0], ["2026-05-05"])
    c = _frame([50.0], ["2026-05-05"])
    fx = _frame([1.10], ["2026-05-05"])

    expected = (
        100.0
        - ((120.0 / 1.10) / COAL_CALORIFIC_MWH_PER_T) / COAL_EFFICIENCY
        - 50.0 * (COAL_EMISSION_FACTOR / COAL_EFFICIENCY)
    )

    out = derived.clean_dark_spread(p, coal, c, fx)
    assert len(out) == 1
    assert out["value"].iloc[0] == pytest.approx(expected, abs=1e-9)


def test_switching_ttf_simple():
    """Switching TTF = η_gas · (Coal_EUR/η_coal + (EF_coal/η_coal − EF_gas/η_gas)·EUA)
    Same inputs as the dark test:
        Coal_EUR = (120/1.10)/6.978 ≈ 15.633
        Coal_EUR/η_coal = 39.083
        EF_coal/η_coal − EF_gas/η_gas = 0.85 − 0.368 = 0.482
        0.482 × 50 = 24.1
        η_gas × (39.083 + 24.1) = 0.50 × 63.183 ≈ 31.59
    """
    coal = _frame([120.0], ["2026-05-05"])
    c = _frame([50.0], ["2026-05-05"])
    fx = _frame([1.10], ["2026-05-05"])

    coal_eur_per_mwh_th = (120.0 / 1.10) / COAL_CALORIFIC_MWH_PER_T
    diff = COAL_EMISSION_FACTOR / COAL_EFFICIENCY - GAS_EMISSION_FACTOR / GAS_EFFICIENCY
    expected = GAS_EFFICIENCY * (coal_eur_per_mwh_th / COAL_EFFICIENCY + diff * 50.0)

    out = derived.switching_ttf(coal, c, fx)
    assert len(out) == 1
    assert out["value"].iloc[0] == pytest.approx(expected, abs=1e-9)


def test_switching_ttf_consistency_with_spreads():
    """If actual TTF == switching TTF, then clean spark == clean dark.

    Solve switching TTF for the test inputs and verify the spreads match.
    """
    coal_v, c_v, fx_v, p_v = 120.0, 50.0, 1.10, 100.0
    dates = ["2026-05-05"]

    coal = _frame([coal_v], dates)
    c = _frame([c_v], dates)
    fx = _frame([fx_v], dates)
    p = _frame([p_v], dates)

    sw = derived.switching_ttf(coal, c, fx)["value"].iloc[0]
    g = _frame([sw], dates)

    cs = derived.clean_spark_spread(p, g, c)["value"].iloc[0]
    cd = derived.clean_dark_spread(p, coal, c, fx)["value"].iloc[0]

    assert cs == pytest.approx(cd, abs=1e-9), (
        f"At switching TTF, spark must equal dark. Got CSS={cs}, CDS={cd}, sw={sw}."
    )


def test_clean_spark_spread_empty_input():
    out = derived.clean_spark_spread(
        pd.DataFrame(columns=["value"]), _frame([1.0], ["2026-05-05"]), _frame([1.0], ["2026-05-05"])
    )
    assert out.empty


def test_cal1_seasonality_projection_basic():
    """For a constant-DA series, the year-ahead projection equals the DA itself."""
    idx = pd.date_range(end="2026-05-07", periods=800, freq="D", name="date")
    df = pd.DataFrame({"value": [50.0] * 800}, index=idx)
    proj = derived.cal1_seasonality_projection(df, smoothing_window=1)
    assert not proj.empty
    # Year-ahead realisation of any constant series is the same constant
    assert proj["value"].iloc[-1] == pytest.approx(50.0)


def test_cal1_seasonality_projection_too_short():
    """Series shorter than 1 year returns empty (can't project ahead)."""
    idx = pd.date_range(end="2026-05-07", periods=100, freq="D", name="date")
    df = pd.DataFrame({"value": [50.0] * 100}, index=idx)
    proj = derived.cal1_seasonality_projection(df)
    assert proj.empty
