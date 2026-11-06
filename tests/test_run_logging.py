"""The run logs when it starts and when each data source starts and ends, so the
next stall shows exactly where it happened. Offline; no tokens in any log line."""
from __future__ import annotations

import logging
import re
import sys
import time

import pandas as pd
import pytest

from data import news
from scripts import generate_brief as gb
from tests.fake_sources import install_fake_sources

pytestmark = pytest.mark.usefixtures("offline")

END = r"^{name}: end (ok|empty|failed) in (\d+\.\d)s$"


def _brief_lines(caplog, level=logging.INFO) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == "brief" and r.levelno == level]


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"value": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2))


def test_a_healthy_source_logs_start_and_end_ok(caplog):
    caplog.set_level(logging.INFO, logger="brief")
    df = gb._safe_fetch("ttf", lambda: _frame())
    assert df.equals(_frame())
    lines = _brief_lines(caplog)
    assert lines[0] == "ttf: start"
    assert re.match(END.format(name="ttf"), lines[1]) and lines[1].split()[2] == "ok"
    assert len(lines) == 2


@pytest.mark.parametrize("result", [None, pd.DataFrame(columns=["value"])], ids=["none", "empty"])
def test_an_empty_source_logs_end_empty(caplog, result):
    caplog.set_level(logging.INFO, logger="brief")
    df = gb._safe_fetch("eua", lambda: result)
    assert df.empty and list(df.columns) == ["value"]
    lines = _brief_lines(caplog)
    assert lines[0] == "eua: start"
    assert re.match(END.format(name="eua"), lines[1]) and lines[1].split()[2] == "empty"


def test_a_failing_source_logs_end_failed_and_never_the_token(caplog):
    secret = "SECRET-TOKEN-123"

    def boom():
        raise RuntimeError(f"401 for url: https://example.invalid/api?securityToken={secret}&x=1")

    caplog.set_level(logging.INFO, logger="brief")
    df = gb._safe_fetch("de_power", boom)
    assert df.empty and list(df.columns) == ["value"]
    lines = _brief_lines(caplog)
    assert lines[0] == "de_power: start"
    assert re.match(END.format(name="de_power"), lines[1]) and lines[1].split()[2] == "failed"
    assert not any(secret in line or "securityToken" in line for line in lines), \
        "the new start/end lines must never carry a token or a URL"


def test_the_end_line_reports_the_seconds_the_source_took(caplog):
    caplog.set_level(logging.INFO, logger="brief")

    def slow():
        time.sleep(0.3)
        return _frame()

    gb._safe_fetch("coal", slow)
    seconds = float(re.match(END.format(name="coal"), _brief_lines(caplog)[1]).group(2))
    assert 0.3 <= seconds < 5.0


def test_fetch_all_logs_a_start_and_an_end_for_every_source(monkeypatch, caplog):
    install_fake_sources(monkeypatch)
    caplog.set_level(logging.INFO, logger="brief")
    gb.fetch_all()
    lines = _brief_lines(caplog)
    starts = [ln.removesuffix(": start") for ln in lines if ln.endswith(": start")]
    ends = [ln.split(": end ")[0] for ln in lines if ": end " in ln]
    assert len(starts) == 15 and starts == ends          # 9 named + 3 flows + 3 weather
    assert {"ttf", "eua", "coal", "de_power", "gb_power", "renewable_share", "storage",
            "eurusd", "jkm"} <= set(starts)
    assert len({*starts}) == len(starts)
    # each source's start comes before its own end, and the pairs do not interleave
    for i, name in enumerate(starts):
        assert lines[2 * i] == f"{name}: start" and lines[2 * i + 1].startswith(f"{name}: end ")


def test_main_logs_one_run_start_line_with_the_utc_time_before_any_source(
        monkeypatch, caplog, tmp_path):
    install_fake_sources(monkeypatch)
    monkeypatch.setattr(news, "fetch_headlines", lambda *a, **k: pd.DataFrame())
    for key in ("ANTHROPIC_API_KEY", "ENTSOE_TOKEN", "AGSI_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(sys, "argv", ["generate_brief.py", "--out-root", str(tmp_path)])
    caplog.set_level(logging.INFO)
    assert gb.main() == 0
    lines = _brief_lines(caplog)
    run_starts = [ln for ln in lines if ln.startswith("run start")]
    assert len(run_starts) == 1
    assert re.fullmatch(r"run start \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC", run_starts[0])
    assert lines[0] == run_starts[0] and lines[1] == "ttf: start"
