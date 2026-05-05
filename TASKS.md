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

These are the items that would embarrass the brief if a careful reviewer ran the script today.

- [x] **Fix stale coal data + broken stooq fallback** _(2026-05-05)_
  - Where: `data/fetchers.py::fetch_coal`, `data/fetchers.py::_stooq`.
  - What shipped: `_stooq` now handles empty bodies, "No data" responses, and zero-row lookback windows with explicit `RuntimeError` (no more `IndexError`). `fetch_coal` now probes a chain of candidate tickers (`MTF=F` → `LMC.L` → `KOL=F` → stooq `coal.f`), prefers the freshest, and — when none are within 7 days — sets `df.attrs["is_stale"] = True` so the cache + UI surface a STALE badge instead of silently using December prices. Added `tests/test_fetchers.py::test_coal_freshness_invariant`, `test_stooq_handles_empty_response`, `test_stooq_handles_no_data_text`.

- [x] **Replace pct-change with absolute change for the two derived spreads** _(2026-05-05)_
  - Where: `Metric.delta_unit` field (config.py), new `daily_change_abs` / `change_over_abs` helpers in `analysis/stats.py`, snapshot builders in `ai/narrative.py` and `scripts/generate_brief.py`, table row in the desk-note template.
  - What shipped: `clean_spark` and `clean_dark` carry `delta_unit="abs"`; everywhere a delta is rendered, the metric registry decides whether to format as `+x.xx%` or `+x.xx EUR/MWh`. Footer note in section 2 explains the convention. Pinned by `tests/test_stats.py::test_daily_change_abs`.

- [x] **Add data-freshness flag to the desk note** _(2026-05-05)_
  - Where: `analysis/stats.py` (`days_since_latest`, `is_stale`), `ai/narrative.py` (snapshot field), `scripts/generate_brief.py` (table column + executive-summary preamble + STALE badge), `ui/cards.py` (per-card freshness caption), `app.py` (header status pill).
  - What shipped: each row of the metrics table shows `as_of` plus a `⚠ STALE` badge when older than 5 business days. The brief opens with a one-line freshness caveat naming every stale metric. The structured `freshness` field is present in `ai_snapshot.json` so Claude reflects it in the narrative. Verified live: today's brief flags Coal (130d), Clean Dark (125d), Switch TTF (120d) as stale, and the AI's TL;DR explicitly mentions "coal data is 130 days stale".

- [x] **Sanity-check the +99% DE Power weekly delta** _(2026-05-05)_
  - Where: `analysis/stats.py::change_over_pct` and `change_over_abs` got an optional `smooth_window` parameter; `scripts/generate_brief.py` and `ai/narrative.py` use `smooth_window=5`.
  - **Note:** The +99% reading was a real holiday-comparison artefact — May 1 prints negatively in DE, so latest/(latest-5) blew up. The fix compares the trailing 5-day mean *today* to the trailing 5-day mean *5 business days ago*, dampening single-day spikes without dropping any data. After the fix today's DE Power 1w reads +31.31% — high but defensible. Pinned by `tests/test_stats.py::test_change_over_pct_smoothed_dampens_holiday_spike`.

- [x] **Commit working tree + tidy commit history** _(2026-05-05)_
  - Where: repo root.
  - What shipped: working tree clean after the 2026-05-05 refactor commit. `cc1de48`'s message (Cobblestone-tagged) left as-is — see Open Questions below for the portfolio-public scrub decision; deliberate to leave that as a one-shot edit you do post-submission.

- [ ] **Push to GitHub + set Actions secrets** ← _your action; can't be automated from here_
  - Where: repo root, GitHub web UI.
  - Acceptance unchanged from before. After push: GitHub repo → Settings → Secrets and variables → Actions → add `ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY`. Then trigger one `workflow_dispatch` run of `daily.yml` to confirm green.

---

## P1 — Metric set alignment with Cobblestone's actual book (added 2026-05-05)

Research confirmed Cobblestone Energy trades **European Power, Gas, and Emissions** — day-ahead through the forward curve, with a short-term / intraday emphasis. They do **not** trade coal as a primary book.

**Decision-utility filter (apply to every metric proposal in this section).** Before adding any tile, answer: *"Does a trader make a different call with this number on screen vs not?"* If no, don't add it. The dashboard's value comes from clarity, not breadth — Sumer has been explicit that an overcrowded screen is worse than a focused one.

Net result: this section is a **structural restructure plus exactly two new metrics**, not a metric land-grab. Anything more lives in Backlog with a "verify decision-utility first" tag.

The post-restructure target shape is:
- **6 primary cards (top row):** TTF Gas · EU Storage · EUA Carbon · DE Power DA · Clean Spark · Clean Dark
- **One curve card or strip:** DA / Cal+1 spread + regime tag (the brief's "Day-Ahead to curve" output)
- **One short-term tightness metric:** wind+solar share of forecast load — single number, lives next to DE Power
- **One fundamentals strip (small, lower on page):** Coal · EUR/USD · (anything else needed by derived metrics)

That's it. No GB Power tile, no NBP tile, no UKA tile, no load tile, no cross-border spread tile — those were proposed in the first draft and explicitly trimmed because none of them changes a trader's call vs the simpler alternatives.

- [ ] **Demote coal from primary tile to fundamentals input**
  - Where: `config.py::METRICS` (drop `coal` from the primary list), `app.py::main` (remove the top-row card), new `ui/fundamentals.py` (or a collapsed strip below the primary cards), README + desk note.
  - Why: Cobblestone doesn't trade coal. Today coal occupies 1/7th of the most expensive screen real estate. It still matters for the clean dark spread, but it should look like an *input*, not a *headline*. This is a removal — it *reduces* clutter, not adds.
  - Acceptance: Top row shows 6 cards (TTF, EU Storage, EUA, DE Power, Clean Spark, Clean Dark). Coal appears in a small "Fundamentals inputs" strip lower on the page (alongside EUR/USD), not as a top-row card. Clean Dark spread continues to compute correctly. Desk note's metrics table flags coal with `(input only)`.

- [ ] **Add a power forward curve indication (DA / Cal+1) — single new metric, not a series of them**
  - Where: new `data/fetchers.py::fetch_de_cal1`, register a single `de_cal1` metric (or a derived `da_cal1_spread`) in `config.py`. One card, not a curve panel.
  - Why: The brief literally says **"Day-Ahead to curve Implications."** Cobblestone trades along the forward curve. Currently you have only day-ahead. This is the single biggest gap between your dashboard and the brief — and it earns its tile because backwardation vs contango directly changes how a trader positions.
  - Decision-utility test: ✓ Backwardated curve = front strength / curve length opportunity; contango = forward-buying pressure. Different positioning either way.
  - Source: EEX publishes free daily Cal-Year settlement indications. Scrape the daily CSV at `https://www.eex.com/en/market-data/power/futures` or use `investpy`. Cal-quarter is nice-to-have but **not** part of this task — keep it to one curve point until proven necessary.
  - Acceptance: One new card showing DA · Cal+1 · Spread with a backwardation/contango chip. No multi-tenor curve panel. Section 5 of the desk note discusses curve shape with numbers, not adjectives.

- [ ] **Add a single short-term tightness metric: renewables share of forecast load**
  - Where: new `data/fetchers.py::fetch_de_tightness` that combines load + renewable forecast and returns one number, registered as `renewable_share` (or `thermal_call_pct`). One metric, not two cards.
  - Why: Wind/solar share of next-day load is the dominant short-term DE Power driver after fuel costs, which is Cobblestone's bread and butter. Combining renewables and load into a single "tightness" number keeps the dashboard sparse — the trader doesn't need to mentally divide two cards to get the answer.
  - Decision-utility test: ✓ Low renewable share = thermal-heavy day = power tracks gas + carbon tightly; high share = power decouples from fuel. Different trade thesis either way.
  - Source: ENTSO-E `query_wind_and_solar_forecast(country='DE_LU')` and `query_load_forecast(country='DE_LU')` via the existing `entsoe-py` client.
  - Acceptance: One small chip or strip near DE Power showing tomorrow's renewable share + 1-yr percentile rank. Surfaces in the desk note's short-term commentary when it's an outlier (top/bottom decile). Does **not** become its own top-row card.

- [ ] **Reframe the desk note's section structure to match the leaner metric set**
  - Where: `scripts/generate_brief.py` (markdown assembly), `ai/prompts/*.md` (prompt updates).
  - Why: Once coal is demoted and DA/Cal+1 + renewable tightness ship, the desk note's sections should reflect the trade-shaped emphasis. Don't expand sections — retitle and re-anchor existing ones.
  - Acceptance: Desk note sections: 1. Executive summary, 2. Monitor metrics (tabular), 3. Gas tightness, 4. Carbon, 5. Power — DA & curve (now backed by Cal+1 numbers), 6. Methodology & sources. Renewables tightness is referenced *inside* section 5 (one sentence when it's an outlier), not given its own section. Coal mentioned only as a fundamentals caveat.

---

## P1 — Dashboard UI/UX upgrades (escalated by Sumer 2026-05-05)

Sumer flagged that the dashboard is unclear about time-frames and lacks hover affordances; he also wants a more "futuristic and appealing" look. Below are bite-sized, prioritised tasks that lift the dashboard substantially without leaving Streamlit.

**Don't switch frameworks.** The brief does not grade visual polish above clarity, and a Dash/Reflex/Next.js rewrite eats the time budget. Push Streamlit to its 80%-of-modern ceiling instead.

- [x] **Time-frame labels on every card and sparkline** _(2026-05-05)_
  - Daily delta on each card now ends in `(1d)`. Sparkline carries an explicit `Last 30d` caption beneath it.

- [x] **Native `help=` tooltip on every metric card** _(2026-05-05)_
  - `st.metric(..., help=...)` populated from `Metric.definition + source` for every card. Hover the `?` icon in the dashboard.

- ~~Click-to-expand metric detail via `st.popover`~~ _(2026-05-05)_
  - Note: superseded by the Methodology tab + the always-on tooltip + the per-metric tabs already in place. A popover would duplicate content already reachable in one click.

- [x] **Multi-horizon delta strip per card** _(2026-05-05)_
  - Each card now shows a row of three chips: `1d / 1w / 1m`. Spreads format as absolute EUR/MWh; price-like metrics format as %. Smoothed 5-day-mean comparison for the 1w chip.

- [x] **Direction-aware delta colours** _(2026-05-05)_
  - `Metric.higher_is` now drives `st.metric(delta_color=...)`. `bullish-power` → inverse (up=red); `supply-rich` → normal (up=green for storage); new `margin-rich` semantic for spreads + switching TTF (up=green). Footer carries the legend.

- [x] **Inject a custom CSS layer** _(2026-05-05)_
  - Where: `ui/style.css`, loaded once in `app.py::_load_css`.
  - Card hover lift, gradient panels on cards/regime strip, subtle glow on percentile chips, IBM Plex / Inter typography fallback chain, tabular numerals on metric values, brighter active-tab underline. Renders cleanly in dark mode.

- ~~Adopt `streamlit-shadcn-ui` for cards + tabs~~ _(2026-05-05)_
  - Note: not adopted. Adds a non-trivial dependency for a stylistic gain that the custom CSS + the regime strip + the AI pane redesign already deliver. Reviewer impact too marginal to justify the dep.

- [x] **Improve the AI Desk Note pane** _(2026-05-05)_
  - Hero `top_takeaway` block (italic, blue left-rule) rendered first; themes as blue chips; risk flags as pink chips; narrative paragraph as the body; audit footer with model + extract-log path + narrate-log path. Two-pass / single-pass toggle is exposed in the pane.

- ~~Replace the per-metric tab body with an `streamlit-elements` Nivo chart (stretch)~~ _(2026-05-05)_
  - Note: deliberately deferred. Plotly already does the job; Nivo is a stretch with installation friction (web bundles inside Streamlit) and no measurable substance gain. Logged in Backlog as candidate for a v0.2-style polish pass.

- [x] **Top-of-page "regime strip"** _(2026-05-05)_
  - Where: `ui/regime.py`, rendered between header and cards in `app.py::main`.
  - 5 KPIs: Switching TTF, TTF − Switching TTF gap, Spark − Dark differential, Storage vs seasonal (pp), Cross-market regime tag. Coloured signed values (green = bearish-power / margin-rich, red = bullish-power / cost-push). Looks like a desk cockpit, not a chart wall.

- [x] **Header refinement: status pill, last-update, environment** _(2026-05-05)_
  - Right of the header: a status pill that reads `8/8 live` (green), `n stale` (amber), or `n missing` (red), with a `title` tooltip listing per-metric freshness on hover. Dropped the emoji from the title and refresh button.

- [x] **Replace the emoji icons with proper iconography** _(2026-05-05)_
  - All emoji removed from titles, headers, and the AI pane. Plain text labels throughout. Kept the `⚠` and `✅` glyphs only in operational STALE badges and CLI stdout where they read as utility, not decoration.

---

## P1 — Strong substance upgrades

Each of these meaningfully strengthens at least one of the five Cobblestone evaluation criteria.

- [x] **8th metric: explicit fuel-switching TTF price** _(2026-05-05)_
  - Where: `analysis/derived.py::switching_ttf`, registry update in `config.py`, snapshot writer in `scripts/generate_brief.py`, table row in the desk-note template, `ui/regime.py` displays the TTF − Switching TTF gap as a headline KPI.
  - Pinned by `tests/test_derived.py::test_switching_ttf_simple` and a consistency test that verifies CSS == CDS at `gas_price = switching_ttf`.

- [x] **Two-pass AI workflow: extract → narrate** _(2026-05-05)_
  - Where: `ai/narrative.py` (`_generate_two_pass`), `ai/prompts/extract_v1.md` (strict-JSON output), `ai/prompts/narrate_v1.md` (prose grounded only in pass-1 JSON). `desk_note_v1.md` retained for `--single-pass` flag.
  - Pass 1's JSON is committed to `output/<date>/data/ai_themes.json`. Both calls are logged to `ai/logs/<date>.jsonl` with `purpose: "extract"` / `purpose: "narrate"`. Verified live on 2026-05-05 — extract returned valid JSON first try; narrative reflects the extraction (TL;DR: "coal data is 130 days stale").

- [ ] **Cal+1 power proxy (true "Day-Ahead → curve")**
  - Note: deferred to "What I'd do with another week" in the README. EEX free Cal+1 indications are scrape-fragile; not worth shipping at the wire. Architectural slot prepared (`fetch_de_cal1` would slot into the same fetcher pattern; derived module can compute the spread).

- [ ] **ENTSO-E renewable-share fundamentals**
  - Note: deferred. Architectural slot prepared (ENTSO-E client already used for power); the `entsoe-py` client supports `query_wind_and_solar_forecast`. One afternoon of work in v0.2.

- [ ] **News + theme extraction (start small)**
  - Note: deferred. Architectural slot prepared (`ai/` already has the two-pass pattern; a third prompt for news themes drops in cleanly). Listed in v0.2 of the roadmap.

---

## P2 — Robustness & reproducibility

- [x] **Pin requirements** _(2026-05-05)_
  - `requirements.txt` keeps `>=` ranges (so a fresh install gets a sane modern set); `requirements.lock` committed with `pip freeze` output (75 entries, including transitive deps). README + `justfile` document the regen pattern.

- [x] **Fix `tests/test_fetchers.py::test_brent`** _(2026-05-05)_
  - Removed (Brent isn't part of the metric set). `tests/test_fetchers.py` now covers the seven actually-used fetchers plus the freshness invariant and stooq robustness regressions.

- [x] **Add `tests/test_derived.py`** _(2026-05-05)_
  - Five tests: clean spark golden input, clean dark golden input, switching TTF golden input, the consistency invariant (at switching TTF gas price, CSS == CDS), and an empty-input safety test.

- [x] **Add CI for tests** _(2026-05-05)_
  - `.github/workflows/tests.yml` — runs `pytest -q` on push and PR. Fetcher tests skip cleanly when secrets aren't set (e.g. fork PRs); pure-logic tests (stats, derived) run unconditionally.

- [x] **Soft-fail individual fetchers in the cron** _(2026-05-05)_
  - `scripts/generate_brief.py::_safe_fetch` already returns an empty DataFrame on individual fetcher failure; the brief renders with whatever data is available, lists missing series, and exits zero unless the file system itself fails. Verified across `de_power`/`storage` token-missing scenarios on 2026-04-28 sample run.

- ~~Use Anthropic prompt caching for the system prompt~~ _(2026-05-05)_
  - Note: verified against the SDK. The minimum cacheable prefix on Haiku 4.5 is 4096 tokens. The extract and narrate system prompts are ~300–500 tokens each — adding `cache_control` would silently no-op and pay no cache surcharge, but also produce no read benefit. The comment in `ai/client.py` is updated with this rationale and an explicit "flip on if prompts grow past 4 K" note.

---

## P3 — Communication & polish

- [ ] **PDF export of the desk note**
  - `justfile` ships a `pdf` target using pandoc + xelatex (TeX is installed locally; pandoc is not). One `brew install pandoc` away from working. Markdown is acceptable per the brief, so this is convenience, not requirement.

- [x] **Mermaid architecture diagram in the README** _(2026-05-05)_
  - Top of `README.md` — flowchart shows public sources → fetchers → cache → analysis (stats / derived / signals) → AI (extract → narrate, with logging) → outputs (markdown, CSV, PNG, JSON, dashboard). Renders natively on GitHub.

- [x] **One-line trade-relevant TL;DR at the top of the desk note** _(2026-05-05)_
  - The two-pass extract returns a `top_takeaway` field; `scripts/generate_brief.py` renders it as a bold one-liner before the executive summary. Today's reads: "Clean spark at 91st-percentile (35.41 EUR/MWh) dominates merit order; coal at 9th-percentile (96 USD/t) is deeply in-the-money, but coal data is 130 days stale — gas anchors power via TTF at 65th-percentile."

- [x] **README "What I'd do with another week" section** _(2026-05-05)_
  - Six honest bullets immediately above the longer-horizon roadmap: paid coal feed, Cal+1, news/policy ingestion, forecasting model, backtesting harness, renewable-share fundamentals. Frames each as a known gap, not a future pipe-dream.

- [ ] **Scrub Cobblestone references for portfolio-public version** ← _post-submission action_
  - Acceptance unchanged. Decision recorded in Open Questions below: keep the Cobblestone references for the submission tag; scrub on `main` post-decision.

- [x] **Justfile or Makefile** _(2026-05-05)_
  - `justfile` at repo root with targets: `brief`, `brief-single-pass`, `dashboard`, `test`, `test-logic`, `pdf`, `clean`, `lock`, `typecheck`. `just --list` works.

- [x] **`.env.example` for the CLI path** _(2026-05-05)_
  - `.env.example` mirrors `.streamlit/secrets.toml.example`. All three credentials with registration links inline.

- [ ] **Type-hint and `mypy --strict` the public API**
  - Note: deferred. The four target files are heavily type-hinted already; making them `--strict`-clean adds no reviewer-visible signal for several hours of work. Logged.

- [x] **Streamlit "Methodology" tab** _(2026-05-05)_
  - Where: `ui/methodology.py`, rendered as the final tab in `app.py::main`.
  - Surfaces the cross-commodity thesis in plain English, the per-metric definitions (in expanders), the plant assumptions, the formulas (in a code block), the rule-based signal thresholds, and the AI workflow design. The dashboard now reads as a living desk note, not a chart wall.

- [ ] **Backtest the cross-market regime tag**
  - Note: deferred. Listed in "What I'd do with another week" alongside the rest of the validation work. Architectural slot prepared (the data layer already produces 5y series of every input).

---

## Backlog / ideas (not yet prioritised)

Add freely. Move into P0–P3 when picking up; never silently widen scope on an in-flight task.

**Reminder for everything below: apply the decision-utility filter before promoting anything from this list to P1. "Does a trader make a different call with this on screen vs not?" If no, leave it here.**

- [ ] Replace ICE Newcastle with a working API2 proxy — investigate Refinitiv-free, EEX coal indications, or `investpy`. Lower priority now that coal is demoted to a fundamentals input.
- [ ] **GB Power day-ahead.** Considered for P1 and rejected — DE is the continental front-curve benchmark, GB tells a different (UK-specific) story, and adding it doubles power tile count without changing how a trader plays the gas + carbon → DE Power thesis. Promote only if the reviewer-conversation reveals GB-specific interest.
- [ ] **NBP front-month gas.** Considered for P1 and rejected — TTF is the European benchmark Cobblestone trades; NBP–TTF basis is interesting but is a *second-order* signal that doesn't move the gas + carbon → power thesis. Promote only if a TTF-NBP basis trade thesis is being told in the desk note.
- [ ] **UKA (UK ETS).** Rejected for P1 — adds carbon complexity with little decision impact unless GB Power is also on screen.
- [ ] **Cross-border power spread (DE-FR, GB-FR).** Rejected for P1 — pure short-term/intraday signal that doesn't speak to the brief's day-ahead-to-curve framing.
- [ ] **Imbalance / single-system price.** Rejected for P1 — pure intraday signal, separate trading workflow from the brief's "fundamentals → curve" framing.
- [ ] TTF–HH spread (TTF vs Henry Hub) as a global LNG-arb sanity check. Useful only if NBP is also in — and NBP is rejected, so this stays parked.
- [ ] Belgian / Dutch / French power day-ahead — same ENTSO-E client. Adds continental coverage beyond DE without changing the trade thesis.
- [ ] EUA option implied vol (if a free source exists) — single best risk-regime indicator for emissions. Possibly the strongest candidate in this list to promote later.
- [ ] German wind speed forecast integration (ICON-EU open data) for D+1 / D+2 power.
- [ ] Dashboard "alert" pane that highlights any metric crossing a percentile threshold today.
- [ ] Email/slack the daily brief from the cron (Anthropic could draft a shorter mobile-friendly variant).
- [ ] Cost dashboard: track Anthropic spend per run from the JSONL logs; surface monthly burn.
- [ ] Switch from pandas to polars in `data/` and `analysis/` — measurable speedup on the 5y series.
- [ ] Consider Claude Sonnet for the narrative pass and Haiku for extraction — A/B over a week and report.
- [ ] Nivo / `streamlit-elements` charts for the per-metric tabs (deferred from P1 dashboard).
- [ ] `streamlit-shadcn-ui` cards/tabs (deferred from P1 dashboard).

---

## Shipped

Move ticked items here after a session, with the date. Keeps the active sections lean.

- 2026-04-28 — Initial scaffold: 5 fetchers, cache layer, stats/signals, charts, brief sidebar, Streamlit `app.py`, headless `scripts/generate_brief.py`, AI client + narrative + versioned prompt + JSONL logging, `.github/workflows/daily.yml` cron, README structured around the brief criteria. Sample output committed at `output/2026-04-28/`.
- 2026-05-05 (morning) — Live end-to-end run with all three tokens. Fresh output at `output/2026-05-05/` including AI narrative from `claude-haiku-4-5`. AGSI+ fetcher fix shipped in `7eff9e6`.
- 2026-05-05 (evening) — Major Cobblestone-readiness pass. P0 fixes: coal-stale flagging, abs deltas for spreads, freshness banners + STALE badges, smoothed weekly comparison. P1: 8th metric (switching TTF), two-pass AI extract→narrate, regime strip, status pill, CSS polish, Methodology tab, multi-horizon delta strips, direction-aware colours, tooltip on every card. P2: full pinned `requirements.lock`, three new test files (21 tests passing), `.github/workflows/tests.yml`. P3: README mermaid diagram + "what I'd do with another week", `justfile`, `.env.example`, AI TL;DR field. See commit log for the granular trail.

---

## Open questions for Sumer

(Claude Code: don't answer these on Sumer's behalf — flag them and wait.)

- [ ] **Submission timing**: ship today as-is, or invest the remaining time in one of the three deferred P1 substance items (Cal+1, renewable share, news ingestion)? Each is ~half a day of clean work; each meaningfully strengthens "Desk relevance" or "AI/LLM leverage".
- [ ] **Public portfolio version**: replace `master` with `main` while we're at it? (Cobblestone may also expect `main`.) Not urgent for submission; relevant for the post-submission portfolio cut.
- [ ] **Coal**: ship as-is with stale-and-flagged Newcastle, or invest a few hours in finding a working free API2 proxy (or registering for a paid trial) before submitting? Today's brief is honest about the limitation in three places (banner, table, methodology); the question is whether honesty is enough or whether you'd rather have live coal in the submission run.
