"""Smoke tests for the 5 data fetchers.

These are live-network integration tests — they hit Yahoo Finance, stooq,
ENTSO-E, and GIE AGSI+. They're intentionally lightweight: each fetcher
must return a DataFrame with the expected shape and recent data. They
skip gracefully when a token is missing or the upstream is unreachable.

Run:  pytest -q tests/test_fetchers.py
"""
from __future__ import annotations

import os
import socket

import pandas as pd
import pytest

from data import fetchers


# Heuristic: skip when we have no internet at all.
def _has_network() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2)
        return True
    except OSError:
        return False


needs_net = pytest.mark.skipif(not _has_network(), reason="no network")


def _assert_tidy(df: pd.DataFrame, min_rows: int = 200) -> None:
    assert df is not None and not df.empty, "empty DataFrame"
    assert "value" in df.columns
    assert df.index.is_monotonic_increasing
    assert df["value"].notna().all(), "nulls present"
    assert len(df) >= min_rows, f"only {len(df)} rows (<{min_rows})"
    # Latest row should be within the last 14 days for a daily series.
    latest = df.index.max()
    assert (pd.Timestamp.utcnow().tz_localize(None) - latest).days <= 14, (
        f"stale data — latest is {latest}"
    )


@needs_net
def test_ttf():
    df = fetchers.fetch_ttf()
    _assert_tidy(df)


@needs_net
def test_brent():
    df = fetchers.fetch_brent()
    _assert_tidy(df, min_rows=1000)


@needs_net
def test_eua():
    df = fetchers.fetch_eua()
    _assert_tidy(df)


@needs_net
def test_de_power():
    token = os.environ.get("ENTSOE_TOKEN")
    if not token:
        pytest.skip("ENTSOE_TOKEN not set in env")
    df = fetchers.fetch_de_power(token)
    _assert_tidy(df, min_rows=1000)


@needs_net
def test_storage():
    token = os.environ.get("AGSI_TOKEN")
    if not token:
        pytest.skip("AGSI_TOKEN not set in env")
    df = fetchers.fetch_storage(token)
    _assert_tidy(df, min_rows=1000)
