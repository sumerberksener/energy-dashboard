"""Weather event detection — convert 7-day forecasts into desk-relevant events.

Weather is the dominant short-term driver of EU power and gas. Cobblestone
explicitly names "Energy Meteorologists" as a team function under Analytics.
A scalar °C anomaly chip on the regime strip is direction-correct but
under-uses the data. This module turns the forecast DataFrames produced by
`data.fetchers.fetch_weather_forecast` into structured events with
trader-facing trading implications.

Four event types — each named after how a trader would describe it:
    cold_snap    — extended cold (heating-demand bullish)
    heat_dome    — extended heat (cooling-demand bullish, gas-demand bearish)
    wind_drought — multi-day low-wind + cloud cover (renewables collapse)
    storm        — single-day extreme wind (renewable surge then potential cut-off)

Pure pandas/numpy. No Streamlit, no Anthropic — this is rule-based intelligence
on the meteorological data, not an AI pass. The AI extract pass can consume
the structured events as additional context but doesn't generate them.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Iterable

import pandas as pd


# --- Thresholds (calibrated for EU temperate-zone trading desks) ------------


# Temperature anomaly thresholds in °C vs 5-yr seasonal normal.
COLD_SNAP_ANOMALY = -3.0      # 2+ consecutive days below this fires a cold snap
COLD_SNAP_SEVERE = -6.0       # any day below this upgrades to severe
HEAT_DOME_ANOMALY = +3.0
HEAT_DOME_SEVERE = +6.0

# Wind drought (a.k.a. dunkelflaute when cold + dark + still).
WIND_DROUGHT_MAX_MS = 5.0     # daily-max wind speed below this signals stillness
WIND_DROUGHT_CLOUD_PCT = 60.0 # plus cloudy ⇒ solar also offline
WIND_DROUGHT_MIN_DAYS = 2     # need at least 2 consecutive days

# Storm: peak gust threshold. Open-Meteo gust forecasts can spike on a
# single hour and aren't always desk-relevant. Threshold set at 28 m/s
# (~100 km/h) — full Beaufort-10 storm force — and dedupe so we surface
# at most one storm per region in the 7-day window. Severity steps up
# at 35 m/s (~125 km/h, severe storm).
STORM_GUST_MS = 28.0
STORM_GUST_SEVERE = 35.0


@dataclass(frozen=True)
class WeatherEvent:
    """One detected weather event with desk-relevant context.

    The `trading_implication` field is a one-sentence rule-based read,
    NOT a forecast or trade recommendation. The desk decides; this is
    pattern recognition surfaced for the trader.
    """
    type: str                   # "cold_snap" | "heat_dome" | "wind_drought" | "storm"
    region: str                 # "DE" | "FR" | "GB" | "DE+FR" etc.
    start_date: date
    end_date: date
    severity: str               # "mild" | "moderate" | "severe"
    magnitude_label: str        # short human-readable summary
    trading_implication: str    # one-sentence trader-facing read

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        return d

    @property
    def headline(self) -> str:
        """Short label for chip / card heading."""
        type_labels = {
            "cold_snap": "Cold snap",
            "heat_dome": "Heat dome",
            "wind_drought": "Wind drought",
            "storm": "Storm",
        }
        type_label = type_labels.get(self.type, self.type)
        if self.start_date == self.end_date:
            day_part = self.start_date.strftime("%a %d %b")
        else:
            day_part = (
                f"{self.start_date.strftime('%a %d')} – "
                f"{self.end_date.strftime('%a %d %b')}"
            )
        return f"{type_label} · {self.region} · {day_part}"


# --- Detection helpers ------------------------------------------------------


def _consecutive_runs(mask: pd.Series, min_length: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return (start, end) date pairs for runs of `min_length`+ True values.

    `mask` is a date-indexed boolean Series. Returns a list of (start, end)
    inclusive timestamps for each consecutive-True window meeting the length
    requirement. Used for "N consecutive days where anomaly < threshold"
    style detections — the standard trader frame for "this is an event,
    not just a one-day blip."
    """
    if mask.empty:
        return []
    runs: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    current_start: pd.Timestamp | None = None
    last_true: pd.Timestamp | None = None
    for ts, val in mask.items():
        if bool(val):
            if current_start is None:
                current_start = ts
            last_true = ts
        else:
            if current_start is not None and last_true is not None:
                length = (last_true - current_start).days + 1
                if length >= min_length:
                    runs.append((current_start, last_true))
            current_start = None
            last_true = None
    # Tail-flush
    if current_start is not None and last_true is not None:
        length = (last_true - current_start).days + 1
        if length >= min_length:
            runs.append((current_start, last_true))
    return runs


def _detect_temperature_event(
    forecasts: dict[str, pd.DataFrame],
    *,
    event_type: str,
    threshold: float,
    severe_threshold: float,
    direction: str,
    min_days: int = 2,
) -> list[WeatherEvent]:
    """Detect cold-snap or heat-dome events across regions.

    `direction` is "below" (cold snap) or "above" (heat dome). For each region
    independently, find runs of `min_days`+ consecutive days where
    `temp_anomaly_c` crosses the threshold in the specified direction. Severity
    is based on the most extreme reading inside the run.
    """
    events: list[WeatherEvent] = []
    for region, df in forecasts.items():
        if df is None or df.empty or "temp_anomaly_c" not in df.columns:
            continue
        anomaly = df["temp_anomaly_c"].dropna()
        if anomaly.empty:
            continue

        if direction == "below":
            mask = anomaly < threshold
        else:
            mask = anomaly > threshold

        for start, end in _consecutive_runs(mask, min_days):
            window = anomaly.loc[start:end]
            if direction == "below":
                peak = window.min()
                severe = peak < severe_threshold
                magnitude = f"peak {peak:+.1f}°C vs normal"
                action_template = _COLD_ACTIONS
            else:
                peak = window.max()
                severe = peak > severe_threshold
                magnitude = f"peak {peak:+.1f}°C vs normal"
                action_template = _HEAT_ACTIONS

            severity = "severe" if severe else (
                "moderate" if abs(peak) >= abs(threshold) + 1.5 else "mild"
            )
            events.append(WeatherEvent(
                type=event_type,
                region=region,
                start_date=pd.Timestamp(start).date(),
                end_date=pd.Timestamp(end).date(),
                severity=severity,
                magnitude_label=magnitude,
                trading_implication=action_template.get(region, action_template["__default__"]),
            ))
    return events


def _detect_wind_drought(
    forecasts: dict[str, pd.DataFrame],
    *,
    min_days: int = WIND_DROUGHT_MIN_DAYS,
) -> list[WeatherEvent]:
    """Multi-day low-wind + cloudy windows. DE matters most (renewables share)."""
    events: list[WeatherEvent] = []
    for region, df in forecasts.items():
        if df is None or df.empty:
            continue
        if "wind_max_ms" not in df.columns or "cloud_cover_pct" not in df.columns:
            continue
        mask = (df["wind_max_ms"] < WIND_DROUGHT_MAX_MS) & \
               (df["cloud_cover_pct"] > WIND_DROUGHT_CLOUD_PCT)
        for start, end in _consecutive_runs(mask, min_days):
            window = df.loc[start:end]
            min_wind = window["wind_max_ms"].min()
            mean_cloud = window["cloud_cover_pct"].mean()
            severity = "severe" if (end - start).days >= 3 else "moderate"
            events.append(WeatherEvent(
                type="wind_drought",
                region=region,
                start_date=pd.Timestamp(start).date(),
                end_date=pd.Timestamp(end).date(),
                severity=severity,
                magnitude_label=(
                    f"min wind {min_wind:.1f} m/s · cloud {mean_cloud:.0f}%"
                ),
                trading_implication=_WIND_DROUGHT_ACTIONS.get(
                    region, _WIND_DROUGHT_ACTIONS["__default__"]
                ),
            ))
    return events


def _detect_storms(forecasts: dict[str, pd.DataFrame]) -> list[WeatherEvent]:
    """Storm-force gust events, deduped to one per region.

    Open-Meteo can flag gust spikes across multiple consecutive days when a
    single low-pressure system tracks across Europe — surfacing each as a
    separate event clutters the news tab without adding signal. We pick
    the worst single day per region above the threshold and emit one event,
    naming the storm window (start = first qualifying day, end = last).
    """
    events: list[WeatherEvent] = []
    for region, df in forecasts.items():
        if df is None or df.empty or "wind_gust_max_ms" not in df.columns:
            continue
        gust = df["wind_gust_max_ms"].dropna()
        if gust.empty:
            continue
        qualifying = gust[gust >= STORM_GUST_MS]
        if qualifying.empty:
            continue
        peak_ts = qualifying.idxmax()
        peak_val = float(qualifying.max())
        # Storm window: the contiguous run of qualifying days bracketing the peak.
        window_mask = gust >= STORM_GUST_MS
        runs = _consecutive_runs(window_mask, min_length=1)
        window_start, window_end = peak_ts, peak_ts
        for s, e in runs:
            if s <= peak_ts <= e:
                window_start, window_end = s, e
                break

        severity = "severe" if peak_val >= STORM_GUST_SEVERE else "moderate"
        peak_day_str = pd.Timestamp(peak_ts).strftime("%a %d %b")
        events.append(WeatherEvent(
            type="storm",
            region=region,
            start_date=pd.Timestamp(window_start).date(),
            end_date=pd.Timestamp(window_end).date(),
            severity=severity,
            magnitude_label=(
                f"peak gust {peak_val:.0f} m/s (~{peak_val * 3.6:.0f} km/h) "
                f"on {peak_day_str}"
            ),
            trading_implication=_STORM_ACTIONS.get(
                region, _STORM_ACTIONS["__default__"]
            ),
        ))
    return events


# --- Trading-implication templates (region-aware) ---------------------------


_COLD_ACTIONS: dict[str, str] = {
    "DE": (
        "Bullish DE power and TTF — heating demand pulls thermal plant up the "
        "merit order. Spark spread expands; watch DE−GB spread widen on the DE side."
    ),
    "FR": (
        "Strongly bullish FR power — French electric heating means a 1°C "
        "temperature drop adds ~2 GW of demand. FR DA spikes, IFA imports surge."
    ),
    "GB": (
        "Bullish GB power and NBP — UK heating demand lifts the gas-fired "
        "stack; NBP-TTF basis tightens. Watch IFA flow direction reverse."
    ),
    "__default__": (
        "Bullish power and gas — heating-demand spike lifts thermal call. "
        "Spark spread expands; watch curve front-month vs Cal+1."
    ),
}


_HEAT_ACTIONS: dict[str, str] = {
    "DE": (
        "Mild bullish DE power on cooling load, but gas demand softens. "
        "Spark spread compresses; renewables (solar) likely strong — watch "
        "DA print fall midday."
    ),
    "FR": (
        "Bullish FR power on AC load and possible nuclear river-cooling "
        "derating. Watch FR-nuclear availability prints if heat persists."
    ),
    "GB": (
        "Modest bullish GB power on cooling demand; less heating-demand "
        "downside than continental peers (UK AC penetration is lower)."
    ),
    "__default__": (
        "Cooling-load bullish on power, bearish on gas. Spark spread "
        "compresses; solar generation likely above seasonal norm."
    ),
}


_WIND_DROUGHT_ACTIONS: dict[str, str] = {
    "DE": (
        "Dunkelflaute risk — DE is renewables-heaviest, so a still + cloudy "
        "window forces gas-fired up the merit order. Spark widens hard; "
        "DA can print 2x-3x normal levels. Watch storage draw if event extends."
    ),
    "FR": (
        "Less acute than DE (FR is nuclear-baseload), but reduces wind imports "
        "from neighbours and lifts FR DA on the marginal hour."
    ),
    "GB": (
        "Significant — GB has high wind share (>30% in normal years). "
        "Gas-fired stack takes load; NBP and GB DA both rise; watch GB-FR "
        "interconnector flow reverse to GB-import."
    ),
    "__default__": (
        "Renewables collapse forces thermal plant up the merit order. "
        "Power and gas both bullish; spark spread expands."
    ),
}


_STORM_ACTIONS: dict[str, str] = {
    "DE": (
        "Wind generation likely surges Day 1, then risk of turbine cut-off "
        "if gusts exceed 25 m/s. Bearish DA early, sharp reversal possible. "
        "Watch DE-FR flow swings."
    ),
    "FR": (
        "Strong wind boost to French generation; FR may export to neighbours. "
        "DA print likely below seasonal norm; watch FR-GB IFA flow toward GB."
    ),
    "GB": (
        "GB wind capacity is large — DA likely soft. Cut-off risk if gusts "
        "exceed safety thresholds; opposite tail (sudden tightening) possible."
    ),
    "__default__": (
        "Wind generation surges then risks cut-off above turbine thresholds. "
        "DA likely soft Day 1, watch for rebound if event severs supply."
    ),
}


# --- Public entry point -----------------------------------------------------


def detect_weather_events(
    forecasts: dict[str, pd.DataFrame],
    *,
    max_events: int = 4,
) -> list[WeatherEvent]:
    """Detect cold snaps, heat domes, wind droughts, and storms across regions.

    Args:
        forecasts: dict of {region_label: forecast_df} where each df is the
                   output of `data.fetchers.fetch_weather_forecast`.
        max_events: cap returned events to keep the news-tab surface tight.

    Returns:
        A list of WeatherEvent records sorted by severity (severe → mild),
        then by start date. Capped at `max_events`.
    """
    events: list[WeatherEvent] = []
    events.extend(_detect_temperature_event(
        forecasts,
        event_type="cold_snap",
        threshold=COLD_SNAP_ANOMALY,
        severe_threshold=COLD_SNAP_SEVERE,
        direction="below",
    ))
    events.extend(_detect_temperature_event(
        forecasts,
        event_type="heat_dome",
        threshold=HEAT_DOME_ANOMALY,
        severe_threshold=HEAT_DOME_SEVERE,
        direction="above",
    ))
    events.extend(_detect_wind_drought(forecasts))
    events.extend(_detect_storms(forecasts))

    severity_rank = {"severe": 0, "moderate": 1, "mild": 2}
    events.sort(key=lambda e: (severity_rank.get(e.severity, 3), e.start_date))
    return events[:max_events]


def summarise_anomaly(forecasts: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Per-region 5-day forward mean temperature anomaly (°C) — for the chip.

    Returns {region: anomaly_c} for the next 5 forecast days; missing
    regions are omitted. Mean across days is the simplest single number
    the regime strip can carry.
    """
    out: dict[str, float] = {}
    for region, df in forecasts.items():
        if df is None or df.empty or "temp_anomaly_c" not in df.columns:
            continue
        s = df["temp_anomaly_c"].dropna().head(5)
        if s.empty:
            continue
        out[region] = float(s.mean())
    return out
