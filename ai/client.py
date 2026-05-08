"""Anthropic Claude client wrapper with JSONL request/response logging.

Design choices:
- Each call appends a JSON record to ai/logs/<YYYY-MM-DD>.jsonl. Records
  capture timestamp, model, prompt SHA-256 hashes, full text, usage tokens,
  and latency — auditable across runs without re-querying the API.
- No prompt caching: Haiku 4.5 requires a 4096-token cacheable prefix; both
  the extract and narrate system prompts are ~300–500 tokens each, well
  below the threshold, so adding `cache_control={"type":"ephemeral"}` would
  pay the cache-write surcharge with zero subsequent reads. If the prompts
  grow past ~4 K tokens — e.g. if a few-shot block or schema appendix is
  added — flip it on then. Verified against current SDK docs (2026-04).
- Adaptive thinking and the effort parameter are skipped: short factual
  narratives don't benefit from extended reasoning, and the cost saving is
  negligible at this volume.
- API key sourced from ANTHROPIC_API_KEY (SDK default) or constructor arg.
  Missing key raises NoAPIKey for the caller to catch and fall back gracefully.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import anthropic

log = logging.getLogger(__name__)


# Cost-aware model tiering — see README §AI workflow for rationale.
# Haiku is the default for structured-JSON tasks (extract pass, news themes
# extraction) where reasoning over the schema dominates and prose polish
# doesn't matter. Sonnet upgrades the *narrate* pass that writes the desk
# note's executive summary — the first thing a trader reads — where prose
# quality, sentence variety, and operational call-outs measurably improve
# over Haiku per side-by-side eval. Costs: Haiku ~$0.003/call, Sonnet
# ~$0.01/call. Daily-cron impact: a few cents per month.
# Both overrideable via env vars for one-line rollback / experimentation.
DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "claude-haiku-4-5")
NARRATE_MODEL = os.environ.get("CLAUDE_NARRATE_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = 1024


class NoAPIKey(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is unavailable. Callers should fall back."""


@dataclass
class AIResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    duration_ms: int
    log_path: str
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


class AIClient:
    """Anthropic Claude wrapper with append-only JSONL logging."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        log_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise NoAPIKey("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=key)
        self.model = model
        self.log_dir = Path(log_dir) if log_dir else Path(__file__).parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

    def _log_path(self) -> Path:
        return self.log_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    def _append_log(self, record: dict) -> Path:
        path = self._log_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def generate(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        purpose: str = "narrative",
    ) -> AIResult:
        """Call the model and log the round trip.

        Raises anthropic.* exceptions for API failures; callers should catch
        and decide whether to retry, fall back, or surface the error.
        """
        started = time.perf_counter()
        ts = datetime.now(timezone.utc).isoformat()

        try:
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            text = next((b.text for b in resp.content if b.type == "text"), "").strip()
            duration_ms = int((time.perf_counter() - started) * 1000)

            usage = resp.usage
            record = {
                "timestamp": ts,
                "purpose": purpose,
                "model": self.model,
                "system_sha": self._sha256(system_prompt),
                "user_sha": self._sha256(user_message),
                "system_text": system_prompt,
                "user_text": user_message,
                "response_text": text,
                "stop_reason": resp.stop_reason,
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
                    "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
                },
                "duration_ms": duration_ms,
                "error": None,
            }
            log_path = self._append_log(record)

            return AIResult(
                text=text,
                model=self.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                duration_ms=duration_ms,
                log_path=str(log_path),
                cache_read_tokens=record["usage"]["cache_read_input_tokens"],
                cache_creation_tokens=record["usage"]["cache_creation_input_tokens"],
            )

        except anthropic.APIError as e:
            duration_ms = int((time.perf_counter() - started) * 1000)
            self._append_log({
                "timestamp": ts,
                "purpose": purpose,
                "model": self.model,
                "system_sha": self._sha256(system_prompt),
                "user_sha": self._sha256(user_message),
                "system_text": system_prompt,
                "user_text": user_message,
                "response_text": None,
                "stop_reason": None,
                "usage": None,
                "duration_ms": duration_ms,
                "error": {"type": type(e).__name__, "message": str(e)},
            })
            raise


def load_prompt(name: str) -> str:
    """Load a versioned prompt from ai/prompts/."""
    p = Path(__file__).parent / "prompts" / f"{name}.md"
    return p.read_text(encoding="utf-8").strip()
