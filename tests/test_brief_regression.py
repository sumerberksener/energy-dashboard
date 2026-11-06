"""The timeouts and log lines must change nothing when every source is healthy.

The reference is the pre-fix code itself (tests/legacy_reference.py, verbatim
from commit 7f71374), run on the same fixtures in the same process. Where the
old code is deterministic for a fixture, the new code must reproduce it
exactly: the fetched frames, the console output, and every file the brief
writes (desk note Markdown, snapshot and per-metric CSVs, AI snapshot and
theme JSONs), the RSS rows, and the request headers sent to a feed. Nothing
touches the internet.
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from data import fetchers, news
from scripts import generate_brief as gb
from tests import legacy_reference as legacy
from tests.fake_sources import ALL_SOURCES, install_fake_sources
from tests.loopback import LoopbackServer, http_reply

pytestmark = pytest.mark.usefixtures("offline")

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- fetch_all ---------------------------------------------------------------


def _assert_same_data(new: dict, old: dict) -> None:
    assert list(new) == list(old)
    for key in old:
        assert_frame_equal(new[key], old[key], check_freq=False, obj=key)
        assert new[key].attrs == old[key].attrs, key


def test_fetch_all_reproduces_the_old_result_for_healthy_sources(monkeypatch):
    install_fake_sources(monkeypatch)
    old = legacy.fetch_all()
    new = gb.fetch_all()
    assert len(new) >= 20  # primaries + derived + projections + flows + weather
    _assert_same_data(new, old)


def test_fetch_all_reproduces_the_old_degradation_for_failing_sources(monkeypatch):
    """Failing / empty / None sources degrade exactly as before (empty `value` frame)."""
    install_fake_sources(monkeypatch)

    def raising(*a, **k):
        raise RuntimeError("upstream exploded")

    monkeypatch.setattr(fetchers, "fetch_ttf", raising)
    monkeypatch.setattr(fetchers, "fetch_eua", lambda: pd.DataFrame(columns=["value"]))
    monkeypatch.setattr(fetchers, "fetch_jkm", lambda: None)
    old = legacy.fetch_all()
    new = gb.fetch_all()
    for key in ("ttf", "eua", "jkm"):
        assert new[key].empty and list(new[key].columns) == ["value"]
    _assert_same_data(new, old)


def test_every_fake_source_is_actually_exercised(monkeypatch):
    calls = install_fake_sources(monkeypatch)
    gb.fetch_all()
    assert all(calls[name] for name in ALL_SOURCES), {k: len(v) for k, v in calls.items()}


# --- the whole brief ---------------------------------------------------------


def _fake_headlines(*args, **kwargs) -> pd.DataFrame:
    now = datetime.now(timezone.utc)
    return pd.DataFrame({
        "source": ["Fixture Wire", "Fixture Wire", "Other Wire"],
        "published_at": [now - timedelta(hours=2), now - timedelta(hours=9),
                         now - timedelta(days=1)],
        "title": ["Gas storage injections slow", "EUA auction clears higher",
                  "German wind output set to ease"],
        "summary": ["Storage draws.", "Carbon supply.", "Weather."],
        "link": ["https://example.invalid/a", "https://example.invalid/b",
                 "https://example.invalid/c"],
    })


def _run_main(monkeypatch, capsys, out_root: Path, *, old_fetch_layer: bool) -> tuple[str, Path]:
    install_fake_sources(monkeypatch)
    monkeypatch.setattr(news, "fetch_headlines", _fake_headlines)
    for key in ("ANTHROPIC_API_KEY", "ENTSOE_TOKEN", "AGSI_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    if old_fetch_layer:
        monkeypatch.setattr(gb, "_safe_fetch", legacy._safe_fetch)
        monkeypatch.setattr(gb, "fetch_all", legacy.fetch_all)
    monkeypatch.setattr(sys, "argv", ["generate_brief.py", "--out-root", str(out_root)])
    capsys.readouterr()
    assert gb.main() == 0
    out = capsys.readouterr().out.replace(str(out_root), "<OUT>")
    (run_dir,) = [p for p in out_root.iterdir() if p.is_dir()]
    return out, run_dir


def _tree(run_dir: Path) -> dict[str, bytes]:
    return {str(p.relative_to(run_dir)): p.read_bytes()
            for p in sorted(run_dir.rglob("*")) if p.is_file()}


def test_the_brief_is_identical_to_what_the_old_fetch_layer_produces(
        monkeypatch, capsys, tmp_path):
    ai_logs = REPO_ROOT / "ai" / "logs"
    logs_before = sorted((p.name, p.stat().st_size) for p in ai_logs.glob("*.jsonl"))

    new_out, new_dir = _run_main(monkeypatch, capsys, tmp_path / "new", old_fetch_layer=False)
    old_out, old_dir = _run_main(monkeypatch, capsys, tmp_path / "old", old_fetch_layer=True)

    assert new_out == old_out, "console output of the brief changed"

    new_tree, old_tree = _tree(new_dir), _tree(old_dir)
    assert sorted(new_tree) == sorted(old_tree)
    md = [k for k in new_tree if k.endswith(".md")]
    assert len(md) == 1 and len(new_tree[md[0]]) > 3000
    charts = [k for k in new_tree if k.endswith(".png")]
    assert len(charts) >= 4 and all(len(new_tree[k]) > 1000 for k in charts)
    for rel, content in new_tree.items():
        if rel.endswith(".png"):
            continue  # same files exist and are non-empty; pixel bytes are not asserted
        assert content == old_tree[rel], f"{rel} differs from the old output"

    # the note itself: structure and the AI-free wording survive
    note = new_tree[md[0]].decode("utf-8")
    assert "Rule-based / informational" in note
    assert "data/ai_news_themes.json" in new_tree and "data/ai_snapshot.json" in new_tree
    # no AI call was made, so no AI log was written or touched
    assert logs_before == sorted((p.name, p.stat().st_size) for p in ai_logs.glob("*.jsonl"))


# --- RSS: same rows, same request headers, as feedparser alone ---------------


def _rss(encoding: str) -> bytes:
    def d(hours: int) -> str:
        return format_datetime(datetime.now(timezone.utc) - timedelta(hours=hours))
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        '<rss version="2.0"><channel><title>Fixture</title><link>http://example.invalid/</link>'
        '<item><title>Café gas hub spread widens</title><link>/story/1</link>'
        f'<description>&lt;p&gt;TTF &amp;amp; NBP &lt;b&gt;move&lt;/b&gt;&lt;/p&gt;</description><pubDate>{d(3)}</pubDate></item>'
        '<item><title>EUA curve flattens</title><link>http://example.invalid/story/2</link>'
        f'<description>Carbon.</description><pubDate>{d(30)}</pubDate></item>'
        '<item><title>Too old to keep</title><link>http://example.invalid/old</link>'
        f'<description>Old.</description><pubDate>{d(24 * 40)}</pubDate></item>'
        '</channel></rss>'
    )
    return xml.encode(encoding)


def _both_paths(reply: bytes) -> tuple[pd.DataFrame, pd.DataFrame, LoopbackServer]:
    """Run the old (feedparser alone) and the new fetch against one fixture server."""
    server = LoopbackServer(reply=reply)
    try:
        feeds = [("Fixture Wire", server.url + "/feed.xml")]
        old = legacy.legacy_fetch_headlines(feeds=feeds)
        new = news.fetch_headlines(feeds=feeds)
    finally:
        server.close()
    return old, new, server


@pytest.mark.parametrize("encoding, content_type", [
    ("utf-8", "application/rss+xml; charset=utf-8"),
    ("iso-8859-1", "application/rss+xml; charset=iso-8859-1"),
    ("iso-8859-1", "application/rss+xml"),   # encoding only declared in the XML prolog
])
def test_headlines_match_the_old_feedparser_only_path(encoding, content_type):
    old, new, server = _both_paths(http_reply(_rss(encoding), content_type))
    assert len(old) == 2, old   # the 40-day-old item is filtered, the other two kept
    assert_frame_equal(new, old)
    assert "Café" in new["title"].iloc[0]
    # the relative link was resolved against the feed URL, the same way in both paths
    assert new["link"].iloc[0] == server.url + "/story/1"


def test_a_gzip_compressed_feed_gives_the_same_rows():
    reply = http_reply(gzip.compress(_rss("utf-8")), "application/rss+xml; charset=utf-8",
                       extra_headers={"Content-Encoding": "gzip"})
    old, new, _ = _both_paths(reply)
    assert len(old) == 2
    assert_frame_equal(new, old)


def test_a_non_feed_error_page_yields_nothing_in_both_paths():
    old, new, _ = _both_paths(http_reply(b"<html><body>Forbidden</body></html>",
                                         "text/html", "403 Forbidden"))
    assert old.empty and new.empty
    assert list(new.columns) == list(old.columns)


def test_the_feed_request_carries_the_same_headers_as_before():
    _, _, server = _both_paths(http_reply(_rss("utf-8"), "application/rss+xml"))
    (old_line, old_headers), (new_line, new_headers) = server.requests
    assert old_line == new_line == "GET /feed.xml HTTP/1.1"
    for name in ("user-agent", "accept", "accept-encoding", "a-im"):
        assert old_headers[name] == new_headers[name], name
    assert new_headers["user-agent"] == "Mozilla/5.0"


# --- AI: same calls, same audit trail ---------------------------------------


_ANTHROPIC_REPLY = json.dumps({
    "id": "msg_fixture", "type": "message", "role": "assistant",
    "model": "claude-haiku-4-5",
    "content": [{"type": "text", "text": "  Fixture narrative.  "}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 11, "output_tokens": 4},
}).encode()


def test_ai_call_is_logged_exactly_as_before(monkeypatch, tmp_path):
    from ai.client import AIClient

    server = LoopbackServer(reply=http_reply(_ANTHROPIC_REPLY, "application/json"))
    try:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", server.url)
        client = AIClient(api_key="DUMMY_NOT_A_REAL_KEY", log_dir=tmp_path)
        r1 = client.generate("system prompt", "user message", purpose="extract")
        r2 = client.generate("system prompt", "user message 2", purpose="narrate")
    finally:
        server.close()

    assert (r1.text, r1.model, r1.input_tokens, r1.output_tokens) == \
        ("Fixture narrative.", "claude-haiku-4-5", 11, 4)
    assert r2.log_path == r1.log_path
    lines = Path(r1.log_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                          # append-only, one record per call
    rec = json.loads(lines[0])
    assert set(rec) == {
        "timestamp", "purpose", "model", "system_sha", "user_sha", "system_text",
        "user_text", "response_text", "stop_reason", "usage", "duration_ms", "error",
    }
    assert set(rec["usage"]) == {
        "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens",
    }
    assert rec["purpose"] == "extract" and rec["error"] is None
    assert rec["system_text"] == "system prompt" and rec["user_text"] == "user message"
    assert rec["response_text"] == "Fixture narrative." and rec["stop_reason"] == "end_turn"
    assert rec["system_sha"] == AIClient._sha256("system prompt")
