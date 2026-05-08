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


@pytest.mark.parametrize("label", list(derived.HORIZON_BDAYS.keys()))
def test_seasonality_projection_constant_series(label):
    """Constant series → projection at any horizon equals that constant.

    Pins the multi-tenor curve strip at all five business-day horizons
    (W+1 / M+1 / Q+1 / Cal+1 / Cal+2). Without this guard a regression in
    `seasonality_projection` would silently desync the dashboard strip from
    the desk-note's "Curve shape" sentence.
    """
    bdays = derived.HORIZON_BDAYS[label]
    # Series long enough to cover Cal+2 (504 bd ≈ 730 calendar days). One
    # length for all parametrised horizons keeps the test cheap.
    idx = pd.date_range(end="2026-05-07", periods=900, freq="D", name="date")
    df = pd.DataFrame({"value": [50.0] * 900}, index=idx)
    proj = derived.seasonality_projection(df, horizon_bdays=bdays, smoothing_window=1)
    assert not proj.empty, f"{label} ({bdays}bd) returned empty projection"
    assert proj["value"].iloc[-1] == pytest.approx(50.0)
    assert proj.attrs.get("horizon_bdays") == bdays


def test_seasonality_projection_horizon_ordering_on_trend():
    """On a monotonic upward trend, longer horizons project a higher level.

    Sanity check: if DA rises over time, the "what was realised at +N"
    projection grows with N. Any future bug that swapped horizons or used
    the wrong sign would flip this monotonicity.
    """
    idx = pd.date_range(end="2026-05-07", periods=900, freq="D", name="date")
    # Linear ramp from 10 to 100
    values = [10.0 + (90.0 / 899.0) * i for i in range(900)]
    df = pd.DataFrame({"value": values}, index=idx)

    levels = {}
    for label in ("w1", "m1", "q1", "cal1", "cal2"):
        proj = derived.seasonality_projection(
            df, horizon_bdays=derived.HORIZON_BDAYS[label], smoothing_window=1
        )
        # Use a date well inside the projectable range so all horizons resolve.
        anchor = idx[100]
        levels[label] = float(proj.loc[anchor, "value"])

    # Upward trend ⇒ longer-horizon projection > shorter-horizon projection
    assert levels["w1"] < levels["m1"] < levels["q1"] < levels["cal1"] < levels["cal2"]


def test_seasonality_projection_too_short_for_horizon():
    """Series too short for the requested horizon returns empty (graceful)."""
    # ~6 months of daily data — enough for W+1/M+1, not enough for Cal+1/Cal+2.
    idx = pd.date_range(end="2026-05-07", periods=180, freq="D", name="date")
    df = pd.DataFrame({"value": [50.0] * 180}, index=idx)

    short_proj = derived.seasonality_projection(df, horizon_bdays=derived.HORIZON_BDAYS["w1"])
    assert not short_proj.empty

    long_proj = derived.seasonality_projection(df, horizon_bdays=derived.HORIZON_BDAYS["cal1"])
    assert long_proj.empty
