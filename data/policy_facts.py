"""Hand-maintained EU ETS supply / policy fact pack.

Used as a deterministic fallback for Section 4 of the desk note when the
day's news flow doesn't surface a specific carbon supply or policy item.

The brief literally asks for *"carbon supply/policy signal."* On quiet news
days, an honest default-fact-pack is better than the bare placeholder. Each
fact below is real, checkable against EU Commission / EU ETS legislation,
and chosen for desk-relevance — i.e. it changes how a trader thinks about
EUA risk over the next 12 months.

Update cadence: review at least monthly. Whenever the EU passes new ETS
legislation, MSR intake rate changes, free-allocation steps fire, or a
linkage agreement is reached, bump `LAST_REVIEWED` and re-rank `priority`.

Layer rule: this module is data-only (no Streamlit, no Anthropic, no pandas
required at import). It exists in `data/` because it functions as a static
data source, parallel to `data/fetchers.py` for live API pulls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


# Bump this whenever you re-curate the FACTS list. The desk-note section 4
# template surfaces the staleness when the fact pack is the source.
LAST_REVIEWED = date(2026, 5, 7)


@dataclass(frozen=True)
class PolicyFact:
    """One ETS supply or policy item, schema-compatible with the AI extract."""
    item: str            # ≤ 18 words, concrete, date-bearing where possible
    side: str            # "supply" | "policy"
    polarity: str        # "bullish-eua" | "bearish-eua" | "neutral"
    source: str          # short reference (typically the legislation or agency)
    why_it_matters: str  # ≤ 25 words on transmission into power-gen marginal cost
    priority: int = 5    # higher = more pressing; ties broken by list order


# Curated as of 2026-05-07. Numbered comments show the underlying citation
# anchor — verify against current EU Commission text before bumping priority.
FACTS: list[PolicyFact] = [
    PolicyFact(
        # CBAM full operational phase began 1 January 2026
        item="CBAM full operational phase live since 1 Jan 2026 — importers paying for embedded emissions",
        side="policy",
        polarity="bullish-eua",
        source="EU Regulation 2023/956 (CBAM)",
        why_it_matters=(
            "Domestic carbon-cost burden gradually levelled with imports; supports EUA "
            "demand floor as carbon leakage protection tightens through 2034."
        ),
        priority=9,
    ),
    PolicyFact(
        # Linear Reduction Factor stepped up to 4.3% in 2024 under Fit-for-55
        item="EU ETS cap declines 4.3% per year through 2030 (linear reduction factor)",
        side="supply",
        polarity="bullish-eua",
        source="Directive (EU) 2023/959 (revised ETS)",
        why_it_matters=(
            "Mechanically tightens supply year-on-year; structural backstop for EUA "
            "across the curve regardless of demand swings."
        ),
        priority=8,
    ),
    PolicyFact(
        # ETS-2 expansion — separate ETS for road transport + buildings, starts 2027
        item="ETS-2 covering road transport + buildings starts 2027 (separate cap and market)",
        side="policy",
        polarity="neutral",
        source="Directive (EU) 2023/959 §III",
        why_it_matters=(
            "Doesn't directly affect EU ETS-1 EUA price; widens the political surface "
            "(consumer carbon cost) which can shape future ETS-1 ambition."
        ),
        priority=7,
    ),
    PolicyFact(
        # MSR intake currently 24%, drops to 12% from 2030
        item="MSR intake rate at 24% through 2029, drops to 12% from 2030",
        side="supply",
        polarity="bullish-eua",
        source="Decision (EU) 2018/410 + 2023 amendment",
        why_it_matters=(
            "Higher-for-longer MSR intake parks 24% of any auction surplus; structural "
            "supply tightener that erodes once 12% rate kicks in."
        ),
        priority=8,
    ),
    PolicyFact(
        # Free allocation phase-out for CBAM sectors over 2026-2034
        item="Free allocation phase-out for CBAM sectors begins 2026, fully removed by 2034",
        side="supply",
        polarity="bullish-eua",
        source="EU Regulation 2023/956 §C",
        why_it_matters=(
            "Steel / cement / aluminium / fertiliser / hydrogen lose free allowances "
            "linearly; auction volume rises, but exposed industrials become forced buyers."
        ),
        priority=7,
    ),
    PolicyFact(
        # Maritime ETS phase-in 2024-2027
        item="Shipping ETS coverage rising from 40% (2024) to 70% (2025) to 100% (2026)",
        side="supply",
        polarity="bullish-eua",
        source="Directive (EU) 2023/959 §II",
        why_it_matters=(
            "Maritime added another ~80–90 MtCO₂/yr of demand at full phase-in; "
            "absorbs allowances without a matching cap increase."
        ),
        priority=6,
    ),
    PolicyFact(
        # EU-UK ETS linkage — discussions resumed but no formal agreement yet
        item="EU-UK ETS linkage discussions ongoing — no formal agreement signed",
        side="policy",
        polarity="neutral",
        source="UK-EU Trade and Cooperation Agreement (TCA) review",
        why_it_matters=(
            "Linkage would converge UKA and EUA prices and reduce CBAM friction on UK "
            "imports; current divergence keeps a tradable basis between the two markets."
        ),
        priority=5,
    ),
]


def select(min_priority: int = 1) -> Optional[PolicyFact]:
    """Return the highest-priority fact above `min_priority`, else None."""
    candidates = [f for f in FACTS if f.priority >= min_priority]
    if not candidates:
        return None
    return sorted(candidates, key=lambda f: -f.priority)[0]


def days_since_review(today: Optional[date] = None) -> int:
    """How long since the fact pack was last refreshed."""
    today = today or date.today()
    return (today - LAST_REVIEWED).days
