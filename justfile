# Energy Dashboard — common commands. Run `just <target>` (https://github.com/casey/just).
# Equivalent Make targets work; pick one. All assume an active venv.

# Default: list available recipes.
default:
    @just --list

# Run the headless CLI to generate today's desk note + artifacts.
brief:
    python scripts/generate_brief.py

# Same, but force single-pass AI (faster, no extract step).
brief-single-pass:
    python scripts/generate_brief.py --single-pass

# Launch the interactive Streamlit dashboard.
dashboard:
    streamlit run app.py

# Run the full test suite (skips fetcher tests when network/tokens unavailable).
test:
    pytest -q

# Run only the pure-logic tests (no network).
test-logic:
    pytest -q tests/test_stats.py tests/test_derived.py

# Render the current desk note to PDF (requires pandoc + a TeX distribution).
pdf date=`date -u +%Y-%m-%d`:
    pandoc "output/{{date}}/desk_note_{{date}}.md" \
        -o "output/{{date}}/desk_note_{{date}}.pdf" \
        --pdf-engine=xelatex \
        -V geometry:margin=1in \
        -V mainfont="Helvetica" \
        --resource-path="output/{{date}}"

# Wipe local parquet cache + outputs (regenerates on next run).
clean:
    rm -rf data/store/*.parquet output/* ai/logs/*.jsonl

# Re-pin requirements.lock from the active venv.
lock:
    pip freeze > requirements.lock

# Type-check the public API only (mypy --strict on data/, analysis/, ai/).
typecheck:
    mypy --strict data analysis ai 2>&1 | tail -30
