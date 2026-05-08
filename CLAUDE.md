# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Cobblestone Energy case-study submission: an automated daily desk note converting public EU gas + carbon fundamentals into a power-curve narrative. Two surfaces share one pipeline — a Streamlit dashboard (`app.py`) and a headless CLI (`scripts/generate_brief.py`). The CLI is what GitHub Actions runs at 07:30 UTC weekdays (`.github/workflows/daily.yml`).

The full README is the single source of truth on the *what and why* (eight metrics, plant assumptions, methodology). This file covers only the *how to work in the codebase* without re-reading it.

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
```

Single test: `pytest -q tests/test_derived.py::test_clean_spark_basic`

Three free credentials are required for live runs (CLI reads from env, dashboard reads from `.streamlit/secrets.toml`): `ENTSOE_TOKEN`, `AGSI_TOKEN`, `ANTHROPIC_API_KEY`. Without them the pipeline still produces output via deterministic fallbacks.

## Layer invariants (the most important rule in the repo)

The codebase splits into four layers with strict import rules. **Do not violate these** — they're what lets the same fetchers + analysis power both Streamlit and the headless CLI:

| Layer | Allowed imports | Forbidden |
|---|---|---|
| `data/` | pandas, numpy, requests, entsoe-py, yfinance | ❌ no `import streamlit` |
| `analysis/` | pandas, numpy | ❌ no streamlit, no I/O, no API calls |
| `ai/` | anthropic SDK, stdlib | only module that may instantiate `anthropic.Anthropic()` |
| `ui/`, `app.py` | everything (streamlit-aware) | this is the only Streamlit-aware code |

Caching layer (`data/cache.py`) is the one place that wraps fetchers with `@st.cache_data` + parquet snapshot fallback — it's the bridge between the pure data layer and Streamlit.

## AI workflow rules

- **Every AI call routes through `ai/client.py`.** It enforces append-only JSONL logging to `ai/logs/<date>.jsonl` (timestamp, model, prompt SHA-256, full text, token usage, latency). Do not call `anthropic.Anthropic()` directly anywhere else — the audit trail is a hard requirement of the case-study brief.
- **Two-pass design**: `ai/narrative.py` runs **extract** (strict JSON, schema in `ai/prompts/extract_v1.md`) → **narrate** (prose grounded *only* in the extract JSON, `ai/prompts/narrate_v1.md`). The narrate prompt explicitly forbids referencing anything not in pass-1 output. A separate news-themes pass (`ai/news_themes.py` + `ai/prompts/news_themes_v1.md`) runs over RSS headlines.
- **Versioned prompts**: prompt files end in `_v1.md`. Bump the version in the filename (and update the loader) rather than mutating an existing prompt — the SHA changes invalidate logs otherwise.
- **Graceful fallback**: when `ANTHROPIC_API_KEY` is missing or a call fails, deterministic rule-based output is emitted from the same JSON snapshot. Never let an AI failure break the pipeline.
- **No prompt caching today**: the system prompts sit below Haiku 4.5's 4096-token cacheable prefix. See the comment in `ai/client.py` for when to flip it on.

## Configuration single-source-of-truth

- **Metric registry** lives in `config.py::METRICS` (a list of frozen `Metric` dataclasses). Adding a metric is a one-place change — `PRIMARY_KEYS`, `DERIVED_KEYS`, `TOP_ROW_METRICS`, `FUNDAMENTALS_METRICS` are all derived from it.
- **Plant assumptions and signal thresholds** (η_gas, η_coal, EF_gas, EF_coal, percentile/sigma cutoffs, `STALE_AFTER_DAYS`) also live in `config.py`. Don't hardcode these elsewhere.
- **Forward curve horizons**: `analysis/derived.py::HORIZON_BDAYS` (W+1=5, M+1=21, Q+1=65, Cal+1=252, Cal+2=504). All five share `seasonality_projection()`; `cal1_seasonality_projection` is a thin back-compat wrapper.

## Output directory contract

`scripts/generate_brief.py` writes to `output/<YYYY-MM-DD>/`:
- `desk_note_<date>.{md,pdf}` — the deliverable; PDF must stay ≤3 pages
- `data/snapshot.csv` — pivot of latest values
- `data/<metric>.csv` — full multi-year history per metric
- `data/ai_snapshot.json` — exact extract-pass payload (auditable input)
- `data/ai_themes.json`, `data/ai_news_themes.json` — extract-pass JSON outputs
- `charts/0[1-5]_*.png` — Matplotlib charts (Agg backend, headless)

Daily artifacts are committed by GitHub Actions with `[skip ci]` to avoid recursive runs.

## Local-only files

- **`TASKS.md`** is the working checklist — gitignored, not part of the deliverable. The local copy is intentionally a superset of any prior version (preserves both `_Original acceptance criteria_` and `**Shipped**` notes for completed items).
- **`PICKUP_TOMORROW.md`** is personal notes — gitignored.
- `.streamlit/secrets.toml` and `.env` are gitignored; only the `.example` versions are tracked.

## When extending

- New metric → add a `Metric` to `config.py::METRICS`, write the fetcher in `data/fetchers.py`, add it to `data/cache.py::get_all_with_derived()`, and add a card in the dashboard top row + a row in the desk-note snapshot table.
- New derived series → `analysis/derived.py` only; pin behaviour in `tests/test_derived.py`.
- New rule-based observation → `analysis/signals.py`; thresholds belong in `config.py`.
- New AI capability → new prompt file in `ai/prompts/`, new module in `ai/`, route through `ai/client.py`. Always pair with a deterministic fallback.
