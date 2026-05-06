# Energy Dashboard — Tasks & Improvements

A living worklist for the Cobblestone case-study repo. Owned by Sumer; edited by Claude Code as work progresses.

---

## How this file works (read first, Claude Code)

- Each task is a checkbox. Tick `- [ ]` → `- [x]` the moment a task is fully done **and** verified.
- Don't delete completed items — they stay checked in place so the log of what shipped is visible. If a section gets long, completed items can be moved to the `## Shipped` section at the bottom (with the date).
- Tasks include a `Where:` line (file paths to touch), a `Why:` line (intent / desk-relevance, so you don't lose the thread), and an `Acceptance:` line (what "done" looks like — verifiable, not vibes).
- If you discover a new task while working, add it under `## Backlog / ideas` rather than silently widening scope on the current task. Surface it; don't bury it.
- If a task turns out to be wrong or unnecessary after investigation, **don't tick it** — strike it out with `~~...~~` and add a one-line `Note:` explaining why. Keeps the audit trail honest.
- Dates use `YYYY-MM-DD`. Today is whatever `date` says, not what's written in older comments.
- Repo conventions worth respecting:
  - `data/` is Streamlit-free pure pandas. Don't add `import streamlit` there.
  - `analysis/` is pure pandas/numpy.
  - `ai/` is the only module that touches the Anthropic SDK.
  - Streamlit-aware code lives in `ui/` and `app.py` only.
  - Every AI call must be logged to `ai/logs/<date>.jsonl` via `ai/client.py`. No raw `anthropic.Anthropic()` calls elsewhere.

---

## P0 — Must fix before submission

- [x] **Fix stale coal data + broken stooq fallback** _(2026-05-05)_
- [x] **Replace pct-change with absolute change for the two derived spreads** _(2026-05-05)_
- [x] **Add data-freshness flag to the desk note** _(2026-05-05)_
- [x] **Sanity-check the +99% DE Power weekly delta** _(2026-05-05)_
- [x] **Commit working tree + tidy commit history** _(2026-05-05)_

- [ ] **Push to GitHub + set Actions secrets** ← _your action; can't be automated from here_
  - Where: repo root, GitHub web UI.
  - Acceptance: After push: GitHub repo → Settings → Secrets and variables → Actions → add `ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY`. Trigger one `workflow_dispatch` run of `daily.yml` to confirm green. Branch is now **`main`** (renamed from master 2026-05-06).

---

## P1 — Metric set alignment with Cobblestone's actual book

Research confirmed Cobblestone Energy trades **European Power, Gas, and Emissions** — day-ahead through the forward curve, with a short-term / intraday emphasis. They do **not** trade coal as a primary book.

**Decision-utility filter (apply to every metric proposal in this section).** Before adding any tile, answer: *"Does a trader make a different call with this number on screen vs not?"* If no, don't add it.

> ⚠ **2026-05-06 reconciliation note**: subsequent chat-driven additions (GB Power as a primary tile, Renewables as a primary tile, news/geopolitics tab, European Markets clickable map, Wiki tab) deviate from the strict 6-card target this section originally laid out. The deviations are documented in each task and on balance increase reviewer-visible substance, but Sumer can choose to roll them back to the leaner spec — see Open Questions.

- [x] **Demote coal from primary tile to fundamentals input** _(2026-05-06)_
  - `Metric.is_fundamentals_input` flag added to `config.py`. Coal moved out of `TOP_ROW_METRICS`. New "Fundamentals inputs" strip in `app.py::_fundamentals_strip` shows coal + EUR/USD with smaller/muted styling. Clean Dark spread continues to compute correctly. Desk note has a separate fundamentals sub-table flagged `(input only)`.

- [ ] **Add a power forward curve indication (DA / Cal+1)**
  - **Status: still deferred.** Probed Yahoo for `EBASE.F`, `PHEX.F`, `PXE.PR`, `F2BAY.NEX`, `DE_BASE.F` on 2026-05-06 — all empty/delisted. EEX publishes daily Cal-Year settlement on its public market-data page but the URL changes per maturity and requires JS-rendered scraping; not stable enough to ship. Architectural slot prepared (`fetch_de_cal1` would slot into the same pattern; derived module ready). Listed in README → "What I'd do with another week".
  - Decision-utility test still: ✓ Backwardation vs contango directly changes positioning. When a stable free source exists, this is the highest-priority next addition.

- [x] **Add a single short-term tightness metric: renewables share of forecast load** _(2026-05-06)_
  - Implemented as `data/fetchers.py::fetch_renewable_share` (ENTSO-E `query_wind_and_solar_forecast` ÷ `query_load_forecast`, daily mean of hourly share). Exposed as the `renewable_share` metric.
  - **Deviation from spec**: the original task said "one chip near DE Power, not its own top-row card." Currently surfaced as a primary card (8 of 8 in the top grid) AND in the regime strip's "Renewables" cell. Two surfaces is more screen real estate than the strict spec wanted. Reasoning for keeping it: 1-yr percentile + sparkline + tooltip on the card adds material context the chip alone wouldn't carry; the regime strip handles the at-a-glance read.
  - Verified live 2026-05-06: 730 rows, latest 25.62 % of load (15th-pctile = renewable-poor; AI's TL;DR called this out as "renewables collapsing").

- [x] **Reframe the desk note's section structure** _(2026-05-06)_
  - Sections now: 1. Executive summary, 2. Monitor metrics (split: primary + fundamentals inputs), 3. Gas + LNG arb, 4. Carbon (EU ETS), 5. Power — Day-Ahead & curve, 6. Short-term drivers (renewables), 7. Today's themes (news + geopolitics), 8. Methodology & sources.

- [x] **(New, 2026-05-06) GB Power day-ahead via Elexon BMRS**
  - Where: `data/fetchers.py::fetch_gb_power`, `config.py::METRICS`, `data/cache.py::get_gb_power`.
  - **Deviation from the rejection in Backlog**: Originally rejected on the decision-utility filter ("DE is the continental front-curve benchmark"). Reinstated after Sumer asked for per-country views in the chat (2026-05-06). Implementation adds value via the European Markets tab even if you don't keep it as a primary card.
  - **Note**: ENTSO-E `GB` zone returns `NoMatchingDataError` — UK left ENTSO-E membership post-Brexit. Switched to Elexon BMRS Insights MID endpoint (no auth, weekly chunks, GBP→EUR via Yahoo `GBPEUR=X`). Cold-start capped at 1 year (52 weekly calls). Verified live: 366 rows, latest 128.31 EUR/MWh.

- [x] **(New, 2026-05-06) Cross-border DE−GB power spread**
  - Computed in `analysis/derived.py::power_spread`, surfaced as the "DE − GB" cell in the regime strip with DE-prem / GB-prem / parity colour coding. Section 5 of the desk note quotes the gap.

---

## P1 — Dashboard UI/UX upgrades

- [x] **Time-frame labels on every card and sparkline** _(2026-05-05)_
- [x] **Native `help=` tooltip on every metric card** _(2026-05-05)_
- ~~Click-to-expand metric detail via `st.popover`~~ _(2026-05-05 — superseded by Methodology tab + tooltip)_
- [x] **Multi-horizon delta strip per card** _(2026-05-05)_
- [x] **Direction-aware delta colours** _(2026-05-05)_
- [x] **Inject a custom CSS layer** _(2026-05-05)_
- ~~Adopt `streamlit-shadcn-ui` for cards + tabs~~ _(2026-05-05 — not adopted; CSS + regime strip + AI redesign already deliver the look)_
- [x] **Improve the AI Desk Note pane** _(2026-05-05)_
- ~~Replace per-metric tab body with `streamlit-elements` Nivo (stretch)~~ _(2026-05-05 — deferred; no measurable substance gain)_
- [x] **Top-of-page "regime strip"** _(2026-05-05)_
- [x] **Header refinement: status pill, last-update** _(2026-05-05)_
- [x] **Replace emoji icons** _(2026-05-05)_
- [x] **(New, 2026-05-06) Top-level navigation: 6 named tabs**
  - Overview / News & Geopolitics / European Markets / Per-Metric Detail / Methodology / How to use (Wiki). The previous flat 8-metric tab strip is now nested as sub-tabs inside "Per-Metric Detail" so the top of the screen surfaces what the trader actually navigates to first thing in the morning.

---

## P1 — Strong substance upgrades

- [x] **8th metric: explicit fuel-switching TTF price** _(2026-05-05)_
- [x] **Two-pass AI workflow: extract → narrate** _(2026-05-05)_

- [ ] **Cal+1 power proxy (true "Day-Ahead → curve")**
  - Note: still deferred. See P1 metric-alignment section above for the probe results.

- [x] **ENTSO-E renewable-share fundamentals** _(2026-05-06)_
  - Shipped — see P1 metric-alignment task above.

- [x] **News + theme extraction** _(2026-05-06)_
  - Shipped. `data/news.py` pulls from 9 RSS feeds (IEA, EIA Today/Petroleum/NatGas, Reuters Sustainability, Bruegel × 2, Euractiv, ENTSO-E). `ai/prompts/news_themes_v1.md` drives a strict-JSON Claude pass producing per-theme `{tag, commodity, polarity, why_it_matters, horizon}` plus a `geopolitics_summary` and a `watchlist`. Output committed to `output/<date>/data/ai_news_themes.json`. The narrative pass receives the news block alongside the metric snapshot — verified 2026-05-06: today's TL;DR explicitly cites Hormuz tail-risk because the news pass surfaced it.
  - **Dashboard surface**: dedicated "News & Geopolitics" tab (`ui/news_panel.py`) auto-loads on tab open, cached 1h. Each theme is rendered as a card with chips + why-it-matters; raw headlines available in an expander; audit footer with model/log path.

- [x] **(New, 2026-05-06) European Markets tab with clickable choropleth**
  - Where: `ui/markets.py`, mounted as a top-level tab in `app.py`.
  - 7 EU+GB countries (DE, GB, FR, NL, BE, IT_NORD, ES) rendered on a Plotly choropleth coloured by latest DA price. `st.plotly_chart(on_select="rerun")` captures click events; the clicked country's panel renders below the map with its DA chart, key stats, and a desk-relevant market note (nuclear-heavy FR; gas-heavy IT; isolated MIBEL ES; etc.). Sub-tabs as fallback navigation. Per-zone DA fetched on demand from ENTSO-E and cached 1h.

- [x] **(New, 2026-05-06) In-app Wiki tab**
  - Where: `ui/wiki.py`. Renders `WIKI.md` inline so the trader doesn't have to leave the dashboard to learn how to use it. The same content is a stand-alone file in the repo root.

---

## P2 — Robustness & reproducibility

- [x] **Pin requirements** _(2026-05-05; re-pinned 2026-05-06 with feedparser; 81 entries)_
- [x] **Fix `tests/test_fetchers.py::test_brent`** _(2026-05-05)_
- [x] **Add `tests/test_derived.py`** _(2026-05-05)_
- [x] **Add CI for tests** _(2026-05-05)_
- [x] **Soft-fail individual fetchers in the cron** _(2026-05-05)_
- ~~Use Anthropic prompt caching for the system prompt~~ _(2026-05-05 — Haiku 4.5's 4096-token min cacheable prefix > our prompt size; doc updated)_

---

## P3 — Communication & polish

- [x] **PDF export of the desk note** _(2026-05-06)_
  - `pandoc` installed via `brew install pandoc`. CLI flag `--pdf` calls `scripts/generate_brief.py::render_pdf` (pandoc + xelatex). Verified live: `output/2026-05-05/desk_note_2026-05-05.pdf` ships alongside the markdown. `justfile`'s `just pdf` target works.

- [x] **Mermaid architecture diagram in the README** _(2026-05-05)_
- [x] **One-line trade-relevant TL;DR at the top of the desk note** _(2026-05-05)_
- [x] **README "What I'd do with another week" section** _(2026-05-05)_

- [ ] **Scrub Cobblestone references for portfolio-public version** ← _post-submission action_
  - Acceptance unchanged. Decision recorded in Open Questions: keep references for the submission tag, scrub on `main` post-submission.

- [x] **Justfile or Makefile** _(2026-05-05)_
- [x] **`.env.example` for the CLI path** _(2026-05-05)_

- [ ] **Type-hint and `mypy --strict` the public API**
  - Note: deferred. The four target files are heavily type-hinted already; making them `--strict`-clean adds no reviewer-visible signal for several hours of work.

- [x] **Streamlit "Methodology" tab** _(2026-05-05)_
- [x] **(New, 2026-05-06) WIKI.md usage guide**
  - Standalone `WIKI.md` at repo root, rendered in-app via the "How to use" tab. Covers what the tool is, how to launch each surface, what the credentials are, how to read the desk note, how to read the dashboard, what to do when something fails, where to find each artefact.

- [ ] **Backtest the cross-market regime tag**
  - Note: deferred. Listed in "What I'd do with another week" alongside the rest of the validation work. Architectural slot prepared.

---

## Backlog / ideas (not yet prioritised)

Add freely. Move into P0–P3 when picking up; never silently widen scope on an in-flight task.

**Reminder for everything below: apply the decision-utility filter before promoting anything from this list to P1. "Does a trader make a different call with this on screen vs not?" If no, leave it here.**

- [ ] Replace ICE Newcastle with a working API2 proxy. Lower priority now that coal is demoted.
- [ ] **NBP front-month gas.** Considered for P1 and rejected — TTF is the European benchmark; NBP–TTF basis is interesting but is a *second-order* signal that doesn't move the gas + carbon → power thesis. Promote only if a TTF-NBP basis trade thesis is being told in the desk note.
- [ ] **UKA (UK ETS).** Rejected for P1 — adds carbon complexity with little decision impact unless GB Power is also a primary tile.
- [ ] **Cross-border power spread (GB-FR via IFA).** DE−GB shipped as a regime-strip cell; GB-FR could follow if the European Markets tab gains spread-vs-spread chips.
- [ ] **Imbalance / single-system price.** Rejected for P1 — pure intraday signal, separate trading workflow from the brief's "fundamentals → curve" framing.
- [ ] TTF–HH spread (TTF vs Henry Hub). Useful only if NBP is also in.
- [ ] **Cal+1 / Cal+2 multi-tenor curve panel.** Promote only after the single Cal+1 metric proves out.
- [ ] EUA option implied vol (if a free source exists).
- [ ] German wind speed forecast integration (ICON-EU open data) for D+1 / D+2 power.
- [ ] Dashboard "alert" pane that highlights any metric crossing a percentile threshold today.
- [ ] Email/slack the daily brief from the cron.
- [ ] Cost dashboard: track Anthropic spend per run from the JSONL logs.
- [ ] Nivo / `streamlit-elements` charts for the per-metric tabs.
- [ ] `streamlit-shadcn-ui` cards/tabs.

---

## Shipped

Move ticked items here after a session, with the date. Keeps the active sections lean.

- 2026-04-28 — Initial scaffold: 5 fetchers, cache layer, stats/signals, charts, brief sidebar, Streamlit `app.py`, headless `scripts/generate_brief.py`, AI client + narrative + versioned prompt + JSONL logging, `.github/workflows/daily.yml` cron, README structured around the brief criteria. Sample output committed at `output/2026-04-28/`.
- 2026-05-05 (morning) — Live end-to-end run with all three tokens. Fresh output at `output/2026-05-05/` including AI narrative from `claude-haiku-4-5`. AGSI+ fetcher fix shipped in `7eff9e6`.
- 2026-05-05 (evening) — Major Cobblestone-readiness pass. P0 fixes: coal-stale flagging, abs deltas for spreads, freshness banners + STALE badges, smoothed weekly comparison. P1: 8th metric (switching TTF), two-pass AI extract→narrate, regime strip, status pill, CSS polish, Methodology tab, multi-horizon delta strips, direction-aware colours, tooltip on every card. P2: full pinned `requirements.lock`, three new test files (21 tests passing), `.github/workflows/tests.yml`. P3: README mermaid diagram + "what I'd do with another week", `justfile`, `.env.example`, AI TL;DR field.
- 2026-05-06 — Cobblestone-aligned metric refit + geopolitics layer + clickable map + nav restructure. **Coal demoted** to fundamentals input. **GB Power added** via Elexon BMRS (UK left ENTSO-E post-Brexit; switched to free Elexon MID endpoint). **DE renewable-share** added (wind+solar forecast / load forecast). **DE−GB cross-border spread** in the regime strip. **News + geopolitics** ingestion (`data/news.py` + `ai/prompts/news_themes_v1.md` + `ai/news_themes.py`) — 9 RSS feeds, Claude theme extraction with structured output. **European Markets tab** with clickable Plotly choropleth (click country → drill into DA chart + market note); fallback sub-tabs for 7 zones. **In-app Wiki tab** rendering `WIKI.md`. **News & Geopolitics tab** auto-loaded with theme cards + watchlist + raw-headlines expander. **PDF export** via pandoc. **Top-level nav** restructured: 6 named tabs (Overview / News / Markets / Per-Metric Detail / Methodology / Wiki). Branch renamed master→main.

---

## Open questions for Sumer

(Claude Code: don't answer these on Sumer's behalf — flag them and wait.)

- [ ] **Submission timing**: ship as-is, or pursue Cal+1 power (the highest-leverage deferred item)? Cal+1 needs an EEX scrape; ~half a day of fragile work.
- [ ] **Lean-spec rollback**: this section's strict 6-card target was deviated from in 2026-05-06 chat work (GB Power as primary tile; Renewables as primary tile + regime cell). Roll back to the lean spec, or keep current 8-tile layout?
- [ ] **Coal**: ship as-is with stale-and-flagged Newcastle (now demoted to fundamentals), or invest in finding a working free API2 proxy / paid trial? Today's brief is honest about the limitation in three places (banner, table, methodology).
- [ ] **Cobblestone scrub**: tag the submission commit, then on `main` rewrite line-6 of README and `cc1de48`'s message to a neutral phrasing? Post-submission task.

---

## Cobblestone company profile (memory)

A separate Claude session was used to capture company-context notes about Cobblestone for use when shaping tool design. As of 2026-05-06 evening, **the actual content of that profile has not been propagated to this repo or to the project memory at `~/.claude/projects/-Users-sumersener/memory/`** — only the placeholder pointer exists in MEMORY.md. When the content lands, summarise it briefly here for future sessions.
