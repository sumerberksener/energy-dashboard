"""Streamlit-aware caching layer over the raw fetchers.

Two-tier strategy:
1. In-memory: @st.cache_data with a 1-hour TTL keeps repeat reloads instant.
2. On-disk: parquet snapshot in data/store/ acts as a graceful-degradation
   fallback if a live fetch fails (API down, token missing, network blip).

Eight registered top-row metrics + one fundamentals input (coal):
    Top row: TTF, EU Storage, EUA, DE Power, GB Power, Renewables,
             Clean Spark, Clean Dark
    Fundamentals: Coal (USD/t), EUR/USD, GBP/EUR (FX helpers, hidden)

`get_all_with_derived()` returns the full dict including derived spreads.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

from analysis import derived as derived_metrics
from config import CACHE_TTL_SECONDS
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
        df.attrs["is_stale"] = bool(df.attrs.get("is_stale", False))
        df.attrs.setdefault("source", "live")
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


# --- Primary fetchers (registered as METRICS) --------------------------------


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_ttf() -> pd.DataFrame:
    return _safe("ttf", fetchers.fetch_ttf)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_eua() -> pd.DataFrame:
    return _safe("eua", fetchers.fetch_eua)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_de_power() -> pd.DataFrame:
    return _safe("de_power", fetchers.fetch_de_power, _secret("ENTSOE_TOKEN"))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_gb_power() -> pd.DataFrame:
    return _safe("gb_power", fetchers.fetch_gb_power, _secret("ENTSOE_TOKEN"))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_storage() -> pd.DataFrame:
    return _safe("storage", fetchers.fetch_storage, _secret("AGSI_TOKEN"))


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_renewable_share() -> pd.DataFrame:
    return _safe(
        "renewable_share", fetchers.fetch_renewable_share, _secret("ENTSOE_TOKEN")
    )


# --- Fundamentals inputs (in METRICS but not top row) -----------------------


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_coal() -> pd.DataFrame:
    return _safe("coal", fetchers.fetch_coal)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_eurusd() -> pd.DataFrame:
    return _safe("eurusd", fetchers.fetch_eurusd)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_jkm() -> pd.DataFrame:
    """JKM LNG benchmark (USD/MMBtu) — auxiliary; not a registered Metric."""
    return _safe("jkm", fetchers.fetch_jkm)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_gbpeur() -> pd.DataFrame:
    return _safe("gbpeur", fetchers.fetch_gbpeur)


PRIMARY_GETTERS = {
    "ttf": get_ttf,
    "storage": get_storage,
    "eua": get_eua,
    "de_power": get_de_power,
    "gb_power": get_gb_power,
    "renewable_share": get_renewable_share,
    "coal": get_coal,
}


def get_primaries() -> dict[str, pd.DataFrame]:
    return {k: g() for k, g in PRIMARY_GETTERS.items()}


def get_all_with_derived() -> dict[str, pd.DataFrame]:
    """Fetch all primaries + compute derived metrics. Returns metric dict.

    Includes `switching_ttf` and `de_gb_spread` as auxiliary derived series
    consumed by the regime strip — not registered as Metrics, but useful
    enough to compute once and pass through.
    """
    primaries = get_primaries()
    eurusd = get_eurusd()
    jkm = get_jkm()

    cs = derived_metrics.clean_spark_spread(
        primaries["de_power"], primaries["ttf"], primaries["eua"]
    )
    cd = derived_metrics.clean_dark_spread(
        primaries["de_power"], primaries["coal"], primaries["eua"], eurusd
    )
    sw = derived_metrics.switching_ttf(
        primaries["coal"], primaries["eua"], eurusd
    )
    de_gb = derived_metrics.power_spread(
        primaries["de_power"], primaries["gb_power"]
    )
    # TTF − JKM spread (EUR/MWh) — Europe-vs-Asia LNG arbitrage signal.
    # Auxiliary metric, surfaced as a chip in the regime strip and in
    # section 3 of the desk note.
    ttf_jkm = derived_metrics.ttf_jkm_spread(primaries["ttf"], jkm, eurusd)
    # Multi-tenor seasonality projection — one call per horizon, all sharing
    # `seasonality_projection` so the methodology is identical across tenors.
    # Cal+1 is kept under its existing key (`de_cal1_proj`) for backward
    # compatibility with the brief template and the regime strip.
    de_curve_projs = {
        f"de_{label}_proj": derived_metrics.seasonality_projection(
            primaries["de_power"],
            horizon_bdays=bdays,
        )
        for label, bdays in derived_metrics.HORIZON_BDAYS.items()
    }

    out = dict(primaries)
    out["clean_spark"] = cs
    out["clean_dark"] = cd
    out["switching_ttf"] = sw
    out["de_gb_spread"] = de_gb
    out.update(de_curve_projs)
    out["eurusd"] = eurusd
    out["jkm"] = jkm
    out["ttf_jkm_spread"] = ttf_jkm
    return out


def clear_cache() -> None:
    for g in (*PRIMARY_GETTERS.values(), get_eurusd, get_gbpeur):
        g.clear()
