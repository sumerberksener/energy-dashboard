"""Data fetchers for the 5 primary metrics + an FX helper.

Pure functions, no Streamlit dependency. Each fetcher returns a tidy DataFrame:
    index: pd.DatetimeIndex (tz-naive, daily, ascending)
    column: "value" (float)
    no duplicate dates, no nulls.

Fallback chains are documented inline. Network errors propagate; the cache
layer above is responsible for falling back to parquet snapshots.

Note on coal: the canonical European thermal-coal benchmark is API2 (Rotterdam
NAR 6000). No reliable free daily feed exists for it. ICE Newcastle (Asian
basin) is used as a proxy — historical correlation ≈ 0.85. Documented as a
known data-quality limitation in the README.
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
    """Thermal coal proxy (USD/t).

    Tries multiple Yahoo Finance tickers for thermal coal futures, in order of
    preference, then falls back to stooq. Each ticker is checked for both
    presence AND freshness — Yahoo `MTF=F` (Newcastle) has been observed to
    return historical-only series with no recent updates, which is worse than
    a clear failure since downstream analytics silently use stale prices.

    True API2 (Rotterdam) is not freely available daily; the candidates here
    are Asian-basin proxies historically correlated ~0.85 with API2.
    """
    candidates = [
        ("MTF=F", _yahoo, "ICE Newcastle (Yahoo)"),
        ("LMC.L", _yahoo, "Lloyds coal ETF (Yahoo)"),
        ("KOL=F", _yahoo, "Coal-vector futures (Yahoo)"),
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
            if age <= 7:  # fresh enough — accept and stop probing
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
    if not token:
        raise RuntimeError("ENTSO-E token missing")
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=token)
    end = pd.Timestamp.now(tz="Europe/Brussels").normalize()
    start = end - pd.DateOffset(years=HISTORY_YEARS)
    ts = client.query_day_ahead_prices("DE_LU", start=start, end=end)
    if ts is None or ts.empty:
        raise RuntimeError("ENTSO-E returned empty for DE_LU")
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


# --- FX helper (used by clean dark spread to convert USD coal to EUR) -------


def fetch_eurusd() -> pd.DataFrame:
    """EUR/USD daily close (1 EUR = X USD)."""
    return _yahoo("EURUSD=X")
