"""Static EU power-curve release calendar.

Hand-maintained list of recurring data publications and policy events that
move European Power, Gas, and Emissions risk. Used as the deterministic
spine of the desk note's "This week ahead" block. AI-driven dated items
(from news, e.g. "Friday: OPEC+ meeting") are layered on top by the
extract pass via the `watchlist_dated` field.

Schema kept minimal: weekday (0=Monday … 6=Sunday), name, relevance,
optional time_utc string. Tier marks how universally the event matters
to a Cobblestone-style desk: 1 = always watch, 2 = secondary.

Layer rule: data-only module, no Streamlit / Anthropic / pandas required
at import. Lives in `data/` parallel to `data/policy_facts.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional


LAST_REVIEWED = date(2026, 5, 8)


_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass(frozen=True)
class Event:
    weekday: int          # 0=Mon, 1=Tue, … 4=Fri (events on Sat/Sun rare)
    name: str             # short, action-oriented
    relevance: str        # one sentence on why a trader cares
    time_utc: Optional[str] = None  # HH:MM, optional
    tier: int = 1         # 1 = always show, 2 = show when slot available


# Order roughly chronological through a week.
RECURRING_EVENTS: list[Event] = [
    Event(
        weekday=1,
        name="AGSI+ daily storage print",
        relevance="First read on the week's gas injection / withdrawal pace; sets the tone for TTF curve shape.",
        time_utc="08:00",
        tier=1,
    ),
    Event(
        weekday=2,
        name="EEX EUA primary auction (Mon–Thu daily; Wed is largest volume)",
        relevance="Supply-side EUA signal; auction clearing relative to spot reads as ETS demand strength.",
        time_utc="09:00",
        tier=1,
    ),
    Event(
        weekday=2,
        name="ENTSO-E DE_LU + GB next-week wind/solar forecast refresh",
        relevance="Sets the residual-load curve a week out; outsized prints move power Cal+1 directionally.",
        tier=1,
    ),
    Event(
        weekday=3,
        name="US EIA weekly crude inventories",
        relevance="Crude — and via crack spreads, refined-products — feed back into LNG arb economics.",
        time_utc="14:30",
        tier=2,
    ),
    Event(
        weekday=4,
        name="EIA weekly natural gas storage report",
        relevance="US storage trajectory anchors LNG export pricing into NW Europe — direct TTF transmission.",
        time_utc="14:30",
        tier=1,
    ),
    Event(
        weekday=4,
        name="ENTSO-E weekly day-ahead volumes / system-balance summary",
        relevance="Reads the European generation mix in last 7d — confirms or breaks the Cal+1 thesis.",
        tier=2,
    ),
]


def label_weekday(weekday: int) -> str:
    return _WEEKDAY_LABELS[weekday % 7]


def select_for_week(today: Optional[date] = None, max_items: int = 5) -> list[Event]:
    """Return upcoming events through end-of-week, in chronological order.

    `today` defaults to today's UTC date. Tier-1 events come first; tier-2
    fill any remaining slots up to `max_items`. If today is Friday or later
    in the week, the list rolls forward into next week so the brief always
    has *something* in the pipeline.
    """
    today = today or datetime.utcnow().date()
    today_dow = today.weekday()

    # Tier-1 events still ahead this week (today's weekday or later)
    tier1_this_week = [e for e in RECURRING_EVENTS if e.tier == 1 and e.weekday >= today_dow]
    tier2_this_week = [e for e in RECURRING_EVENTS if e.tier == 2 and e.weekday >= today_dow]
    tier1_next_week = [e for e in RECURRING_EVENTS if e.tier == 1]
    tier2_next_week = [e for e in RECURRING_EVENTS if e.tier == 2]

    out: list[Event] = []
    for pool in (tier1_this_week, tier2_this_week, tier1_next_week, tier2_next_week):
        for e in pool:
            if e in out:
                continue
            out.append(e)
            if len(out) >= max_items:
                return out
    return out


def days_since_review(today: Optional[date] = None) -> int:
    today = today or date.today()
    return (today - LAST_REVIEWED).days
