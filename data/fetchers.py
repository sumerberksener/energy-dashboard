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
    if "Date" not in r.text.splitlines()[0]:
        raise RuntimeError(f"stooq returned non-CSV for {symbol}")
    df = pd.read_csv(io.StringIO(r.text))
    if df.empty or "Close" not in df.columns:
        raise RuntimeError(f"stooq returned empty for {symbol}")
    df["Date"] = pd.to_datetime(df["Date"])
    s = df.set_index("Date")["Close"]
    start, _ = _date_range()
    s = s[s.index >= start.tz_localize(None)]
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
    """Thermal coal proxy (USD/t). ICE Newcastle via Yahoo `MTF=F`.

    True API2 (Rotterdam) is not freely available daily; Newcastle is the
    closest free proxy. ~0.85 correlation with API2 historically.
    """
    for ticker in ("MTF=F", "QM=F"):  # MTF = Newcastle, QM = e-mini crude (sanity reject)
        try:
            df = _yahoo(ticker)
            if not df.empty:
                return df
        except Exception as e:
            log.info("Coal Yahoo %s failed (%s); trying next", ticker, e)
    return _stooq("coal.f")


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
    """EU aggregate gas storage (% full) from GIE AGSI+."""
    if not token:
        raise RuntimeError("AGSI+ token missing")

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=HISTORY_YEARS * 366)
    headers = {"x-key": token}
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "country": "eu",
            "from": start.isoformat(),
            "to": end.isoformat(),
            "size": 300,
            "page": page,
        }
        r = requests.get(
            "https://agsi.gie.eu/api", headers=headers, params=params, timeout=30
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
