"""Metric metadata. Single source of truth for the 5 dashboard metrics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    short_name: str
    unit: str
    source: str
    definition: str
    color: str
    higher_is: str  # "bullish-price" | "bearish-price" | "supply-rich" — for cross-metric reasoning


METRICS: list[Metric] = [
    Metric(
        key="ttf",
        name="TTF Front-Month Natural Gas",
        short_name="TTF Gas",
        unit="EUR/MWh",
        source="ICE (via Yahoo Finance)",
        definition=(
            "TTF (Title Transfer Facility) is the European wholesale natural gas benchmark, "
            "traded at a virtual hub in the Netherlands. The front-month contract reflects "
            "expected gas for next-month delivery and is the single most-watched price in "
            "EU energy markets."
        ),
        color="#f9e2af",
        higher_is="bullish-price",
    ),
    Metric(
        key="brent",
        name="Brent Crude Front-Month",
        short_name="Brent",
        unit="USD/bbl",
        source="ICE (via Yahoo Finance)",
        definition=(
            "Brent is the global oil price benchmark, derived from North Sea crude. The "
            "front-month futures contract sets the reference for roughly two-thirds of "
            "internationally traded crude and feeds into refined-product, freight, and "
            "inflation pricing."
        ),
        color="#fab387",
        higher_is="bullish-price",
    ),
    Metric(
        key="eua",
        name="EUA December Carbon Futures",
        short_name="EUA Carbon",
        unit="EUR/tCO₂",
        source="ICE (via Yahoo Finance / stooq)",
        definition=(
            "European Union Allowances (EUA) are the carbon emission permits traded under "
            "the EU Emissions Trading System. The December contract is the most liquid; the "
            "price is a direct input to power-generation marginal cost and drives "
            "coal-vs-gas fuel switching."
        ),
        color="#a6e3a1",
        higher_is="bullish-price",
    ),
    Metric(
        key="de_power",
        name="German Day-Ahead Baseload Power",
        short_name="DE Power",
        unit="EUR/MWh",
        source="ENTSO-E Transparency Platform",
        definition=(
            "The day-ahead auction sets the price for delivery of one MWh of electricity in "
            "each hour of the next day. Germany's print is the most-watched in Europe — its "
            "scale and fuel mix make it the de-facto continental power benchmark."
        ),
        color="#89b4fa",
        higher_is="bullish-price",
    ),
    Metric(
        key="storage",
        name="EU Aggregate Gas Storage",
        short_name="EU Storage",
        unit="% full",
        source="GIE AGSI+",
        definition=(
            "The fill level of EU gas storage facilities, aggregated across member states by "
            "Gas Infrastructure Europe (AGSI+). Storage trajectory versus the 5-year "
            "seasonal average is the single most-cited supply/demand balance signal in EU gas."
        ),
        color="#cba6f7",
        higher_is="supply-rich",
    ),
]


METRICS_BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}


# Signal thresholds — kept here so they're tweakable without touching logic.
PERCENTILE_HIGH = 90  # ≥ this → "historically high"
PERCENTILE_LOW = 10   # ≤ this → "historically low"
SIGMA_EXTENDED = 2.0  # |price - 50dMA| / σ ≥ this → "extended"
ZSCORE_OUTSIZED = 2.0  # |daily move| / σ ≥ this → "outsized move"

# Lookback window for percentile / z-score calcs.
HISTORY_YEARS = 5

# Cache TTLs.
CACHE_TTL_SECONDS = 60 * 60  # 1 hour
