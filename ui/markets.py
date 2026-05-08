"""European Markets tab — clickable choropleth map of EU + GB power markets.

The user lands on a Europe-wide map. Each country Cobblestone trades is
shaded by today's day-ahead price (or its 5-yr percentile). Clicking a
country populates a detail panel below the map with that country's chart,
key stats, and a desk-relevant note.

Plotly choropleth + Streamlit's `on_select="rerun"` handles the click capture
without any extra dependencies (plotly is already in use). Falls back to
sub-tabs when no country is selected so the user can still navigate.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analysis import stats
from config import CACHE_TTL_SECONDS
from data import fetchers


@dataclass(frozen=True)
class CountryView:
    code: str           # ENTSO-E bidding zone code
    iso3: str           # ISO 3166-1 alpha-3 (for plotly choropleth)
    label: str          # Display name
    flag: str           # short tag (no emoji)
    color: str          # chart line colour
    note: str           # 1-2 sentence desk-relevant market characterisation
    gas_only: bool = False  # Cobblestone trades the gas book here, not power
    book_note: str = ""     # Optional override displayed under the heading
                            # (e.g. "Gas-only book — power DA shown as a corridor read")


@dataclass(frozen=True)
class _Centroid:
    """Approximate (lat, lon) centroid for placing on-map country labels."""
    lat: float
    lon: float


COUNTRIES: list[CountryView] = [
    CountryView(
        code="DE_LU", iso3="DEU", label="Germany", flag="DE", color="#89b4fa",
        note=(
            "Europe's largest power market. Coal phase-out + 50%+ renewables means "
            "DA prices increasingly track wind/solar forecast and gas. Peak-vs-baseload "
            "spreads widen on dunkelflaute (low wind, low sun) days."
        ),
    ),
    CountryView(
        code="GB", iso3="GBR", label="Great Britain", flag="GB", color="#74c7ec",
        note=(
            "Cobblestone explicitly trades GB. NBP gas and N2EX power are tightly "
            "coupled. DE−GB spread captures Continent-vs-Island dynamics; flow "
            "across IFA/IFA2/Nemo interconnectors arbitrages it. UK ETS (UKA) "
            "premium/discount to EUA is a separate, real signal."
        ),
    ),
    CountryView(
        code="FR", iso3="FRA", label="France", flag="FR", color="#89dceb",
        note=(
            "Nuclear-heavy fleet (~65–70% of generation in normal years). DA price "
            "is highly sensitive to nuclear availability — outages or unplanned "
            "downtime push prices sharply higher. Cold winters add electric-heating "
            "load that no other large EU market carries to the same degree."
        ),
    ),
    CountryView(
        code="NL", iso3="NLD", label="Netherlands", flag="NL", color="#fab387",
        note=(
            "Gas-heavy fleet, tightly coupled to TTF. Major LNG terminals (Gate, "
            "Rotterdam) make NL a cheaper-LNG-arrives-first market. High coastal "
            "wind capacity adds meaningful intra-day volatility."
        ),
    ),
    CountryView(
        code="BE", iso3="BEL", label="Belgium", flag="BE", color="#a6e3a1",
        note=(
            "Densely interconnected with NL, FR, DE, and GB (via Nemo Link). Nuclear "
            "phaseout in progress means BE's price increasingly imports the "
            "marginal generator from neighbours — a useful tell on continental tightness."
        ),
    ),
    CountryView(
        code="IT_NORD", iso3="ITA", label="Italy (North)", flag="IT", color="#f9e2af",
        note=(
            "North zone of Italy's IPEX market. Gas-heavy, supplemented by hydro "
            "and large imports from CH/FR/AT. High gas dependence makes IT_NORD "
            "the most TTF-sensitive of the major continental markets."
        ),
    ),
    CountryView(
        code="ES", iso3="ESP", label="Spain", flag="ES", color="#f38ba8",
        note=(
            "MIBEL market (joint with PT). Largest installed solar capacity in "
            "Europe and isolated from continental grid (only a small FR "
            "interconnector). DA price often decouples sharply from rest of EU — "
            "a separate signal, not redundant with DE/FR."
        ),
    ),
    CountryView(
        code="AT", iso3="AUT", label="Austria", flag="AT", color="#cba6f7",
        note=(
            "Central-European hub coupled into the DE+AT+LU bidding zone until 2018; "
            "now its own zone but still highly imported/exported. Large hydro fleet "
            "balances the gas-heavy core. Useful tell on continental flow direction."
        ),
    ),
    CountryView(
        code="CH", iso3="CHE", label="Switzerland", flag="CH", color="#94e2d5",
        note=(
            "Hydro-dominant (>55% of generation) with significant pumped storage. "
            "CH plays a re-export role between FR/DE/IT — its price often signals "
            "where the continental shortage is sitting that day."
        ),
    ),
    CountryView(
        code="HU", iso3="HUN", label="Hungary", flag="HU", color="#f5c2e7",
        note=(
            "Central-European corridor market — HU's DA price is the cleanest single "
            "tell for AT/SK/RO flow direction, since the HUPX coupling means whichever "
            "neighbour is short for the day exports its scarcity into HU. Gas-fired "
            "generation sets the marginal unit most hours; nuclear at Paks supplies "
            "baseload but not flex. Watch the HU-AT spread on tight days — it inverts "
            "before continental scarcity shows up in DE."
        ),
    ),
    CountryView(
        code="IE_SEM", iso3="IRL", label="Ireland (SEM)", flag="IE", color="#a6e3a1",
        note=(
            "Single Electricity Market — covers the whole island (RoI + NI) and runs as "
            "an isolated grid with only the East-West and Moyle interconnectors to GB. "
            "Wind share regularly exceeds 40% of generation, so DA prints swing harder "
            "on forecast revisions than anywhere else in the book. The GB-IE spread "
            "via the interconnectors is the cleanest read on whether Britain is "
            "exporting cheap wind into the island or pulling expensive gas back out."
        ),
    ),
    CountryView(
        code="SK", iso3="SVK", label="Slovakia", flag="SK", color="#cba6f7",
        gas_only=True,
        book_note=(
            "Gas-only book for Cobblestone — the power DA panel below is shown as a "
            "corridor read, not a tradable position. SK gas is the trade."
        ),
        note=(
            "Cobblestone trades the SK gas book, not SK power. The DA chart is a "
            "useful corridor indicator: SK sits on the CZ-HU power flow and inherits "
            "the marginal unit from whichever side is short, so the print signals "
            "central-European tightness before it propagates west. SK gas itself "
            "(NCG-linked, with Russian-transit overhang) is where the actual exposure sits."
        ),
    ),
]

ISO3_BY_CODE = {c.iso3: c for c in COUNTRIES}

# Approximate label centroids (lat, lon). Values are rough — they only need
# to land inside the country polygon for the on-map text.
LABEL_CENTROIDS: dict[str, _Centroid] = {
    "DEU": _Centroid(51.0, 10.4),
    "GBR": _Centroid(54.5, -2.5),
    "FRA": _Centroid(46.5,  2.2),
    "NLD": _Centroid(52.3,  5.6),
    "BEL": _Centroid(50.6,  4.4),
    "ITA": _Centroid(45.8,  9.5),  # north Italy (IT_NORD zone)
    "ESP": _Centroid(40.4, -3.7),
    "AUT": _Centroid(47.5, 14.5),
    "CHE": _Centroid(46.8,  8.2),
    "HUN": _Centroid(47.2, 19.5),
    "IRL": _Centroid(53.4, -8.2),
    "SVK": _Centroid(48.7, 19.7),
}


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _get_zone_da(zone_code: str) -> pd.DataFrame:
    """Cached per-zone day-ahead fetch — keyed by zone string."""
    try:
        token = st.secrets["ENTSOE_TOKEN"]
    except Exception:
        token = None
    if not token:
        return pd.DataFrame(columns=["value"])
    try:
        if zone_code == "GB":
            return fetchers.fetch_gb_power(token)
        return fetchers.fetch_power_zone(token, zone_code)
    except Exception:
        return pd.DataFrame(columns=["value"])


def _country_da_summary() -> pd.DataFrame:
    """Build a small DataFrame with one row per country: code, latest, percentile."""
    rows = []
    for c in COUNTRIES:
        df = _get_zone_da(c.code)
        if df is None or df.empty:
            rows.append({
                "code": c.code, "iso3": c.iso3, "country": c.label,
                "latest": None, "percentile": None, "available": False,
            })
            continue
        rows.append({
            "code": c.code,
            "iso3": c.iso3,
            "country": c.label,
            "latest": stats.latest(df),
            "percentile": stats.percentile_rank(df),
            "available": True,
        })
    return pd.DataFrame(rows)


def _build_choropleth(summary: pd.DataFrame) -> go.Figure:
    plot_df = summary.dropna(subset=["latest"]).copy()
    if plot_df.empty:
        fig = go.Figure(data=go.Choropleth(locations=[], z=[]))
        fig.update_geos(scope="europe")
        return fig

    # Choropleth fill — Cividis is a perceptually uniform dark-friendly scale.
    fig = go.Figure(data=go.Choropleth(
        locations=plot_df["iso3"],
        z=plot_df["latest"],
        text=plot_df["country"],
        customdata=plot_df[["percentile"]].values,
        colorscale=[
            [0.00, "#22b07d"],   # green — cheap
            [0.50, "#f9e2af"],   # amber — middle
            [1.00, "#f38ba8"],   # red — expensive
        ],
        marker=dict(
            line=dict(color="#cdd6f4", width=1.0),  # bright country borders
            opacity=0.92,
        ),
        colorbar=dict(
            # Plotly v5+ moved colorbar title font into `title.font`;
            # the legacy `titlefont` raises ValueError in current versions.
            title=dict(
                text="EUR/MWh",
                side="right",
                font=dict(color="#cdd6f4", size=11),
            ),
            thickness=14,
            len=0.65,
            outlinewidth=0,
            tickfont=dict(color="#cdd6f4", size=11),
        ),
        hovertemplate=(
            "<b>%{text}</b><br>"
            "DA price: %{z:.2f} EUR/MWh<br>"
            "5y percentile: %{customdata[0]:.0f}<br>"
            "<extra></extra>"
        ),
    ))

    # Always-visible non-traded countries fade into the background — keep them
    # rendered so the map reads as Europe, not just a few coloured fragments.
    #
    # IMPORTANT: dropping `scope="europe"` because Plotly's built-in scope
    # presets override lataxis_range/lonaxis_range and reintroduce a default
    # white backdrop outside the scope's bounds. With explicit bounds + bgcolor
    # the map sits cleanly on the dark theme with no white panels.
    fig.update_geos(
        showcountries=True,
        countrycolor="#313244",
        countrywidth=0.6,
        showland=True,
        landcolor="#1e1e2e",
        showocean=True,
        oceancolor="#11111b",
        showlakes=True,
        lakecolor="#11111b",
        showrivers=False,
        showframe=False,
        showcoastlines=True,
        coastlinecolor="#45475a",
        coastlinewidth=0.4,
        projection_type="mercator",
        center=dict(lat=51, lon=8),
        lataxis_range=[35, 62],
        lonaxis_range=[-12, 26],
        bgcolor="rgba(0,0,0,0)",  # transparent — let the page background show
        visible=True,
    )

    # 2-letter country labels rendered on the map for instant readability.
    label_lats, label_lons, label_text = [], [], []
    for _, row in plot_df.iterrows():
        c = ISO3_BY_CODE.get(row["iso3"])
        ctr = LABEL_CENTROIDS.get(row["iso3"])
        if c is None or ctr is None:
            continue
        label_lats.append(ctr.lat)
        label_lons.append(ctr.lon)
        label_text.append(c.flag)
    if label_lats:
        fig.add_trace(go.Scattergeo(
            lat=label_lats, lon=label_lons, text=label_text,
            mode="text",
            textfont=dict(color="#11111b", size=13, family="Inter, sans-serif"),
            hoverinfo="skip",
            showlegend=False,
        ))

    fig.update_layout(
        height=620,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        dragmode=False,  # disables click-and-drag pan
    )
    return fig


def _line_chart(df: pd.DataFrame, country: CountryView) -> go.Figure:
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=1)
    s = df[df.index >= cutoff]
    fig = go.Figure(
        data=[go.Scatter(
            x=s.index, y=s["value"], mode="lines",
            line=dict(color=country.color, width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f} EUR/MWh<extra></extra>",
        )]
    )
    fig.update_layout(
        title=f"{country.label} — Day-Ahead Baseload, 1Y",
        height=380,
        margin=dict(l=20, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)",
        yaxis=dict(title="EUR/MWh", gridcolor="rgba(255,255,255,0.08)"),
        showlegend=False,
    )
    return fig


def _country_panel(country: CountryView) -> None:
    df = _get_zone_da(country.code)

    heading = f"### {country.flag} · {country.label}"
    if country.gas_only:
        heading += "  ·  _Gas-only book_"
    st.markdown(heading)
    if country.book_note:
        st.caption(f"**Book:** {country.book_note}")
    st.caption(country.note)

    if df is None or df.empty:
        if country.gas_only:
            st.info(
                f"Day-ahead power data for **{country.code}** is unavailable — "
                "panel is a gas-only book; no power exposure to surface."
            )
        else:
            st.warning(
                f"Day-ahead data for **{country.code}** is unavailable. "
                "Confirm `ENTSOE_TOKEN` is set."
            )
        return

    chart_col, stats_col = st.columns([3, 1])
    with chart_col:
        st.plotly_chart(_line_chart(df, country), width="stretch")
    with stats_col:
        last = stats.latest(df)
        d1 = stats.daily_change_pct(df)
        w1 = stats.change_over_pct(df, 5, smooth_window=5)
        m1 = stats.change_over_pct(df, 21)
        p = stats.percentile_rank(df)
        rows = {
            "Latest": f"{last:,.2f} EUR/MWh" if last is not None else "—",
            "1d Δ":   f"{d1:+.2f}%" if d1 is not None else "—",
            "1w Δ":   f"{w1:+.2f}%" if w1 is not None else "—",
            "1m Δ":   f"{m1:+.2f}%" if m1 is not None else "—",
            "5y pctile": f"{p:.0f}" if p is not None else "—",
            "As of":  df.index.max().strftime("%Y-%m-%d"),
        }
        st.markdown("**Key stats**")
        st.dataframe(
            pd.DataFrame(rows.items(), columns=["", "Value"]).set_index(""),
            width="stretch",
        )


def render() -> None:
    """Render the European Markets tab body — map + dynamic country detail."""
    st.markdown(
        "**Click a country on the map** to drill into its day-ahead price chart, "
        "stats, and a desk-relevant market note. Coverage matches Cobblestone's "
        "European book: Germany and GB are also primary cards on the overview "
        "screen; FR / NL / BE / IT / ES / AT / CH / HU / IE are the next-tier "
        "power exposures. SK is shown for the gas book — power DA is a corridor "
        "read only."
    )
    st.markdown("")

    summary = _country_da_summary()

    if summary.empty or not summary["available"].any():
        st.warning(
            "ENTSO-E data unavailable. Set `ENTSOE_TOKEN` in `.streamlit/secrets.toml` "
            "to enable the map. The token is free — see README → How to use."
        )
        return

    fig = _build_choropleth(summary)

    # Streamlit click-event capture. selection_mode="points" returns the
    # ISO3 of the clicked country in event.selection.points[0].location.
    # Disable wheel zoom + modebar — we only need click to drill in.
    event = st.plotly_chart(
        fig,
        width="stretch",
        on_select="rerun",
        selection_mode="points",
        key="markets_map",
        config={
            "displayModeBar": False,
            "scrollZoom": False,
            "doubleClick": False,
            "displaylogo": False,
            "showTips": False,
        },
    )

    selected_iso: str | None = None
    try:
        if event and getattr(event, "selection", None):
            pts = event.selection.get("points", []) if isinstance(event.selection, dict) else getattr(event.selection, "points", [])
            if pts:
                first = pts[0]
                selected_iso = (
                    first.get("location") if isinstance(first, dict) else getattr(first, "location", None)
                )
    except Exception:
        selected_iso = None

    # Render-or-fallback: show clicked country's panel; otherwise sub-tabs as fallback.
    selected = ISO3_BY_CODE.get(selected_iso) if selected_iso else None

    if selected:
        st.markdown("---")
        _country_panel(selected)
        st.caption("_Tip: click another country on the map above to switch view, "
                   "or use the sub-tabs below as a fallback._")
        st.markdown("")

    st.markdown("##### Country sub-tabs (fallback navigation)")
    sub_tabs = st.tabs([c.flag + " · " + c.label for c in COUNTRIES])
    for tab, country in zip(sub_tabs, COUNTRIES):
        with tab:
            _country_panel(country)
