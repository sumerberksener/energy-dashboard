# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Keep this file current.** Whenever something important surfaces — a new requirement, a new convention, a key decision, a fact about Cobblestone, a workflow change — update this file as part of the same change. CLAUDE.md is loaded into every future conversation; if it's stale, future-you operates with stale context.

---

## Mission — what this project must deliver

This repository is **Sumer Sener's submission for the Cobblestone Energy case study**. Author: Sumer Sener · `sumerberksener@gmail.com`. Recruitment contact: `recruitment@cobblestoneenergy.com`. Deadline: one week from 2026-05-08 → **target submission by ~2026-05-15**.

### Case study brief (verbatim)

> **Case Study Theme — European Cross-Commodity Risk Pack: Gas + Carbon → Power Curve Implications**
>
> Build an automated monitor that converts public gas and carbon fundamentals into a clear, repeatable trading narrative for European power (Day-Ahead to curve).
>
> **Requirements:**
>
> 1. **Fundamentals View** — produce a concise desk note summarising current cross-commodity risk. *Deliverable:* 1–3 page document covering gas tightness, carbon supply/policy signal, and implications for European power curve risk, supported by numbers and at least two generated charts.
> 2. **Monitor Metrics** — define repeatable metrics that map directly to trading risk. *Deliverable:* a set of **5–8 daily monitor metrics** with clear relevance to gas, carbon, and power curve risk.
> 3. **Automation** — automate the data and reporting workflow. *Deliverable:* runnable Python script (or precise pseudo-code) that pulls public data, produces a cleaned dataset, generates charts, and outputs a short daily brief.
> 4. **AI / LLM Integration** — reduce manual analyst overhead using a programmatic AI component. *Deliverable:* code-integrated AI workflow with **logged prompts and outputs** that structures inputs and/or produces a metrics-grounded narrative.
>
> **Submission:** 1–3 page document (PDF or Markdown) including name + email; GitHub link or zipped folder containing automated data ingestion, chart generation, AI workflow code and prompts, dependencies, and output artifacts.
>
> **Evaluation criteria:** fundamental reasoning and market intuition · desk relevance and clarity of metrics · automation robustness and reproducibility · communication quality (decision-useful) · AI/LLM leverage as a measurable productivity gain.

**Every change must serve one of the five evaluation criteria.** When in doubt, ask: does this make the desk note more decision-useful, the metrics more desk-relevant, the automation more robust, or the AI leverage more visible? If not, it's scope creep.

---

## Critical context — Cobblestone Energy

Source: <https://cobblestoneenergy.com/> (Power, Gas, Emissions desk pages). Founded 2018 in London, expanded to Dubai. **Use their verbatim phrases when shaping outputs** — the brief should look like it was written *for* this desk, not *at* it.

### What they trade

| Desk | Markets / products | Geographic coverage |
|---|---|---|
| **Power** | Electricity across all major European markets, "from day ahead all the way along the forward curve" | Belgium, France, Germany, Great Britain, Hungary, Ireland, Italy, Netherlands, Spain, Switzerland |
| **Gas** | Physical gas via storage + pipelines, OTC and exchange-traded on all major European hubs | Austria, Belgium, France, Germany, Great Britain, Italy, Netherlands, Slovakia, Spain, Switzerland |
| **Emissions** | "European AND UK markets" — both EU ETS (EUA) and UK ETS (UKA); CBAM is explicitly named | EU + UK |
| **Automated Trading** | In-house tech that supports traders and generates value independently | — |

### Verbatim phrases worth weaving into outputs

- **Power** trades "from day ahead all the way along the forward curve" — three pillars: **Short-Term** (responding to "real time changes in plant availability, transmission capacity and weather forecasts"), **Curve Trading** ("forward positions across multiple maturities" driven by "structural fundamentals, forward expectations, and disciplined risk management"), and **Power Transportation** (physical transmission capacity).
- **Gas** trades "across major European hubs" with "forward positions across multiple delivery periods" informed by "seasonal demand, storage dynamics, and supply expectations". Pillars: Physical Gas Trading · Curve & Forward Trading · Operational Execution & Delivery.
- **Emissions** uses three analytical pillars: **Policy Analysis** ("Understanding how policy shapes market balance"), **Supply-Demand Fundamentals** ("allowance supply, emissions trends, and structural factors"), **Disciplined Execution** ("clear parameters guiding positioning and execution"). CBAM is the single instrument named verbatim.
- Cross-cutting: "Grounded in data, discipline, and execution" · "Disciplined risk management" · "Clear limits, controls, and governance structures" · "Positions, exposures, and performance are monitored in real time" · "Structural fundamentals".

### How this shapes the project

- The eight-metric set is curated to mirror Cobblestone's *actual* book: TTF (gas), EU storage (gas fundamentals), EUA (carbon), DE Power (continental front curve), GB Power (Cobblestone explicitly trades GB), Renewables share (residual-load driver), Clean Spark (gas-fired margin), Clean Dark (fuel-switching read). TTF−JKM is auxiliary because Cobblestone's gas book is European but LNG matters for tightness.
- The desk note's section headings (Gas tightness · Carbon supply/policy · Power curve risk) map onto Cobblestone's three desks. Section 5's "Curve shape" sentence speaks directly to "forward positions across multiple maturities".
- **UKA coverage is required**: the emissions desk trades EUA *and* UKA. Section 4 carries an EU/UK ETS basis sentence even when no live UKA print is available; structural facts live in `data/policy_facts.py`.
- **Risk-framing line at the foot of the desk note** paraphrases Cobblestone's four-pillar risk framework ("clear limits and continuous monitoring; observations framed as risk inputs, not directional calls") — recognisable without verbatim copy-paste.

---

## Working agreements (read every session)

### Commit + push regularly with clear messages

This is a **non-negotiable part of the workflow**, not an end-of-session ritual:

- **Commit often** — after each meaningful unit of change (a fix, a feature increment, a brief regeneration). Don't accumulate days of work in the working tree.
- **Clear, scoped commit messages.** Lead with a short imperative subject (e.g. `brief: collapse DA/Cal+1 into single multi-tenor curve sentence` · `Fix DE Power weekly-Δ explosion across negative-price holidays`); body explains the *why* and the desk-relevance hook. Mirror the existing commit style — `git log --oneline` for examples.
- **Push to `origin/main` regularly.** Remote: <https://github.com/sumerberksener/energy-dashboard> (public). The submission is the GitHub link, so the remote must always reflect the latest committed state.
- **Never push secrets.** Audit before any push: `git diff` for token-like patterns; verify `.streamlit/secrets.toml`, `.env`, and `TASKS.md` are not staged.
- **Do not skip hooks** (`--no-verify`) and do not amend already-pushed commits — create a new commit instead.

### Keep CLAUDE.md current

Update this file in the same change whenever:
- a new convention or invariant is introduced,
- a new command, environment variable, or credential is required,
- a key decision is made about the case study (a metric added/dropped, a section reframed, a Cobblestone-language alignment),
- the deadline, contact, or evaluation criteria change.

A stale CLAUDE.md is worse than no CLAUDE.md — future sessions will trust it.

### Stay in scope

The case-study brief is the contract. New features, refactors, or abstractions only land if they make a measurable contribution to one of the five evaluation criteria. Open questions and follow-ups go in `TASKS.md` (gitignored, local-only) — surface them rather than burying them in scope.

---

## Common commands

The repo uses [`just`](https://github.com/casey/just):

```bash
just brief              # Run the headless CLI → output/<today>/
just brief-single-pass  # Skip the extract step (faster AI path)
just dashboard          # streamlit run app.py
just test               # full pytest (network tests skip when offline)
just test-logic         # pure-logic tests only (no network) — tests/test_stats.py + tests/test_derived.py
just typecheck          # mypy --strict on data/ analysis/ ai/
just pdf                # render today's desk note to PDF (needs pandoc + xelatex)
just clean              # wipe data/store/*.parquet, output/, ai/logs/
just lock               # re-pin requirements.lock from active venv
```

Single test: `pytest -q tests/test_derived.py::test_clean_spark_basic`

Three free credentials are required for live runs (CLI reads from env, dashboard reads from `.streamlit/secrets.toml`): `ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY`. Without them the pipeline still produces output via deterministic fallbacks.

GitHub Actions cron in `.github/workflows/daily.yml` runs `scripts/generate_brief.py` at **07:30 UTC weekdays** and commits artifacts back with `[skip ci]`.

---

## Layer invariants (the most important rule in the repo)

The codebase splits into four layers with strict import rules. **Do not violate these** — they're what lets the same fetchers + analysis power both Streamlit and the headless CLI:

| Layer | Allowed imports | Forbidden |
|---|---|---|
| `data/` | pandas, numpy, requests, entsoe-py, yfinance | ❌ no `import streamlit` |
| `analysis/` | pandas, numpy | ❌ no streamlit, no I/O, no API calls |
| `ai/` | anthropic SDK, stdlib | only module that may instantiate `anthropic.Anthropic()` |
| `ui/`, `app.py` | everything (streamlit-aware) | this is the only Streamlit-aware code |

Caching layer (`data/cache.py`) is the one place that wraps fetchers with `@st.cache_data` + parquet snapshot fallback — it's the bridge between the pure data layer and Streamlit.

---

## AI workflow rules

- **Every AI call routes through `ai/client.py`.** It enforces append-only JSONL logging to `ai/logs/<date>.jsonl` (timestamp, model, prompt SHA-256, full text, token usage, latency). Do not call `anthropic.Anthropic()` directly anywhere else — the audit trail is the AI/LLM evaluation criterion in the brief.
- **Two-pass design**: `ai/narrative.py` runs **extract** (strict JSON, schema in `ai/prompts/extract_v1.md`) → **narrate** (prose grounded *only* in the extract JSON, `ai/prompts/narrate_v1.md`). The narrate prompt explicitly forbids referencing anything not in pass-1 output. A separate news-themes pass (`ai/news_themes.py` + `ai/prompts/news_themes_v1.md`) runs over RSS headlines.
- **Versioned prompts**: prompt files end in `_v1.md`. Bump the version in the filename (and update the loader) rather than mutating an existing prompt — the SHA changes invalidate logs otherwise.
- **Graceful fallback**: when `ANTHROPIC_API_KEY` is missing or a call fails, deterministic rule-based output is emitted from the same JSON snapshot. Never let an AI failure break the pipeline.
- **Model**: Claude Haiku 4.5 (`claude-haiku-4-5`). Cost per daily run is fractions of a cent. No prompt caching — the system prompts sit below Haiku's 4096-token cacheable prefix; see comment in `ai/client.py` for when to flip it on.

---

## Configuration single-source-of-truth

- **Metric registry** lives in `config.py::METRICS` (a list of frozen `Metric` dataclasses). Adding a metric is a one-place change — `PRIMARY_KEYS`, `DERIVED_KEYS`, `TOP_ROW_METRICS`, `FUNDAMENTALS_METRICS` are all derived from it.
- **Plant assumptions and signal thresholds** (η_gas=0.50, η_coal=0.40, EF_gas=0.184, EF_coal=0.34, coal calorific 6.978 MWh/t, percentile/sigma cutoffs, `STALE_AFTER_DAYS=5`) all live in `config.py`. Don't hardcode these elsewhere.
- **Author identity**: `AUTHOR_NAME`, `AUTHOR_EMAIL`, `SUBMISSION_TITLE` in `config.py` — used in the desk note header.
- **Forward curve horizons**: `analysis/derived.py::HORIZON_BDAYS` (W+1=5, M+1=21, Q+1=65, Cal+1=252, Cal+2=504). All five share `seasonality_projection()`; `cal1_seasonality_projection` is a thin back-compat wrapper.

---

## Output directory contract

`scripts/generate_brief.py` writes to `output/<YYYY-MM-DD>/`:
- `desk_note_<date>.{md,pdf}` — the deliverable; **PDF must stay ≤3 pages** (brief requirement).
- `data/snapshot.csv` — pivot of latest values across metrics
- `data/<metric>.csv` — full multi-year history per metric
- `data/ai_snapshot.json` — exact extract-pass payload (auditable input)
- `data/ai_themes.json`, `data/ai_news_themes.json` — extract-pass JSON outputs
- `charts/0[1-5]_*.png` — Matplotlib charts (Agg backend, headless)

Daily artifacts are committed by GitHub Actions with `[skip ci]` to avoid recursive runs.

---

## Local-only files (gitignored)

- **`TASKS.md`** — the working checklist. Not part of the deliverable. The local copy is intentionally a superset of any prior version (preserves both `_Original acceptance criteria_` and `**Shipped**` notes).
- **`PICKUP_TOMORROW.md`** — personal continuation notes.
- **`.streamlit/secrets.toml`** and **`.env`** — only the `.example` versions are tracked.

---

## When extending

- **New metric** → add a `Metric` to `config.py::METRICS`, write the fetcher in `data/fetchers.py`, wire it into `data/cache.py::get_all_with_derived()`, add a card in the dashboard top row + a row in the desk-note snapshot table. Justify desk-relevance in the commit message.
- **New derived series** → `analysis/derived.py` only; pin behaviour in `tests/test_derived.py`.
- **New rule-based observation** → `analysis/signals.py`; thresholds belong in `config.py`.
- **New AI capability** → new prompt file in `ai/prompts/` (versioned), new module in `ai/`, route through `ai/client.py`. Always pair with a deterministic fallback.
- **New section in the desk note** → must keep the PDF at ≤3 pages. If something has to give, prune lower-value prose, don't shrink fonts.
