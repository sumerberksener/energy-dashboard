"""Every external call that used to be able to block forever now has a finite timeout.

One test per call site. Two kinds:

* "is built with a timeout": the library object or call is recorded and its
  timeout argument inspected (ENTSO-E clients, Yahoo download, RSS GET);
* "does not block": the real library talks to a loopback server that accepts
  the connection and never answers, with the timeout shortened to half a
  second. On the old code these calls block for as long as the server stays
  silent, so the test gives up after a few seconds and fails.

All offline: loopback only, no tokens, no live data.
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import anthropic
import feedparser
import pandas as pd
import pytest
import requests

import config
from ai import client as ai_client
from data import fetchers, news
from tests.loopback import LoopbackServer

pytestmark = pytest.mark.usefixtures("offline")

REPO_ROOT = Path(__file__).resolve().parent.parent
SHORT = 0.5          # seconds: the shortened timeout used against a silent server
GIVE_UP_S = 20.0     # a call that is still blocked after this long is "blocked forever"


def _timeout_seconds(value) -> float:
    """Reduce a requests/httpx timeout (number or object) to its longest phase."""
    if isinstance(value, (int, float)):
        return float(value)
    phases = [getattr(value, a, None) for a in ("connect", "read", "write", "pool")]
    nums = [float(p) for p in phases if p is not None]
    assert nums, f"no finite phase in timeout {value!r}"
    return max(nums)


def _run_bounded(fn, limit_s: float = GIVE_UP_S):
    """Run fn() in a daemon thread. Returns (elapsed_s, outcome) where outcome is
    the return value or the exception it raised; fails if fn is still blocked."""
    box: dict = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as e:  # noqa: BLE001 - the test inspects whatever came out
            box["error"] = e

    started = time.monotonic()
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(limit_s)
    assert not t.is_alive(), f"still blocked after {limit_s:.0f}s: no timeout took effect"
    return time.monotonic() - started, box.get("error", box.get("value"))


@pytest.fixture
def silent_server():
    server = LoopbackServer()
    yield server
    server.close()


# --- configured numbers and the workflow ------------------------------------


def test_configured_timeouts_are_finite_and_modest():
    assert 0 < config.API_TIMEOUT_S <= 120
    assert 0 < config.QUICK_TIMEOUT_S <= 30


def test_workflow_job_limit_is_40_minutes():
    text = (REPO_ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert re.findall(r"^\s*timeout-minutes:\s*(\d+)\s*$", text, re.M) == ["40"]


# --- ENTSO-E (three client constructions) -----------------------------------


class _RecordingEntsoeClient:
    """Stands in for entsoe.EntsoePandasClient; remembers how it was built."""
    built: list[dict] = []

    def __init__(self, **kwargs):
        type(self).built.append(kwargs)

    def __getattr__(self, name):
        raise RuntimeError("stop: the test only inspects the constructor")


@pytest.mark.parametrize("call", [
    lambda: fetchers.fetch_de_power("DUMMY"),
    lambda: fetchers.fetch_renewable_share("DUMMY"),
    lambda: fetchers.fetch_cross_border_flow("DUMMY", "DE_LU", "FR"),
], ids=["day_ahead_prices", "renewable_share", "cross_border_flow"])
def test_every_entsoe_client_is_built_with_a_timeout(monkeypatch, call):
    import entsoe

    _RecordingEntsoeClient.built = []
    monkeypatch.setattr(entsoe, "EntsoePandasClient", _RecordingEntsoeClient)
    with pytest.raises(RuntimeError, match="stop"):
        call()
    (kwargs,) = _RecordingEntsoeClient.built
    assert kwargs["api_key"] == "DUMMY"
    assert 0 < _timeout_seconds(kwargs.get("timeout")) <= 120
    assert isinstance(kwargs.get("session"), requests.Session)


def test_a_silent_entsoe_server_cannot_block_the_fetch(monkeypatch, silent_server):
    import entsoe.entsoe

    monkeypatch.setattr(entsoe.entsoe, "URL", silent_server.url + "/api")
    monkeypatch.setattr(fetchers, "API_TIMEOUT_S", SHORT, raising=False)
    elapsed, outcome = _run_bounded(lambda: fetchers.fetch_de_power("DUMMY"))
    assert isinstance(outcome, requests.exceptions.Timeout), outcome
    assert elapsed < GIVE_UP_S and silent_server.accepted >= 1


# --- Yahoo Finance -----------------------------------------------------------


def test_yahoo_download_is_given_an_explicit_timeout(monkeypatch):
    import yfinance

    seen: list[dict] = []

    def fake_download(*args, **kwargs):
        seen.append(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(yfinance, "download", fake_download)
    with pytest.raises(RuntimeError, match="Yahoo Finance returned empty"):
        fetchers.fetch_eurusd()
    (kwargs,) = seen
    assert 0 < _timeout_seconds(kwargs.get("timeout")) <= 30


# --- RSS ----------------------------------------------------------------------


_RSS = (b'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>T</title>'
        b'<item><title>Gas storage draws</title><link>http://example.invalid/a</link>'
        b'<description>Storage.</description><pubDate>%s</pubDate></item></channel></rss>')


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.url = "https://feeds.example.invalid/rss"
        self.headers = {"Content-Type": "application/rss+xml; charset=utf-8"}


def test_rss_fetch_passes_a_timeout_and_parses_the_bytes(monkeypatch):
    from email.utils import format_datetime
    from datetime import datetime, timezone

    body = _RSS % format_datetime(datetime.now(timezone.utc)).encode()
    gets: list[tuple] = []
    parsed_inputs: list = []
    real_parse = feedparser.parse

    def fake_get(url, **kwargs):
        gets.append((url, kwargs))
        return _FakeResponse(body)

    def spying_parse(source, *args, **kwargs):
        parsed_inputs.append(source)
        return real_parse(source, *args, **kwargs)

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(feedparser, "parse", spying_parse)
    df = news.fetch_headlines(feeds=[("Fixture", "https://feeds.example.invalid/rss")])

    (url, kwargs), = gets
    assert url == "https://feeds.example.invalid/rss"
    assert 0 < _timeout_seconds(kwargs.get("timeout")) <= 30
    assert kwargs["headers"]["User-Agent"] == "Mozilla/5.0"
    assert parsed_inputs and not any(isinstance(s, str) for s in parsed_inputs), \
        "feedparser must get the downloaded bytes, never the URL (it has no timeout)"
    assert df["title"].tolist() == ["Gas storage draws"]


def test_a_silent_feed_cannot_block_the_news_step(monkeypatch, silent_server):
    monkeypatch.setattr(news, "QUICK_TIMEOUT_S", SHORT, raising=False)
    feeds = [("Silent", silent_server.url + "/feed.xml")]
    elapsed, outcome = _run_bounded(lambda: news.fetch_headlines(feeds=feeds))
    assert isinstance(outcome, pd.DataFrame) and outcome.empty   # soft-fails like before
    assert elapsed < GIVE_UP_S and silent_server.accepted >= 1


# --- Anthropic ----------------------------------------------------------------


def test_the_ai_client_has_a_timeout_and_keeps_the_sdk_retries(tmp_path):
    client = ai_client.AIClient(api_key="DUMMY_NOT_A_REAL_KEY", log_dir=tmp_path)._client
    assert 0 < _timeout_seconds(client.timeout) <= 120
    assert client.max_retries == anthropic.DEFAULT_MAX_RETRIES


def test_a_silent_ai_server_cannot_block_the_call(monkeypatch, tmp_path, silent_server):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", silent_server.url)
    monkeypatch.setattr(ai_client, "API_TIMEOUT_S", SHORT, raising=False)
    client = ai_client.AIClient(api_key="DUMMY_NOT_A_REAL_KEY", log_dir=tmp_path)
    elapsed, outcome = _run_bounded(lambda: client.generate("system", "user"))
    assert isinstance(outcome, anthropic.APITimeoutError), outcome
    assert elapsed < GIVE_UP_S
    assert silent_server.accepted >= 1
