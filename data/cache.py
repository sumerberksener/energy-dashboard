"""Streamlit-aware caching layer over the raw fetchers.

Two-tier strategy:
1. In-memory: @st.cache_data with a 1-hour TTL keeps repeat reloads instant.
2. On-disk: parquet snapshot in data/store/ acts as a graceful-degradation
   fallback if a live fetch fails (API down, token missing, network blip).
   When a snapshot is served, df.attrs["is_stale"] = True and the UI shows
   a "stale" badge.

Five primary metrics are fetched directly. Two derived metrics — clean spark
and clean dark spreads — are computed by analysis.derived from the primaries.
get_all_with_derived() returns the full 7-metric dict.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

from analysis import derived as derived_metrics
from config import CACHE_TTL_SECONDS, PRIMARY_KEYS
from data import fetchers

log = logging.getLogger(__name__)

STORE = Path(__file__).parent / "store"
STORE.mkdir(exist_ok=True)


def _path(key: str) -> Path:
    return STORE / f"{key}.parquet"


def _load_snapshot(key: str) -> pd.DataFrame | None:
    p = _path(key)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception as e:
        log.warning("snapshot read failed for %s: %s", key, e)
        return None


def _save_snapshot(key: str, df: pd.DataFrame) -> None:
    if df is None or df.empty:
        return
    try:
        df.to_parquet(_path(key))
    except Exception as e:
        log.warning("snapshot write failed for %s: %s", key, e)


def _safe(key: str, fn: Callable[..., pd.DataFrame], *args, **kwargs) -> pd.DataFrame:
    try:
        df = fn(*args, **kwargs)
        if df is None or df.empty:
            raise ValueError("empty result")
        _save_snapshot(key, df)
        df.attrs["is_stale"] = False
        df.attrs["source"] = "live"
        return df
    except Exception as e:
        log.warning("live fetch failed for %s: %s — trying snapshot", key, e)
        snap = _load_snapshot(key)
        if snap is not None and not snap.empty:
            snap.attrs["is_stale"] = True
            snap.attrs["source"] = "snapshot"
            snap.attrs["error"] = str(e)
            return snap
        empty = pd.DataFrame(columns=["value"], index=pd.DatetimeIndex([], name="date"))
        empty.attrs["is_stale"] = True
        empty.attrs["source"] = "empty"
        empty.attrs["error"] = str(e)
        return empty


def _secret(name: str) -> str | None:
    try:
        return st.secrets[name]
    except Exception:
        return None


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_ttf() -> pd.DataFrame:
    return _safe("ttf", fetchers.fetch_ttf)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_eua() -> pd.DataFrame:
    return _safe("eua", fetchers.fetch_eua)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_coal() -> pd.DataFrame:
    return _safe("coal", fetchers.fetch_coal)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_de_power() -> pd.DataFrame:
    return _safe("de_power", fetchers.fetch_de_power, _secret("ENTSOE_TOKEN"))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_storage() -> pd.DataFrame:
    return _safe("storage", fetchers.fetch_storage, _secret("AGSI_TOKEN"))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_eurusd() -> pd.DataFrame:
    return _safe("eurusd", fetchers.fetch_eurusd)


PRIMARY_GETTERS = {
    "ttf": get_ttf,
    "storage": get_storage,
    "coal": get_coal,
    "eua": get_eua,
    "de_power": get_de_power,
}


def get_primaries() -> dict[str, pd.DataFrame]:
    return {k: g() for k, g in PRIMARY_GETTERS.items()}


def get_all_with_derived() -> dict[str, pd.DataFrame]:
    """Fetch all 5 primaries + compute the 3 derived metrics. Returns 8-metric dict."""
    primaries = get_primaries()
    eurusd = get_eurusd()

    cs = derived_metrics.clean_spark_spread(
        primaries["de_power"], primaries["ttf"], primaries["eua"]
    )
    cd = derived_metrics.clean_dark_spread(
        primaries["de_power"], primaries["coal"], primaries["eua"], eurusd
    )
    sw = derived_metrics.switching_ttf(
        primaries["coal"], primaries["eua"], eurusd
    )

    out = dict(primaries)
    out["clean_spark"] = cs
    out["clean_dark"] = cd
    out["switching_ttf"] = sw
    return out


def clear_cache() -> None:
    for g in (*PRIMARY_GETTERS.values(), get_eurusd):
        g.clear()
