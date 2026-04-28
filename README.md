# EU Energy Markets — Morning Brief

A 5-minute morning briefing for an energy trader: today's prints on the five most-watched EU energy metrics, 5-year history, and rule-based observations.

> **🔗 Live demo:** _add your Streamlit Community Cloud URL here once deployed_
>
> **📸 Screenshot:** _add `screenshot.png` to the repo and embed it here once the app is running with real data_

---

## What it does

- **Today, at a glance.** Five metric cards across the top show the latest print, daily change, a 30-day sparkline, and a rule-based "headline" tag (historically high / extended / outsized move / well-supplied / etc.).
- **5-year context.** A tab per metric drills into a Plotly chart with the 50-day moving average, 10–90th-percentile band, and a stats table (1d/1w/1m/1y change, 5y high/low, percentile rank).
- **Morning brief paragraph.** The sidebar surfaces the 3 most-extreme signals across all five metrics in plain language — a one-glance summary the trader can scan in seconds.
- **Trader-friendly definitions.** Each metric has a 1–2 sentence explanation of what it is and why it matters, so a desk newcomer can ramp up without reading research notes.
- **Resilient to flaky data.** Each fetcher has a documented fallback chain. If a live fetch fails, the dashboard falls back to a cached parquet snapshot and shows a "stale" badge instead of going blank.

## The 5 metrics

| # | Metric | Unit | Source (free) | Why it matters |
|---|---|---|---|---|
| 1 | **TTF Front-Month Natural Gas** | EUR/MWh | Yahoo Finance → stooq | The European wholesale gas benchmark — the single most-watched price in EU energy markets. |
| 2 | **Brent Crude Front-Month** | USD/bbl | Yahoo Finance → stooq | The global oil benchmark; sets cross-commodity tone, refined-product economics, and inflation pricing. |
| 3 | **EUA December Carbon Futures** | EUR/tCO₂ | stooq → KRBN proxy | EU ETS carbon price; direct input to power-generation marginal cost; drives coal-vs-gas fuel switching. |
| 4 | **German Day-Ahead Baseload Power** | EUR/MWh | ENTSO-E Transparency Platform | Europe's largest power market and de-facto continental power benchmark. |
| 5 | **EU Aggregate Gas Storage** | % full | GIE AGSI+ | Daily fundamentals signal — storage trajectory vs the 5-year seasonal average is the most-cited supply/demand balance indicator. |

The mix is deliberate: four price benchmarks (gas, oil, carbon, power) plus one fundamental (storage), giving the trader both market-action and balance signals at a glance.

## Architecture

```
energy-dashboard/
├── app.py                  # Streamlit entrypoint — page layout
├── config.py               # Metric metadata & signal thresholds
├── data/
│   ├── fetchers.py         # 5 fetch functions (no Streamlit dep)
│   ├── cache.py            # @st.cache_data wrappers + parquet fallback
│   └── store/              # parquet snapshots (gitignored)
├── analysis/
│   ├── stats.py            # rolling MA, percentile rank, z-score, etc.
│   └── signals.py          # rule-based observations + morning brief
├── ui/
│   ├── cards.py            # top-row metric cards w/ sparklines
│   ├── charts.py           # 5-yr Plotly charts + stats tables
│   └── brief.py            # sidebar morning-brief panel
├── tests/
│   └── test_fetchers.py    # live-API smoke tests
└── .streamlit/
    ├── config.toml         # dark theme
    └── secrets.toml.example
```

The codebase intentionally separates concerns: `data/` knows nothing about Streamlit, `analysis/` is pure pandas/numpy, and `ui/` is the only layer that talks to Streamlit. This separation is what makes the planned ML/NLP extensions (see Roadmap) drop-in additions instead of rewrites.

## Run locally

You'll need free API tokens for ENTSO-E and GIE AGSI+ (both take ~2 minutes).

1. **Get tokens** (one-time):
   - ENTSO-E: register at <https://transparency.entsoe.eu/> → My Account Settings → Generate token.
   - AGSI+: register at <https://agsi.gie.eu/account>.

2. **Clone & install:**
   ```bash
   git clone <your-repo-url>
   cd energy-dashboard
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Set secrets:**
   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   # edit .streamlit/secrets.toml and paste your tokens
   ```

4. **Run:**
   ```bash
   streamlit run app.py
   ```
   Open <http://localhost:8501>. First load takes 20–30 seconds while the five fetchers populate the local parquet cache; subsequent loads are instant.

## Deploy to Streamlit Community Cloud

1. Push this repo to GitHub (public or private).
2. Sign in at <https://share.streamlit.io> with your GitHub account.
3. Click **Create app** → pick this repo → branch `main` → main file `app.py`.
4. Click **Advanced settings → Secrets** and paste:
   ```toml
   ENTSOE_TOKEN = "..."
   AGSI_TOKEN   = "..."
   ```
5. Deploy. The app sleeps after ~7 days of inactivity; first wake takes ~10 seconds.

## Run the tests

```bash
pytest -q tests/test_fetchers.py
```

Tests hit live APIs and skip gracefully when offline or when a token isn't set in env vars (`ENTSOE_TOKEN`, `AGSI_TOKEN`).

## Roadmap

The current release is **v0.1**: rule-based observations, no forecasting. The architecture is built to make each next step a self-contained addition rather than a rewrite.

| Version | Theme | What ships |
|---------|-------|------------|
| **v0.2** | Hands-off mornings | Daily auto-refresh via GitHub Actions cron + emailed morning-brief PDF. |
| **v0.3** | News awareness | Headline ingestion (Reuters / Bloomberg / Argus RSS) + per-metric sentiment scoring. |
| **v0.4** | Forecasting | Directional next-day price model (logistic regression baseline → gradient boosting → LSTM). UI displays predicted direction with calibrated confidence. |
| **v0.5** | NLP trade ideas | Fine-tune a small LM on energy news to extract themes and surface candidate trade ideas with rationale. |
| **v0.6** | Backtesting | A backtesting harness that replays signals against historical PnL on a simple long/short rule, so signal quality is measured rather than asserted. |

## Honest limitations

- **EUA free-data quality is the weakest link.** Stooq's `co2.f` is the cleanest free proxy I've found for ICE EUA December; if it fails, the fallback `KRBN` ETF blends EUA with RGGI and CCA — useful directionally but not a clean EUA print. A paid feed would resolve this.
- **No intraday data.** Daily granularity by design — the trader uses this as a morning summary, not a live blotter.
- **Observations are rule-based, not predictive.** Calling them "suggestions" would overstate the rigor; they're descriptive flags. The Roadmap lays out where forecasting actually lives.
- **No backtesting yet.** Until v0.6, signal quality is asserted by construction, not measured.

## Data sources

- ICE TTF & Brent futures via [Yahoo Finance](https://finance.yahoo.com) and [stooq.com](https://stooq.com)
- ICE EUA carbon via stooq
- German day-ahead power via the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/)
- EU gas storage via [GIE AGSI+](https://agsi.gie.eu/)

## Disclaimer

This dashboard is informational. Rule-based observations are descriptive flags computed from public market data and are **not investment advice, not a recommendation, and not a forecast**. Always do your own analysis.
