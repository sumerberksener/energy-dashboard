"""Smoke tests for the data fetchers.

These are live-network integration tests — they hit Yahoo Finance, stooq,
ENTSO-E, and GIE AGSI+. Each fetcher must return a tidy DataFrame with
the expected shape and recent data. They skip gracefully when a token is
missing or the upstream is unreachable.

Run:  pytest -q tests/test_fetchers.py
"""
from __future__ import annotations

import os
import socket

import pandas as pd
import pytest

from data import fetchers


def _has_network() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        return True
    except OSError:
        return False


needs_net = pytest.mark.skipif(not _has_network(), reason="no network")


def _assert_tidy(df: pd.DataFrame, min_rows: int = 200, max_age_days: int = 14) -> None:
    assert df is not None and not df.empty, "empty DataFrame"
    assert "value" in df.columns
    assert df.index.is_monotonic_increasing
    assert df["value"].notna().all(), "nulls present"
    assert len(df) >= min_rows, f"only {len(df)} rows (<{min_rows})"
    latest = df.index.max()
    age = (pd.Timestamp.utcnow().tz_localize(None) - latest).days
    assert age <= max_age_days, f"stale data — latest is {latest} ({age} days old)"


@needs_net
def test_ttf():
    _assert_tidy(fetchers.fetch_ttf())


@needs_net
def test_eua():
    _assert_tidy(fetchers.fetch_eua())


@needs_net
def test_coal_freshness_invariant():
    """fetch_coal returns either fresh data OR a frame flagged as stale.

    Per TASKS.md P0: 'returns a series whose latest date is within the last 5
    business days OR raises a clear exception that the cache layer surfaces as
    df.attrs["is_stale"] = True. No silent staleness.'
    """
    df = fetchers.fetch_coal()
    assert df is not None and not df.empty
    assert "value" in df.columns
    age = (pd.Timestamp.utcnow().tz_localize(None) - df.index.max()).days
    if age > 7:
        # Stale data must be explicitly flagged so downstream code can surface it.
        assert df.attrs.get("is_stale") is True, (
            f"Coal data is {age} days old but is_stale flag is not set — "
            "this is the silent-staleness regression P0 calls out."
        )


@needs_net
def test_de_power():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        pytest.skip("ENTSOE_TOKEN not set in env")
    _assert_tidy(fetchers.fetch_de_power(token), min_rows=1000)


@needs_net
@pytest.mark.parametrize("zone", ["HU", "IE_SEM", "SK"])
def test_cobblestone_zone_dap(zone: str) -> None:
    """Smoke-check ENTSO-E DA fetch for the Cobblestone-aligned zones added in P1A.

    HU + IE + SK are live-book markets per cobblestoneenergy.com (Power for
    HU/IE; Gas for SK with power DA shown as a corridor read).
    """
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        pytest.skip("ENTSOE_TOKEN not set in env")
    df = fetchers.fetch_power_zone(token, zone)
    # IE_SEM publishes on a SEM-day calendar, so its trailing edge can lag a
    # day or two vs central-European zones; allow 4d there.
    max_age = 4 if zone == "IE_SEM" else 14
    _assert_tidy(df, min_rows=500, max_age_days=max_age)


@needs_net
def test_storage():
    token = os.environ.get("AGSI_TOKEN")
    if not token:
        pytest.skip("AGSI_TOKEN not set in env")
    _assert_tidy(fetchers.fetch_storage(token), min_rows=1000)


@needs_net
def test_eurusd():
    _assert_tidy(fetchers.fetch_eurusd(), min_rows=500)


def test_stooq_handles_empty_response(monkeypatch):
    """Regression: an empty stooq body must raise a meaningful error, not IndexError.

    Per TASKS.md P0: '_stooq currently raises IndexError on empty CSV — fix to
    handle empty/non-CSV responses gracefully.'
    """
    class _StubResp:
        status_code = 200
        text = ""
        def raise_for_status(self): pass

    monkeypatch.setattr(fetchers.requests, "get", lambda *a, **kw: _StubResp())
    with pytest.raises(RuntimeError, match="stooq"):
        fetchers._stooq("anything")


def test_stooq_handles_no_data_text(monkeypatch):
    """A 'No data' style response should also raise RuntimeError, not crash."""
    class _StubResp:
        status_code = 200
        text = "No data"
        def raise_for_status(self): pass

    monkeypatch.setattr(fetchers.requests, "get", lambda *a, **kw: _StubResp())
    with pytest.raises(RuntimeError, match="stooq"):
        fetchers._stooq("anything")


@needs_net
@pytest.mark.parametrize("from_zone,to_zone", fetchers.INTERCONNECTORS)
def test_cross_border_flow(from_zone: str, to_zone: str) -> None:
    """Smoke-check ENTSO-E cross-border flow fetch for the three Cobblestone-
    relevant interconnector corridors (DE↔FR, GB↔FR, NL↔DE).

    Surfaces the "Power Transportation" pillar of Cobblestone's Power desk.
    Cross-border flow data publishes hourly with a typical lag of 1-2 days,
    so we relax the freshness window vs DA prices.
    """
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        pytest.skip("ENTSOE_TOKEN not set in env")
    df = fetchers.fetch_cross_border_flow(token, from_zone, to_zone)
    _assert_tidy(df, min_rows=200, max_age_days=4)
    # Net flow is signed daily MWh; both polarities are valid.
    assert df.attrs.get("from_zone") == from_zone
    assert df.attrs.get("to_zone") == to_zone


@needs_net
@pytest.mark.parametrize("region", list(fetchers.WEATHER_LOCATIONS.keys()))
def test_weather_forecast(region: str) -> None:
    """Smoke-check Open-Meteo forecast + 5-yr seasonal-normal join.

    No token required (Open-Meteo is fully free). The returned DataFrame
    should carry the next 7 forecast days plus matched seasonal normals.
    """
    lat, lon = fetchers.WEATHER_LOCATIONS[region]
    df = fetchers.fetch_weather_forecast(lat, lon, region)
    assert df is not None and not df.empty
    expected_columns = {
        "temp_c", "wind_max_ms", "wind_gust_max_ms", "cloud_cover_pct",
        "temp_normal_c", "temp_anomaly_c",
    }
    assert expected_columns.issubset(df.columns), \
        f"missing columns: {expected_columns - set(df.columns)}"
    assert 5 <= len(df) <= 8, f"forecast horizon should be ~7 days, got {len(df)}"
    # Anomaly column should be populated for at least the first 5 days
    # (later days may lack 5-yr archive matches; that's tolerable).
    assert df["temp_anomaly_c"].head(5).notna().any(), "no anomaly data computed"


def test_detect_weather_events_smoke(monkeypatch):
    """Detector returns structured events from a synthetic cold-snap forecast.

    Builds a 7-day forecast where DE shows a 4-day cold snap (anomaly = −5°C),
    and confirms the detector classifies it correctly with the right region,
    severity, and a non-empty trading implication.
    """
    from analysis.weather import detect_weather_events

    idx = pd.date_range(start="2026-05-08", periods=7, freq="D")
    de = pd.DataFrame({
        "temp_c": [10.0] * 7,
        "wind_max_ms": [10.0] * 7,
        "wind_gust_max_ms": [15.0] * 7,
        "cloud_cover_pct": [40.0] * 7,
        "temp_normal_c": [15.0] * 7,
        "temp_anomaly_c": [-5.0] * 4 + [0.0] * 3,
        "wind_normal_max_ms": [10.0] * 7,
        "wind_normal_gust_ms": [15.0] * 7,
    }, index=idx)
    events = detect_weather_events({"DE": de})
    assert any(e.type == "cold_snap" and e.region == "DE" for e in events)
    cold = next(e for e in events if e.type == "cold_snap")
    assert cold.severity in {"moderate", "severe"}
    assert "DE" in cold.trading_implication or "thermal" in cold.trading_implication
    assert (cold.end_date - cold.start_date).days == 3
