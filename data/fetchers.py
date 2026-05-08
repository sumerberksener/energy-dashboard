"""Data fetchers for the primary metrics.

Pure functions, no Streamlit dependency. Each fetcher returns a tidy DataFrame:
    index: pd.DatetimeIndex (tz-naive, daily, ascending)
    column: "value" (float)
    no duplicate dates, no nulls.

Fallback chains are documented inline. Network errors propagate; the cache
layer above is responsible for falling back to parquet snapshots.

Coal note (history): an earlier version of this module fetched a Newcastle
coal proxy for clean dark spread / switching TTF. As of 2026-05, no usable
free daily API2/Newcastle feed exists (Yahoo's MTF=F stopped updating; stooq
gated their CSV API; investpy is dead). Coal-dependent metrics were dropped
in favour of a Renewable Share metric — a strict desk-relevance upgrade for
2026 EU power markets, where wind+solar share is the dominant marginal-price
driver after gas.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from config import HISTORY_YEARS

log = logging.getLogger(__name__)


def _date_range():
    end = pd.Timestamp.now(tz="UTC").normalize()
    start = end - pd.DateOffset(years=HISTORY_YEARS)
    return start, end


def _tidy(s: pd.Series) -> pd.DataFrame:
    df = s.to_frame(name="value").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.dropna()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna()


def _yahoo(ticker: str) -> pd.DataFrame:
    import yfinance as yf

    start, end = _date_range()
    hist = yf.download(
        ticker,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if hist is None or hist.empty:
        raise RuntimeError(f"Yahoo Finance returned empty for {ticker}")
    close = hist["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return _tidy(close)


def _stooq(symbol: str) -> pd.DataFrame:
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()

    text = r.text or ""
    lines = text.splitlines()
    if not lines:
        raise RuntimeError(f"stooq returned empty body for {symbol}")
    # Common stooq "no data" responses: a single line with "No data" or just headers
    if "Date" not in lines[0]:
        snippet = text[:120].replace("\n", " ")
        raise RuntimeError(f"stooq returned non-CSV for {symbol}: {snippet!r}")

    df = pd.read_csv(io.StringIO(text))
    if df.empty or "Close" not in df.columns:
        raise RuntimeError(f"stooq returned empty CSV for {symbol}")
    df["Date"] = pd.to_datetime(df["Date"])
    s = df.set_index("Date")["Close"]
    start, _ = _date_range()
    s = s[s.index >= start.tz_localize(None)]
    if s.empty:
        raise RuntimeError(f"stooq returned no rows in lookback window for {symbol}")
    return _tidy(s)


# --- Primary metric fetchers ------------------------------------------------


def fetch_ttf() -> pd.DataFrame:
    """TTF front-month gas (EUR/MWh). Yahoo `TTF=F` → stooq fallback."""
    try:
        return _yahoo("TTF=F")
    except Exception as e:
        log.info("TTF Yahoo failed (%s); falling back to stooq", e)
    return _stooq("ttf.f")


def fetch_eua() -> pd.DataFrame:
    """EUA December carbon futures (EUR/tCO2). stooq → KRBN ETF proxy fallback.

    KRBN is a global carbon ETF (blends EUA/RGGI/CCA), used only if pure EUA
    data is unavailable. Documented as a known data-quality limitation.
    """
    try:
        return _stooq("co2.f")
    except Exception as e:
        log.info("EUA stooq failed (%s); falling back to Yahoo KRBN proxy", e)
    return _yahoo("KRBN")


def fetch_coal() -> pd.DataFrame:
    """Thermal coal proxy (USD/t). Multi-source fallback chain.

    Yahoo `MTF=F` (Newcastle) → other Yahoo candidates → stooq. Each is
    checked for both presence AND freshness — the freshest source wins.
    Sources older than 7 days set `df.attrs["is_stale"] = True` so the
    cache + UI surface a STALE badge instead of pretending December prices
    are current. As of 2026-05, all known free Newcastle/API2 daily feeds
    are degraded; this fetcher is best-effort, demoted to a fundamentals
    input only, and downstream metrics (Clean Dark) carry the staleness flag.
    """
    candidates = [
        ("MTF=F", _yahoo, "ICE Newcastle (Yahoo)"),
        ("LMC.L", _yahoo, "Yahoo coal-related ETF"),
        ("KOL=F", _yahoo, "Yahoo coal-vector futures"),
        ("coal.f", _stooq, "stooq coal.f"),
    ]
    best: pd.DataFrame | None = None
    best_label: str = ""
    best_age_days: int = 10**9

    for symbol, fetch_fn, label in candidates:
        try:
            df = fetch_fn(symbol)
            if df is None or df.empty:
                continue
            age = int((pd.Timestamp.now().normalize() - df.index.max()).days)
            if age < best_age_days:
                best, best_label, best_age_days = df, label, age
            if age <= 7:
                log.info("Coal: using %s (%d rows, latest %s)",
                         label, len(df), df.index.max().date())
                df.attrs["coal_source"] = label
                return df
        except Exception as e:
            log.info("Coal %s (%s) failed: %s", symbol, label, e)

    if best is not None:
        log.warning(
            "Coal: all sources stale; best is %s with %d-day-old data — "
            "downstream will flag as STALE", best_label, best_age_days
        )
        best.attrs["coal_source"] = best_label
        best.attrs["is_stale"] = True
        return best

    raise RuntimeError("Coal: no usable source found across Yahoo + stooq")


def fetch_de_power(token: str) -> pd.DataFrame:
    """Germany day-ahead baseload power (EUR/MWh) via ENTSO-E."""
    return _fetch_entsoe_dap(token, "DE_LU")


def fetch_power_zone(token: str, zone: str) -> pd.DataFrame:
    """Generic ENTSO-E day-ahead price fetcher for any bidding zone, in EUR/MWh.

    GB is a special case (returns GBP/MWh natively) — handled by `fetch_gb_power`.
    Other EU zones return EUR/MWh natively.
    """
    return _fetch_entsoe_dap(token, zone)


def fetch_gb_power(token: str | None = None) -> pd.DataFrame:
    """GB day-ahead baseload power (EUR/MWh) via Elexon BMRS Insights.

    UK left ENTSO-E membership post-Brexit, so the ENTSO-E `GB` zone returns
    no data. Elexon's BMRS Market Index Data (MID) is the canonical free
    feed for GB half-hourly settlement prices, requires no auth, and covers
    both APX and N2EX. We filter to APXMIDP (the standard GB DA reference)
    and aggregate to daily mean before converting GBP→EUR via Yahoo's
    `GBPEUR=X`.

    Elexon enforces a max date range of 7 days per call, so we paginate
    weekly. To keep cold-start latency reasonable, GB history is capped at
    1 year (52 weekly calls ≈ 30 s) — enough for percentile rank against
    a representative window. The `token` arg is accepted but unused for
    API parity with the ENTSO-E fetchers.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365)  # 1 year cold-start cap (Elexon weekly chunks)

    all_rows: list[dict] = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(chunk_start + timedelta(days=7), end)
        url = "https://data.elexon.co.uk/bmrs/api/v1/balancing/pricing/market-index"
        params = {
            "from": chunk_start.isoformat(),
            "to": chunk_end.isoformat(),
            "dataProviders": "APXMIDP",
            "format": "json",
        }
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            log.info("Elexon MID chunk %s–%s failed: %s", chunk_start, chunk_end, e)
            chunk_start = chunk_end
            continue
        for row in payload.get("data", []) or []:
            if row.get("dataProvider") != "APXMIDP":
                continue
            all_rows.append({
                "settlementDate": row.get("settlementDate"),
                "price": row.get("price"),
            })
        chunk_start = chunk_end

    if not all_rows:
        raise RuntimeError("Elexon MID returned no rows for GB")

    df = pd.DataFrame(all_rows)
    df["settlementDate"] = pd.to_datetime(df["settlementDate"])
    daily_gbp = df.groupby("settlementDate")["price"].mean()  # daily baseload from half-hourly
    daily_gbp.index = pd.to_datetime(daily_gbp.index)

    fx = fetch_gbpeur()
    aligned_fx = fx.reindex(daily_gbp.index, method="ffill")
    eur_per_mwh = daily_gbp * aligned_fx["value"]
    return _tidy(eur_per_mwh.dropna())


def _fetch_entsoe_dap(token: str, zone: str) -> pd.DataFrame:
    if not token:
        raise RuntimeError("ENTSO-E token missing")
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=token)
    end = pd.Timestamp.now(tz="Europe/Brussels").normalize()
    start = end - pd.DateOffset(years=HISTORY_YEARS)
    ts = client.query_day_ahead_prices(zone, start=start, end=end)
    if ts is None or ts.empty:
        raise RuntimeError(f"ENTSO-E returned empty for {zone}")
    daily = ts.resample("D").mean()
    return _tidy(daily)


def fetch_storage(token: str) -> pd.DataFrame:
    """EU aggregate gas storage (% full) from GIE AGSI+.

    Uses the dedicated `/api/data/eu` endpoint. The older `country=eu` query
    parameter on `/api` returns no rows under the current API.
    """
    if not token:
        raise RuntimeError("AGSI+ token missing")

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=HISTORY_YEARS * 366)
    headers = {"x-key": token}
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "size": 300,
            "page": page,
        }
        r = requests.get(
            "https://agsi.gie.eu/api/data/eu",
            headers=headers, params=params, timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        page_rows = payload.get("data", []) or []
        if not page_rows:
            break
        rows.extend(page_rows)
        last_page = payload.get("last_page") or 1
        if page >= int(last_page):
            break
        page += 1

    if not rows:
        raise RuntimeError("AGSI+ returned no rows")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["gasDayStart"])
    s = df.set_index("date")["full"]
    return _tidy(s.sort_index())


# --- Renewable share fetcher (DE wind+solar forecast / load forecast) -------


def fetch_renewable_share(token: str) -> pd.DataFrame:
    """Day-ahead forecast wind + solar share of load (DE_LU bidding zone, %).

    Calls ENTSO-E twice:
        - query_wind_and_solar_forecast → MW per renewable generation type
        - query_load_forecast            → MW load forecast
    Resamples to daily simple-mean and divides to get a % share. Daily mean
    of an hourly series is the right aggregation for "what's the typical
    renewable contribution that day."
    """
    if not token:
        raise RuntimeError("ENTSO-E token missing")
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=token)
    end = pd.Timestamp.now(tz="Europe/Brussels").normalize()
    # Renewable forecast history at hourly resolution is heavy — pull 2y.
    start = end - pd.DateOffset(years=2)

    rs = client.query_wind_and_solar_forecast(
        "DE_LU", start=start, end=end, psr_type=None,
    )
    if rs is None or rs.empty:
        raise RuntimeError("ENTSO-E returned empty wind+solar forecast for DE_LU")
    # rs comes as columns per generation type; sum across types per timestamp.
    if isinstance(rs, pd.DataFrame):
        renew = rs.sum(axis=1)
    else:
        renew = rs

    load = client.query_load_forecast("DE_LU", start=start, end=end)
    if load is None or len(load) == 0:
        raise RuntimeError("ENTSO-E returned empty load forecast for DE_LU")
    if isinstance(load, pd.DataFrame):
        load = load.iloc[:, 0]

    # Align hourly, then resample to daily mean of hourly share.
    aligned = pd.concat([renew.rename("renew"), load.rename("load")], axis=1).dropna()
    hourly_share = (aligned["renew"] / aligned["load"]) * 100.0
    daily = hourly_share.resample("D").mean()
    return _tidy(daily)


# --- Cross-border power flows (Power Transportation pillar) -----------------


# Cobblestone names "Power Transportation" as the third pillar of their Power
# Trading desk: "We invest in the physical transmission capacities that connect
# the power grids of Europe together. We then move the electricity from one
# region to another, depending on where it is needed most." These three
# corridors are the cleanest single tells on continental flow direction:
#   DE_LU↔FR — fuel-mix imbalance (FR-nuclear vs DE-renewables-and-thermal).
#   GB↔FR via IFA — UK premium vs continental import.
#   NL↔DE_LU — LNG-import side: Rotterdam/Gate gasification spilling into DE.
INTERCONNECTORS: list[tuple[str, str]] = [
    ("DE_LU", "FR"),
    ("GB", "FR"),
    ("NL", "DE_LU"),
]


def fetch_cross_border_flow(token: str, from_zone: str, to_zone: str) -> pd.DataFrame:
    """Net daily cross-border physical flow between two ENTSO-E zones, in MWh.

    Pulls the bidirectional `query_crossborder_flows` series in MW for both
    directions and computes net = (from→to) − (to→from), then resamples to
    daily mean × 24 to express the day's net energy transferred in MWh.
    Positive ⇒ from-zone is exporting; negative ⇒ from-zone is importing.

    This surfaces what Cobblestone calls "Power Transportation" — the
    third pillar of their Power desk — as a single signed daily number per
    corridor. Auxiliary metric: not registered in `config.py::METRICS`.
    """
    if not token:
        raise RuntimeError("ENTSO-E token missing")
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=token)
    end = pd.Timestamp.now(tz="Europe/Brussels").normalize()
    # 1y of history is plenty for the regime read; cuts cold-start latency.
    start = end - pd.DateOffset(years=1)

    fwd = client.query_crossborder_flows(from_zone, to_zone, start=start, end=end)
    bwd = client.query_crossborder_flows(to_zone, from_zone, start=start, end=end)
    if fwd is None or len(fwd) == 0:
        raise RuntimeError(f"ENTSO-E returned empty {from_zone}→{to_zone} flow")
    if bwd is None or len(bwd) == 0:
        raise RuntimeError(f"ENTSO-E returned empty {to_zone}→{from_zone} flow")

    # Both series are tz-aware (Europe/Brussels). Align on the same index by
    # converting to UTC for arithmetic, then resample to daily mean × 24 to
    # express net daily MWh.
    net_mw = fwd.tz_convert("UTC").subtract(bwd.tz_convert("UTC"), fill_value=0.0)
    net_daily = net_mw.resample("D").mean() * 24.0
    df = _tidy(net_daily)
    df.attrs["from_zone"] = from_zone
    df.attrs["to_zone"] = to_zone
    df.attrs["unit"] = "MWh/day (net)"
    return df


# --- Weather forecasts (Energy Meteorologists alignment) --------------------


# Cobblestone names "Energy Meteorologists" as a team function under
# Analytics. Weather is the dominant short-term driver of EU power and gas
# (renewables, FR electric heating, IT/ES gas demand). We pull a unified
# 5-7 day forecast at three regional centroids and compare against a 5-yr
# seasonal normal computed from the Open-Meteo historical archive — same
# calendar window from prior years.
WEATHER_LOCATIONS: dict[str, tuple[float, float]] = {
    "DE": (52.52, 13.41),  # Berlin
    "FR": (48.85,  2.35),  # Paris (electric-heating sensitivity)
    "GB": (51.51, -0.13),  # London
}


def _open_meteo(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_weather_forecast(latitude: float, longitude: float, label: str) -> pd.DataFrame:
    """7-day weather forecast + 5-yr seasonal normal at one regional centroid.

    Returns one DataFrame indexed on the next 7 calendar days with columns:
        - temp_c               daily mean air temperature (°C)
        - wind_max_ms          daily-max 10m wind speed (m/s)
        - wind_gust_max_ms     daily-max 10m wind gust (m/s)
        - cloud_cover_pct      daily mean cloud cover (%)
        - temp_normal_c        5-yr seasonal normal mean temperature (°C)
        - temp_anomaly_c       forecast − normal (°C)
        - wind_normal_max_ms   5-yr seasonal normal daily-max wind speed
        - wind_normal_gust_ms  5-yr seasonal normal daily-max wind gust

    The "5-yr seasonal normal" is computed from the Open-Meteo historical
    archive: pull the same calendar window (forecast date ±3 days) across
    the prior 5 years and take the mean per day-of-year.

    Sources: api.open-meteo.com (forecast) + archive-api.open-meteo.com
    (historical reanalysis). Both free, no auth.
    """
    forecast = _open_meteo(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": latitude, "longitude": longitude,
            "hourly": "temperature_2m,wind_speed_10m,wind_gusts_10m,cloud_cover",
            "forecast_days": 7,
            "timezone": "auto",
        },
    )
    h = forecast.get("hourly") or {}
    times = h.get("time") or []
    if not times:
        raise RuntimeError(f"Open-Meteo forecast empty for {label}")
    fc = pd.DataFrame({
        "time": pd.to_datetime(times),
        "temp": h.get("temperature_2m") or [],
        "wind_speed": h.get("wind_speed_10m") or [],
        "wind_gust": h.get("wind_gusts_10m") or [],
        "cloud": h.get("cloud_cover") or [],
    }).set_index("time")
    fc_daily = pd.DataFrame({
        "temp_c": fc["temp"].resample("D").mean(),
        "wind_max_ms": fc["wind_speed"].resample("D").max(),
        "wind_gust_max_ms": fc["wind_gust"].resample("D").max(),
        "cloud_cover_pct": fc["cloud"].resample("D").mean(),
    }).dropna(how="all")

    # 5-yr seasonal normal from historical archive — pull a window covering
    # the next 7 days plus a ±3-day buffer for matching, across each of the
    # last 5 calendar years.
    today = pd.Timestamp.now().normalize()
    horizon_end = today + pd.Timedelta(days=8)
    archive_segments: list[pd.DataFrame] = []
    for years_back in range(1, 6):
        seg_start = (today - pd.DateOffset(years=years_back) - pd.Timedelta(days=3)).date()
        seg_end = (horizon_end - pd.DateOffset(years=years_back) + pd.Timedelta(days=3)).date()
        try:
            arc = _open_meteo(
                "https://archive-api.open-meteo.com/v1/archive",
                {
                    "latitude": latitude, "longitude": longitude,
                    "start_date": seg_start.isoformat(),
                    "end_date": seg_end.isoformat(),
                    "daily": "temperature_2m_mean,wind_speed_10m_max,wind_gusts_10m_max",
                    "timezone": "auto",
                },
            )
            d = arc.get("daily") or {}
            if not d.get("time"):
                continue
            seg = pd.DataFrame({
                "time": pd.to_datetime(d["time"]),
                "temp_c": d.get("temperature_2m_mean") or [],
                "wind_max_ms": d.get("wind_speed_10m_max") or [],
                "wind_gust_max_ms": d.get("wind_gusts_10m_max") or [],
            }).set_index("time")
            archive_segments.append(seg)
        except Exception as e:
            log.info("Open-Meteo archive %dy-back fetch failed for %s: %s",
                     years_back, label, e)

    normals = pd.DataFrame(
        index=fc_daily.index,
        columns=["temp_normal_c", "wind_normal_max_ms", "wind_normal_gust_ms"],
        dtype=float,
    )
    if archive_segments:
        all_archive = pd.concat(archive_segments).sort_index()
        # For each forecast date, average historical readings within the same
        # ±3-day calendar window (across all 5 years).
        for forecast_date in fc_daily.index:
            mask = (
                (all_archive.index.month == forecast_date.month)
                & (
                    abs(
                        all_archive.index.dayofyear
                        - pd.Timestamp(forecast_date).dayofyear
                    )
                    <= 3
                )
            )
            window = all_archive[mask]
            if window.empty:
                continue
            normals.loc[forecast_date, "temp_normal_c"] = float(window["temp_c"].mean())
            normals.loc[forecast_date, "wind_normal_max_ms"] = float(
                window["wind_max_ms"].mean()
            )
            normals.loc[forecast_date, "wind_normal_gust_ms"] = float(
                window["wind_gust_max_ms"].mean()
            )

    out = fc_daily.join(normals)
    out["temp_anomaly_c"] = out["temp_c"] - out["temp_normal_c"]
    out.index.name = "date"
    out.attrs["label"] = label
    out.attrs["lat"] = latitude
    out.attrs["lon"] = longitude
    return out


# --- LNG signal -------------------------------------------------------------


# 1 MWh = 3.41214 MMBtu — used to convert JKM (USD/MMBtu) to a TTF-comparable
# EUR/MWh basis. Standard conversion factor; lives here so any future LNG
# fetcher uses the same constant.
MMBTU_PER_MWH = 3.41214


def fetch_jkm() -> pd.DataFrame:
    """JKM (Japan-Korea Marker) LNG futures front-month, in USD/MMBtu.

    Cobblestone explicitly trades pipeline gas + LNG; JKM is the Asian LNG
    benchmark and the natural counterparty to TTF in the Europe-vs-Asia
    arbitrage that drives global LNG flows. We surface JKM as USD/MMBtu
    (the native trading unit) and let the derived `ttf_jkm_spread` convert
    to EUR/MWh for the TTF comparison.

    Source: Yahoo Finance `JKM=F`. Free, daily, ~2y of history available.
    Documented as Cobblestone-relevant LNG signal — auxiliary metric only,
    not a primary tile.
    """
    return _yahoo("JKM=F")


# --- FX helpers ------------------------------------------------------------


def fetch_eurusd() -> pd.DataFrame:
    """EUR/USD daily close (1 EUR = X USD). Used by clean dark spread."""
    return _yahoo("EURUSD=X")


def fetch_gbpeur() -> pd.DataFrame:
    """GBP→EUR rate (1 GBP = X EUR). Used to convert GB power to EUR/MWh.

    Yahoo's `GBPEUR=X` returns EUR-per-GBP directly.
    """
    return _yahoo("GBPEUR=X")
