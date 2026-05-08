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
