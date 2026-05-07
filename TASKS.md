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

### Final-pass compliance fixes (added 2026-05-07)

These came out of a brief-vs-deliverable compliance check. Each is a verifiable mismatch between what the Cobblestone brief literally asks for and what `output/2026-05-05/` currently delivers. Do all four before pushing to GitHub. Total time ~2 hours.

- [ ] **Cut desk note to 1–3 pages (currently 7 pages)** ← _critical; direct brief violation_
  - Where: `scripts/generate_brief.py` (markdown assembly + matplotlib `figsize` for chart pages), `output/<today>/desk_note_<today>.md` after regeneration, the PDF generation step.
  - Why: The brief is unambiguous — *"1–3 page document"*. `pypdf.PdfReader('output/2026-05-05/desk_note_2026-05-05.pdf').pages` returns **7**. A 7-page submission to a 1–3 page brief invites a "did they read the requirements?" reaction from the reviewer regardless of content quality. This is the single highest-priority pre-submission item.
  - Acceptance:
    - After regeneration, `pypdf.PdfReader(...).pages` (or `pdfinfo`) returns ≤ 3.
    - Cuts to make, in priority order:
      1. **Move section 8 (Methodology & sources) to the README** entirely. Replace section 8 in the desk note with a one-liner: *"Methodology and source list: see README §Methodology."* Methodology is reference material that doesn't need to ride with every daily brief.
      2. **Compress section 7 (news + geopolitics)** from a full table to a 1-line geopolitics summary plus a 2–4 bullet `Watchlist`. Drop the per-headline detail rows.
      3. **Strip duplicated metric lines** in sections 3/4/5/6. Currently every section repeats the metric in two ways back-to-back, e.g. *"TTF front-month prints at 48.14 EUR/MWh — Within typical range. \n TTF Gas prints at 48.14 EUR/MWh (65th-pctile of 5y)."* — same number twice, two lines apart. Keep one. Across four sections this saves ~½ page on its own.
      4. **Smaller chart sizes** — current PDF chart pages are oversized. Reduce matplotlib `figsize` to ~60% (e.g. `(7, 3.5)` instead of `(11, 6)`) and confirm legibility in the PDF.
      5. If still over 3 after the above, drop one chart. The most expendable is `04_de_gb_power.png` since DE-GB spread is already a single line in section 5.
    - Commit message suggestion: `Cut desk note to 1–3 pages (brief compliance)`.

- [ ] **Add carbon supply/policy commentary to section 4** ← _direct brief wording: "carbon supply/policy signal"_
  - Where: `scripts/generate_brief.py` (section 4 template), optionally a small versioned `data/policy_facts.py` with hand-maintained ETS supply/policy facts; verify `ai/prompts/extract_v1.md` reliably populates `carbon_policy_signal`.
  - Why: The brief literally asks for *"carbon supply/policy signal."* Section 4 today is one paragraph about EUA as a marginal-cost lever — that's price-impact commentary, not supply/policy. The narrate_v1 prompt already weaves `carbon_policy_signal` into the executive summary (section 1) when present, but section 4 itself is hardcoded boilerplate that doesn't consume the field. The reviewer's eye goes to the section labelled "Carbon"; that section needs to address what the brief asked for.
  - Acceptance:
    - Section 4 of the desk note contains, in addition to the existing price/percentile read: one short paragraph (2–3 sentences) on **supply** (EUA issuance volumes, MSR intake/cancellation thresholds, free-allocation phase-out trajectory) and/or **policy** (CBAM phase-in dates, ETS-2 expansion to road/buildings, EU–UK ETS linkage status). Pick whichever is most pressing per day.
    - Generation logic: prefer `ai_extract.carbon_policy_signal` from the existing two-pass extract (already in the prompt). If that field is null, fall back to a versioned hand-maintained fact-pack at `data/policy_facts.py` that returns the most relevant current ETS development. Hybrid is fine: AI fills if news triggers it, fact-pack provides the default.
    - If the source is the fact-pack, a small `pytest` warning fires if `policy_facts.py` was last touched > 30 days ago. Keeps the fallback honest over time.
    - When done, the desk note's section 4 contains both a price/percentile read (kept) AND a supply/policy paragraph (new). The brief's exact wording is now satisfied by the section that claims to address it.

- [ ] **Fix the stale-coal contradiction in section 5** ← _internal consistency / reviewer credibility_
  - Where: `scripts/generate_brief.py` (section 5 template).
  - Why: The top-of-document banner correctly flags coal as 130 days stale. Section 5 line 65 then asserts: *"Coal is firmly in-the-money vs gas — coal-fired plants set the marginal cost."* That claim is built on the very data the freshness banner just disclaimed. A careful reviewer will catch the contradiction.
  - Acceptance: Two acceptable fixes — pick one:
    1. **Caveat in place** — change the sentence to: *"Based on stale coal data (130 days old), the merit-order signal is indicative not current; the spark spread suggests gas remains competitive."* Explicitly acknowledges the staleness in section 5 itself, not just the banner.
    2. **Re-anchor on spark spread alone (preferred — supports the page-cut effort)** — drop the "Coal is firmly in-the-money" sentence entirely; let the section talk only about spark, DE/GB DA, and the curve regime. Mention coal only as a fundamentals input that is not currently usable.
    - Either way, no current-state assertion in section 5 that depends on stale coal data.

- [ ] **Regenerate today's output and pull Cal+1 into section 5** ← _stale brief content_
  - Where: command line first, then `scripts/generate_brief.py` (section 5 template).
  - Why: The latest output dir is `output/2026-05-05/`. Today is 2026-05-07. Cal+1 shipped today (commit `ffc997d`), but section 5 of the May 5 desk note still says verbatim *"EEX Cal+1 / Cal+2 settlement indications are listed in the roadmap"* — admitting in writing that the curve metric is missing, even though it now isn't. Submitting this version means handing the reviewer a brief that disclaims its own most recent feature.
  - Acceptance:
    - Run `python scripts/generate_brief.py` once with all three tokens set in env. `output/<today>/` is created with markdown + PDF + charts + per-metric CSVs + ai_snapshot.json.
    - Update section 5's template in `scripts/generate_brief.py`:
      - **Remove** the "Forward curve note: ... in the roadmap" paragraph.
      - **Replace with** a real curve regime line, e.g. *"DA / Cal+1 (model) at <DA> / <Cal1> EUR/MWh; spread <Δ> EUR/MWh — <backwardated|contango|flat>. Front absorbs storage/outages; Cal+1 reflects the structural carbon-and-fuel trajectory. Cal+1 is a backward-looking seasonality projection (see methodology)."* — pulled from the new `cal1_seasonality_projection` series.
    - The new section 5 says *something* about the curve with a number, not pointing at the roadmap.
    - PDF regenerated and on disk at `output/<today>/desk_note_<today>.pdf`. Page count check from the cut-to-3-pages task above is run on this regenerated PDF, not the May 5 one.

### Critical bugs from 2026-05-07 dashboard QA

These came out of running the live dashboard after the metric-set work landed. Each is a real, screenshot-captured issue. Fix all five before the GitHub push — bug 1 in particular cascades into the "AI couldn't generate the report" failure and almost certainly explains it.

- [ ] **`KeyError: 'switching_ttf'` blowing up the morning brief and (likely) the AI generation path**
  - Where: `analysis/signals.py::signal_for` line 64 — `metric = METRICS_BY_KEY[metric_key]` raises because `switching_ttf` is in the data dict but has no `Metric` entry.
  - Why: `data/cache.py::get_all_with_derived` (line 184) adds `out["switching_ttf"] = sw` as an auxiliary derived series. The code-comment at `analysis/signals.py:66` even acknowledges these auxiliaries exist (`switching_ttf`, `de_gb_spread`, `de_cal1_proj`, `eurusd`). But `analysis/signals.py::morning_brief` (line 125) iterates `data.items()` and calls `signal_for(k, df)` for every key — including the auxiliaries — and the lookup fails. The traceback is visible in the Methodology and Per-Metric Detail tabs in the screenshots Sumer sent on 2026-05-07.
  - Why this matters for AI generation: `morning_brief` is on the path to building the AI snapshot (`ai_snapshot.json` is built from rule-based signals + raw data). When `morning_brief` crashes the snapshot never gets built, the two-pass extract→narrate has nothing to consume, and the dashboard's "Generate desk note" button silently fails or shows the same traceback. Sumer reported "Claude couldn't generate the report" — this is almost certainly the cause, not a separate API issue.
  - Acceptance:
    - **Preferred fix**: in `analysis/signals.py::morning_brief` and any other callers, filter the data dict to keys that exist in `METRICS_BY_KEY` before iterating. e.g. `for k, df in data.items() if k in METRICS_BY_KEY`. Auxiliary series like `switching_ttf` are tracked elsewhere (regime strip, methodology) and don't need a Signal.
    - **Alternative**: make `signal_for` return `None` for unknown keys and have callers skip `None` results.
    - **Don't fix by registering switching_ttf as a Metric** unless you also add a primary card / tab for it — registration implies surface-level presence, and switching_ttf is currently only used as an auxiliary number on the regime strip.
    - After the fix: load every tab in the dashboard (Overview, News & Geopolitics, European Markets, Per-Metric Detail, Methodology, How to use). Zero tracebacks visible. Click "Generate desk note" → narrative renders, fresh entry appears in `ai/logs/<today>.jsonl`.

- [ ] **Material icon syntax leaking as literal text on the Methodology tab "Metrics tracked" list**
  - Where: `ui/methodology.py` (the `st.expander` calls in the Metrics-tracked block, lines ~33–37). Possibly extends to other expanders/headers in the codebase.
  - Why: Each row visually shows three overlapping strings — an icon-name like `_arrow_right`, the metric key like `TTF_Gas`, and the actual label "TTF Front-Month Natural Gas". The most likely cause is `:material/arrow_right:` (or similar) being passed as `icon=` to `st.expander` while the installed Streamlit version doesn't support that parameter. The icon falls back to literal text, and the rendering machinery then composites the icon-string and the label on top of each other.
  - Acceptance:
    - Each row in "Metrics tracked" renders as a clean expander labelled `<short_name> — <name>` (e.g. *"TTF Gas — TTF Front-Month Natural Gas"*). No `_arrow_right`, no `_TTF_Gas` underscore, no overlap.
    - Either (a) upgrade Streamlit to a version that supports the `icon=":material/...":` syntax (check `requirements.txt` and bump if so), OR (b) drop the `icon=` parameter wherever it's used and replace with a plain emoji prefix or no icon at all.
    - Take a screenshot of the Methodology tab post-fix and save under `docs/screenshots/methodology_after.png` for the record.

- [ ] **Sidebar shows literal text "ouble_arrow_right" where the collapse icon should be**
  - Where: `app.py` (likely an `st.set_page_config` or sidebar widget setting), or `.streamlit/config.toml`.
  - Why: Same root cause as the methodology bug — a Material icon name (probably `keyboard_double_arrow_right`) is being rendered as text. The string "ouble_arrow_right" visible top-left in every screenshot is the truncated tail of that icon name.
  - Acceptance: Sidebar header shows either a clean chevron/arrow glyph or no icon at all — never the literal Material icon name. Verify on every tab.

- [ ] **European Markets choropleth renders with too-wide projection and a large white panel**
  - Where: `ui/markets.py`. Note that lines 227–246 already set `scope="europe"`, `projection_type="mercator"`, `lataxis_range=[35, 62]`, `lonaxis_range=[-12, 26]` — so the bounds *are* configured but aren't being respected.
  - Why: The screenshot shows the map extending south into Africa and east into the Middle East, plus a large white bounding box. Likely culprits:
    1. The `update_geos` call doesn't reach this particular figure (check whether the call is on the right `fig` object — there are two `update_geos` calls in the file at lines 191 and 227).
    2. `fitbounds="locations"` is being applied somewhere and overriding `lataxis_range` / `lonaxis_range`.
    3. The `bgcolor` of the geo subplot isn't set to the dark theme background, leaving Plotly's default white panel visible.
  - Acceptance:
    - Map is visually centred and zoomed on Europe (~lat 35–70, lon −15 to 35). The Mediterranean is at the bottom of the view, not the middle.
    - No white panels. The geo subplot background matches the dashboard's dark theme (`bgcolor` set to the page's secondaryBackgroundColor).
    - Click-to-drill into a country still works after the fix.
    - Take a screenshot of the European Markets tab post-fix and save under `docs/screenshots/markets_after.png`.

- [ ] **Verify AI desk-note generation works end-to-end after bug 1 is fixed**
  - Where: command line + the dashboard.
  - Why: The user reported "Claude LLM couldn't generate the report when I needed it to." Most likely a downstream effect of bug 1's KeyError. Verify, don't assume.
  - Acceptance:
    - With all three tokens set in env (`ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY`), run `streamlit run app.py`, click "Generate desk note" on the Overview tab.
    - Confirm: a 3–5 sentence narrative renders in the pane (not an error / not "rule-based fallback" silently swallowed).
    - Confirm: a fresh entry appears in `ai/logs/<today>.jsonl` with `purpose: "extract"` and `purpose: "narrate"` records, both with non-zero `usage.input_tokens` and `usage.output_tokens`.
    - Also run `python scripts/generate_brief.py` end-to-end and confirm `output/<today>/desk_note_<today>.md` is produced with the AI narrative in the executive summary.
    - If the AI generation is *still* broken after bug 1 is fixed, dig into the two-pass workflow (`ai/narrative.py`) — most likely a malformed JSON response from the extract pass that the narrate pass can't consume. Add a defensive `json.JSONDecodeError` catch with a one-shot retry.

---

- [ ] **Push to GitHub + set Actions secrets** ← _your action; can't be automated from here_
  - Where: repo root, GitHub web UI.
  - Acceptance: After push: GitHub repo → Settings → Secrets and variables → Actions → add `ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY`. Trigger one `workflow_dispatch` run of `daily.yml` to confirm green. Branch is now **`main`** (renamed from master 2026-05-06). Add the live workflow-run link to the README so the reviewer can see the cron path is real, not theoretical.

---

## P1 — Metric set alignment with Cobblestone's actual book

Research confirmed Cobblestone Energy trades **European Power, Gas, and Emissions** — day-ahead through the forward curve, with a short-term / intraday emphasis. They do **not** trade coal as a primary book.

**Decision-utility filter (apply to every metric proposal in this section).** Before adding any tile, answer: *"Does a trader make a different call with this number on screen vs not?"* If no, don't add it.

> ⚠ **2026-05-06 reconciliation note**: subsequent chat-driven additions (GB Power as a primary tile, Renewables as a primary tile, news/geopolitics tab, European Markets clickable map, Wiki tab) deviate from the strict 6-card target this section originally laid out. The deviations are documented in each task and on balance increase reviewer-visible substance, but Sumer can choose to roll them back to the leaner spec — see Open Questions.

- [x] **Demote coal from primary tile to fundamentals input** _(2026-05-06)_
  - `Metric.is_fundamentals_input` flag added to `config.py`. Coal moved out of `TOP_ROW_METRICS`. New "Fundamentals inputs" strip in `app.py::_fundamentals_strip` shows coal + EUR/USD with smaller/muted styling. Clean Dark spread continues to compute correctly. Desk note has a separate fundamentals sub-table flagged `(input only)`.

- [x] **Add a power forward curve indication (DA / Cal+1)** _(2026-05-07 — shipped as seasonality projection, not market quote)_
  - **What ships**: a model-derived **Cal+1 seasonality projection** in `analysis/derived.py::cal1_seasonality_projection`. For each historical date, finds realised DA exactly 1 year later (±3-day window) and reports the rolling 30-day mean. The DA − Cal+1 spread reads as a backwardation/contango regime signal.
  - **Surface**: a dedicated **Power curve panel** (`ui/curve.py`) on the Overview tab, expanded by default — KPI box (DA / Cal+1 proj / spread + regime label), regime explanation, 2Y line chart with dashed projection. Plus a "DA − Cal+1 (model)" cell in the regime strip. Plus a Methodology-tab section explaining the model's caveats.
  - **Honest about what it is**: every surface labels this as "model — not a market quote" and explains the limitation (backward-looking, mean-reverting, doesn't price current expectations). Replace with EEX Cal-Year settlement when paid feed is available.
  - **Probes**: 2026-05-06 + 2026-05-07. Yahoo (`EBASE.F`, `PHEX.F`, `PXE.PR`, `F2BAY.NEX`, `DE_BASE.F`, `F2BAY26.NEX`, `EBASE26.F`, `EEX.DE`, etc.) — all empty. EEX gvsi webservice — connection refused. Energy-Charts API — spot only, no futures. TradingEconomics — paywalled. Decision: synthetic projection beats no curve indication, with full transparency.
  - Pinned by `tests/test_derived.py::test_cal1_seasonality_projection_basic` and `test_cal1_seasonality_projection_too_short`.

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

- [x] **Cal+1 power proxy (true "Day-Ahead → curve")** _(2026-05-07)_
  - Shipped as a seasonality-based projection — see P1 metric-alignment section above for full details and the probe trail of all the free sources that didn't pan out.

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
