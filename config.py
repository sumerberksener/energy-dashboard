"""Metric metadata. Single source of truth for the 7 dashboard/brief metrics.

The metric set is anchored to the brief's thesis: gas + carbon → power curve.
Five primary metrics are fetched directly; two are derived (clean spark and
clean dark spreads) — these are the bridge from gas/carbon fundamentals to
the gas-fired and coal-fired generator economics that drive power pricing.
"""
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
    higher_is: str   # "bullish-power" | "bearish-power" | "supply-rich" | "margin-rich"
    derived: bool = False
    delta_unit: str = "pct"   # "pct" (price-like, never crosses 0) or "abs" (spreads — pct meaningless across zero)
    is_fundamentals_input: bool = False  # True ⇒ feeds derived metrics but isn't a top-row card (coal, EUR/USD, ...)


METRICS: list[Metric] = [
    # --- Primary cards (what Cobblestone actually trades) ----------------
    Metric(
        key="ttf",
        name="TTF Front-Month Natural Gas",
        short_name="TTF Gas",
        unit="EUR/MWh",
        source="ICE (via Yahoo Finance)",
        definition=(
            "TTF (Title Transfer Facility) is the European wholesale natural gas benchmark, "
            "traded at a virtual hub in the Netherlands. The front-month contract reflects "
            "expected gas for next-month delivery and is the dominant input to European "
            "power generation cost."
        ),
        color="#f9e2af",
        higher_is="bullish-power",
    ),
    Metric(
        key="storage",
        name="EU Aggregate Gas Storage",
        short_name="EU Storage",
        unit="% full",
        source="GIE AGSI+",
        definition=(
            "Fill level of EU gas storage facilities, aggregated across member states by "
            "Gas Infrastructure Europe (AGSI+). Storage trajectory vs the 5-year seasonal "
            "average is the most-cited supply/demand balance signal in EU gas — and "
            "feeds directly into TTF curve shape and winter-power risk."
        ),
        color="#cba6f7",
        higher_is="supply-rich",
    ),
    Metric(
        key="eua",
        name="EUA December Carbon Futures",
        short_name="EUA Carbon",
        unit="EUR/tCO2",
        source="ICE (via stooq / KRBN proxy)",
        definition=(
            "European Union Allowances (EUA) are the carbon emission permits traded under "
            "the EU Emissions Trading System. The December contract is the most liquid "
            "and is a direct input to power-generation marginal cost — shaping the long end "
            "of the power curve via dispatch economics for fossil generation."
        ),
        color="#a6e3a1",
        higher_is="bullish-power",
    ),
    Metric(
        key="de_power",
        name="German Day-Ahead Baseload Power",
        short_name="DE Power",
        unit="EUR/MWh",
        source="ENTSO-E Transparency Platform",
        definition=(
            "Day-ahead clearing price for one MWh in each hour of the next delivery day "
            "in the German-Luxembourg bidding zone, averaged to a daily baseload print. "
            "Germany is Europe's largest power market and the de-facto continental "
            "front-curve benchmark."
        ),
        color="#89b4fa",
        higher_is="bullish-power",
    ),
    Metric(
        key="gb_power",
        name="GB Day-Ahead Baseload Power",
        short_name="GB Power",
        unit="EUR/MWh",
        source="ENTSO-E (GB bidding zone) · GBP→EUR converted",
        definition=(
            "Day-ahead clearing price for one MWh in each hour of next-day delivery in "
            "the GB bidding zone, averaged to a daily baseload print and converted from "
            "GBP to EUR via the daily FX close. Cobblestone explicitly trades GB power; "
            "the DE − GB spread captures Continent-vs-Island dynamics and IFA/IFA2 "
            "interconnector flow signals."
        ),
        color="#74c7ec",
        higher_is="bullish-power",
    ),
    Metric(
        key="renewable_share",
        name="DE Wind + Solar Forecast Share",
        short_name="Renewables",
        unit="% of load",
        source="ENTSO-E (wind+solar forecast / load forecast)",
        definition=(
            "Day-ahead forecast wind + solar generation as a percentage of forecast load "
            "in the German-Luxembourg bidding zone. After gas, this is the single biggest "
            "driver of day-ahead power: high renewable share compresses the residual-load "
            "curve and pushes prices down (or negative); low share lifts gas-fired plants "
            "into the merit order. Daily aggregation = simple mean across hourly forecasts."
        ),
        color="#94e2d5",
        higher_is="supply-rich",
    ),
    Metric(
        key="clean_spark",
        name="Clean Spark Spread (CCGT, day-ahead)",
        short_name="Clean Spark",
        unit="EUR/MWh",
        source="Derived (DE Power − TTF/η_gas − EUA × EF_gas)",
        definition=(
            "Margin of a 50%-efficient combined-cycle gas plant, net of carbon cost: "
            "Power − Gas/η − Carbon × emission factor. When the clean spark is positive "
            "and rising, gas-fired generation is in-the-money and gas is the marginal "
            "European fuel — a regime in which TTF moves transmit directly into the power curve."
        ),
        color="#fab387",
        higher_is="margin-rich",
        derived=True,
        delta_unit="abs",
    ),
    Metric(
        key="clean_dark",
        name="Clean Dark Spread (hard coal, day-ahead)",
        short_name="Clean Dark",
        unit="EUR/MWh",
        source="Derived (DE Power − Coal/η_coal − EUA × EF_coal)",
        definition=(
            "Margin of a 40%-efficient hard-coal plant, net of carbon cost: "
            "Power − Coal/η − Carbon × emission factor. The dark-vs-spark differential "
            "signals fuel switching: when CDS exceeds CSS, coal is in-the-money over gas. "
            "Coal isn't a Cobblestone book, but the dark spread is still a real desk-watched "
            "signal because it shapes gas-side risk."
        ),
        color="#f38ba8",
        higher_is="margin-rich",
        derived=True,
        delta_unit="abs",
    ),
    # --- Fundamentals inputs (inputs to derived metrics; not top-row cards) -----
    Metric(
        key="coal",
        name="API2 / Newcastle Thermal Coal Proxy",
        short_name="Coal",
        unit="USD/t",
        source="ICE Newcastle (proxy via Yahoo Finance)",
        definition=(
            "Thermal coal benchmark. API2 (Rotterdam, NAR 6000) is the canonical European "
            "reference; ICE Newcastle is a free-data proxy with documented basis "
            "(~0.85 historical correlation). Cobblestone doesn't trade coal directly — "
            "this is a fundamentals input feeding the Clean Dark spread."
        ),
        color="#7f849c",
        higher_is="bullish-power",
        is_fundamentals_input=True,
    ),
]


METRICS_BY_KEY: dict[str, Metric] = {m.key: m for m in METRICS}
PRIMARY_KEYS: list[str] = [m.key for m in METRICS if not m.derived]
DERIVED_KEYS: list[str] = [m.key for m in METRICS if m.derived]
TOP_ROW_METRICS: list[Metric] = [m for m in METRICS if not m.is_fundamentals_input]
FUNDAMENTALS_METRICS: list[Metric] = [m for m in METRICS if m.is_fundamentals_input]


# --- Spread parameters ------------------------------------------------------
# Industry-standard CCGT and hard-coal plant assumptions. Documented here so
# they're auditable from a single place.

GAS_EFFICIENCY = 0.50           # η for modern CCGT
GAS_EMISSION_FACTOR = 0.184     # tCO2 per MWh_thermal (natural gas combustion)

COAL_EFFICIENCY = 0.40          # η for modern hard-coal plant
COAL_EMISSION_FACTOR = 0.34     # tCO2 per MWh_thermal (hard coal NAR 6000)
COAL_CALORIFIC_MWH_PER_T = 6.978  # 25.12 GJ/t × 0.27778 MWh/GJ → MWh_thermal per tonne


# --- Signal thresholds ------------------------------------------------------
PERCENTILE_HIGH = 90
PERCENTILE_LOW = 10
SIGMA_EXTENDED = 2.0
ZSCORE_OUTSIZED = 2.0

HISTORY_YEARS = 5
CACHE_TTL_SECONDS = 60 * 60

# Freshness: a series whose latest row is older than this is flagged STALE in
# the snapshot, the markdown table, and the JSON sent to the AI.
STALE_AFTER_DAYS = 5


# --- Submission identity ----------------------------------------------------
AUTHOR_NAME = "Sumer Sener"
AUTHOR_EMAIL = "sumerberksener@gmail.com"
SUBMISSION_TITLE = "European Cross-Commodity Risk Pack: Gas + Carbon → Power Curve Implications"
