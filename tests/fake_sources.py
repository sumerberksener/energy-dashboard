"""Deterministic in-memory stand-ins for every external data source.

`install_fake_sources` replaces the public `fetch_*` functions in
`data.fetchers` so the whole brief pipeline (fetch_all -> CSVs -> charts ->
rule-based narrative -> Markdown) can run with no network and no tokens.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import fetchers

ALL_SOURCES = (
    "ttf", "eua", "coal", "de_power", "gb_power", "renewable_share",
    "storage", "eurusd", "jkm", "flows", "weather",
)


def _today() -> pd.Timestamp:
    return pd.Timestamp.now().normalize()


def price_frame(base: float, vol: float, seed: int, n: int = 1300,
                floor: float | None = None) -> pd.DataFrame:
    """Business-day random walk ending yesterday, tidy like the real fetchers."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range(end=_today() - pd.Timedelta(days=1), periods=n, name="date")
    # mean-reverting (AR(1)) so levels stay near `base` like real prices do
    noise = rng.normal(0.0, vol, size=n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.97 * x[i - 1] + noise[i]
    vals = base + x
    if floor is not None:
        vals = np.maximum(vals, floor)
    return pd.DataFrame({"value": vals}, index=idx)


def weather_frame(label: str, lat: float, lon: float) -> pd.DataFrame:
    idx = pd.date_range(start=_today() + pd.Timedelta(days=1), periods=7, freq="D", name="date")
    df = pd.DataFrame({
        "temp_c": np.linspace(8.0, 11.0, 7),
        "wind_max_ms": np.linspace(9.0, 14.0, 7),
        "wind_gust_max_ms": np.linspace(14.0, 21.0, 7),
        "cloud_cover_pct": np.linspace(40.0, 70.0, 7),
        "temp_normal_c": np.full(7, 9.0),
        "temp_anomaly_c": np.linspace(-1.0, 2.0, 7),
        "wind_normal_max_ms": np.full(7, 10.0),
        "wind_normal_gust_ms": np.full(7, 15.0),
    }, index=idx)
    df.attrs["label"] = label
    df.attrs["lat"] = lat
    df.attrs["lon"] = lon
    return df


def healthy_frames() -> dict[str, pd.DataFrame]:
    coal = price_frame(105.0, 1.5, seed=3, floor=40.0)
    coal.attrs["coal_source"] = "fixture"
    return {
        "ttf": price_frame(35.0, 0.6, seed=1, floor=8.0),
        "eua": price_frame(70.0, 0.9, seed=2, floor=20.0),
        "coal": coal,
        "de_power": price_frame(90.0, 4.0, seed=4, floor=-20.0),
        "gb_power": price_frame(85.0, 4.0, seed=5, floor=-20.0),
        "renewable_share": price_frame(45.0, 2.5, seed=6, floor=5.0).clip(upper=95.0),
        "storage": price_frame(60.0, 0.4, seed=7, floor=5.0).clip(upper=100.0),
        "eurusd": price_frame(1.08, 0.004, seed=8, floor=0.8),
        "jkm": price_frame(14.0, 0.25, seed=9, floor=3.0),
    }


def install_fake_sources(monkeypatch) -> dict[str, list]:
    """Patch data.fetchers.fetch_* with fakes. Returns a call log per source."""
    frames = healthy_frames()
    calls: dict[str, list] = {name: [] for name in ALL_SOURCES}

    def make(name: str):
        def fake(*args, **kwargs):
            calls[name].append(args)
            return frames[name].copy()
        return fake

    for name in ("ttf", "eua", "coal", "de_power", "gb_power", "renewable_share",
                 "storage", "eurusd", "jkm"):
        monkeypatch.setattr(fetchers, f"fetch_{name}", make(name))

    def fake_flow(token, from_zone, to_zone):
        calls["flows"].append((from_zone, to_zone))
        seed = 20 + len(from_zone) + len(to_zone)
        df = price_frame(0.0, 800.0, seed=seed, n=360)
        df.attrs.update({"from_zone": from_zone, "to_zone": to_zone, "unit": "MWh/day (net)"})
        return df

    def fake_weather(latitude, longitude, label):
        calls["weather"].append((latitude, longitude, label))
        return weather_frame(label, latitude, longitude)

    monkeypatch.setattr(fetchers, "fetch_cross_border_flow", fake_flow)
    monkeypatch.setattr(fetchers, "fetch_weather_forecast", fake_weather)
    return calls
