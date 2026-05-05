# Wiki — How to use the EU Energy Cross-Commodity Risk Pack

A short usage guide aimed at the trader on the desk who didn't write this code.

---

## What is this?

A **morning-brief tool** for European Power, Gas, and Emissions traders. It pulls public market data + energy news every weekday morning, computes the cross-commodity signals a desk would otherwise build by hand (clean spark, clean dark, fuel-switch headroom, storage-vs-seasonal, renewables share, DE−GB spread), runs a Claude (Haiku 4.5) two-pass over the structured snapshot to produce an executive summary + structured news themes, and writes a 1–3 page Markdown / PDF brief plus an interactive Streamlit dashboard.

**Two surfaces, same data:**

- **Markdown / PDF brief** — for the cron / inbox / phone. Self-contained, archived per day under `output/<date>/`.
- **Streamlit dashboard** — for sit-down review. Adds clickable map of European markets, per-metric drill-downs, on-demand AI generation, and a Methodology tab.

---

## How do I launch it?

### Interactive dashboard (Streamlit)

```bash
cd ~/Desktop/energy-dashboard
source .venv/bin/activate
streamlit run app.py        # or: just dashboard
```

Opens at <http://localhost:8501>. Stop with Ctrl-C in the terminal.

### Headless brief (CLI)

```bash
cd ~/Desktop/energy-dashboard
source .venv/bin/activate
python scripts/generate_brief.py             # default: two-pass AI, news on
python scripts/generate_brief.py --pdf       # also render PDF (needs pandoc)
python scripts/generate_brief.py --no-news   # skip RSS + news theme extraction
python scripts/generate_brief.py --single-pass  # one Claude call instead of two
# or: just brief
```

Writes everything to `output/<today>/`.

### Daily automation (GitHub Actions)

`.github/workflows/daily.yml` runs the CLI weekday mornings at 07:30 UTC and commits the new artefacts back. Configure repo secrets `ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY` to enable the live run. The cron is a no-op until they're set.

---

## What credentials do I need?

Three free credentials. Store in `.streamlit/secrets.toml` for local dev, or as repo secrets for the cron.

| Service | Used for | Where to register | Time |
|---|---|---|---|
| **ENTSO-E Transparency Platform** | DE / FR / NL / BE / IT / ES day-ahead power, renewable + load forecasts | <https://transparency.entsoe.eu/> → My Account → Generate token. Then **email `transparency@entsoe.eu`** with subject "Restful API access" — they enable it within 1–3 business days. | ~3 days |
| **GIE AGSI+** | EU gas storage (% full) | <https://agsi.gie.eu/account> — token visible after email confirmation | ~5 min |
| **Anthropic Claude** | AI desk note + news theme extraction | <https://console.anthropic.com> → Plans & Billing → add $5 → API Keys → Create Key. Daily run cost: fractions of a cent on Haiku 4.5. | ~5 min |

GB power, TTF, EUA, coal, EUR/USD, GBP/EUR all use unauthenticated public sources (Elexon BMRS, Yahoo Finance, stooq).

---

## How do I read the desk note?

Sections, in order:

1. **Executive summary** — TL;DR (one sentence) + 3–5 sentence Claude-generated narrative grounded in the structured snapshot. Lead with what's most decision-relevant *today*.
2. **Monitor metrics** — 8 primary tiles (TTF, EU Storage, EUA, DE Power, GB Power, Renewables, Clean Spark, Clean Dark) plus fundamentals inputs (Coal). Each row shows latest value, `as_of` date (with `⚠ STALE` flag when old), 1d / 1w deltas, 5y percentile, and a one-line headline.
3. **Gas + LNG arb** — TTF context + EU storage trajectory + the chart that pairs them.
4. **Carbon (EU ETS)** — EUA level + the marginal-cost transmission to gas-fired vs coal-fired generation cost.
5. **Power — Day-Ahead & curve** — DE + GB DA prints, DE−GB spread, clean spreads, fuel-switch reading. Notes on what the spread regime implies for the curve.
6. **Short-term drivers** — DE wind+solar forecast share + the chart. The single biggest day-ahead driver after gas.
7. **Today's themes** — structured news from public RSS feeds, AI-tagged with commodity / polarity / why-it-matters / horizon. Includes a watchlist of upcoming events.
8. **Methodology & sources** — every formula and assumption auditable.

---

## How do I read the dashboard?

- **Status pill** (top right) — `8/8 live` (green) / `n stale` (amber) / `n missing` (red). Hover for per-metric freshness.
- **Regime strip** — five cross-commodity KPIs in one bar: storage vs seasonal, spark−dark differential, DE−GB spread, renewable forecast share, regime tag.
- **Eight metric cards** — each with a `?` tooltip (full definition + source), 1d / 1w / 1m delta chips, sparkline, percentile chip, and STALE badge if stale.
- **Fundamentals inputs strip** — small line below cards showing coal + EUR/USD (inputs to derived metrics, not separately traded).
- **AI Desk Note pane** — click "Generate desk note" to call Claude. Hero TL;DR, theme chips, risk-flag chips, narrative, audit footer.
- **Per-metric tabs** — 5-yr Plotly chart + stats table + observation per metric.
- **European Markets tab** — clickable choropleth of Europe; click a country (DE, GB, FR, NL, BE, IT, ES) to drill into its DA chart, stats, and a desk-relevant market note. Sub-tabs as fallback navigation.
- **Methodology tab** — the thesis, formulas (clean spark / clean dark / switching TTF), signal thresholds, AI workflow design.
- **Sidebar** — aggregate morning brief, cross-market regime tag, per-metric data freshness.

---

## What if something fails?

Designed to soft-fail per fetcher — one source going down doesn't break the brief.

| Symptom | Likely cause | Fix |
|---|---|---|
| **GB Power says no data** | Elexon BMRS endpoint changed or rate-limited | Re-run after a few minutes; if persistent, check `data/fetchers.py::fetch_gb_power` for endpoint URL change |
| **DE Power / Renewables / Storage say no data** | ENTSO-E or AGSI+ token missing or revoked | Verify `.streamlit/secrets.toml` (or env vars). For ENTSO-E specifically, check that you emailed `transparency@entsoe.eu` and got the API-access-enabled confirmation. |
| **Coal flagged STALE for many days** | Free Newcastle Yahoo feed is degraded (known limitation; coal is a fundamentals input only, so the headline metrics still work). The dark spread carries the staleness through. | Document only — paid feed required to fix in production. |
| **News themes section empty** | RSS feeds returning nothing or all filtered out by AI. Ratio is probably wrong. | Run the CLI with `--no-news` to skip; report the bozo-flagged feeds; add or fix feed URLs in `data/news.py::DEFAULT_FEEDS`. |
| **AI narrative says "rule-based fallback"** | `ANTHROPIC_API_KEY` missing or invalid | Check that the key starts `sk-ant-…` and is set in secrets / env. The CLI prints which path was taken. |
| **Streamlit shows old data** | Browser-cached or in-memory `@st.cache_data` (1h TTL) | Click the **Refresh data** button in the dashboard header, or add `?ttl=0` to the URL. |
| **GitHub Actions run failed** | Most likely a token expired or the upstream shape changed | Check the Actions log; the Elexon, ENTSO-E, AGSI+, and Yahoo paths all log explicit error reasons. |

---

## What's a "good" morning to start with this?

When **at least 7/8 metrics show green** in the status pill and the news section has 3+ themes, the brief is fully populated and the executive summary will be at its sharpest. When fewer are live, the brief still emits — it just leans more on whatever's available and explicitly names the gaps.

A tight regime to watch: **storage well below seasonal + clean spark high + renewables low + GB premium widening → bullish power across the curve**. The regime strip surfaces all four in one bar.

---

## Where do I find...

| Item | Path |
|---|---|
| Latest Markdown desk note | `output/<today>/desk_note_<today>.md` |
| Latest PDF (when generated) | `output/<today>/desk_note_<today>.pdf` |
| Today's metric snapshot CSV | `output/<today>/data/snapshot.csv` |
| Per-metric 5-yr CSVs | `output/<today>/data/<metric>.csv` |
| The exact JSON Claude saw | `output/<today>/data/ai_snapshot.json` |
| AI extract output (themes / risk flags / TL;DR) | `output/<today>/data/ai_themes.json` |
| AI news theme extraction | `output/<today>/data/ai_news_themes.json` |
| Generated charts | `output/<today>/charts/*.png` |
| Full AI request/response logs | `ai/logs/<today>.jsonl` |
| Versioned prompts | `ai/prompts/*.md` |
| Plant assumptions (η, EF, calorific) | `config.py` |
| Signal thresholds (`PERCENTILE_HIGH`, `SIGMA_EXTENDED`, etc.) | `config.py` |
| Roadmap of what's next | `README.md` → "What I'd do with another week" |

---

## Conventions worth knowing

- **`data/`** is Streamlit-free (pure pandas + requests). Don't import streamlit there.
- **`analysis/`** is pure pandas/numpy.
- **`ai/`** is the only module that touches the Anthropic SDK. Every call goes through `ai/client.py` and is logged to `ai/logs/<date>.jsonl`.
- **`ui/`** + `app.py` are the only Streamlit-aware code.
- Spreads (Clean Spark, Clean Dark) report **absolute** EUR/MWh deltas; everything else reports **percentage** deltas. The Metric registry's `delta_unit` field decides.
- Weekly deltas (`1w Δ`) compare the **5-day trailing mean today vs the 5-day trailing mean 5 business days ago** — robust to single-day holiday spikes.
- Data older than `STALE_AFTER_DAYS` (5) triggers a `⚠ STALE` flag everywhere it surfaces.

---

## Disclaimer

Observations are rule-based and informational, **not investment advice**. Always do your own analysis.
