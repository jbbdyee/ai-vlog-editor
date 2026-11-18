"""TODO 26: the "편집 두뇌" for chat editing — one place that picks which AI reads a sentence.

Two brains fill the same small JSON form:
- ``ollama``: the local AI (free; CUTORY_CHAT_LLM_MODEL, default qwen2.5:7b since TODO 27).
- ``claude``: Claude through the official SDK (paid, needs ANTHROPIC_API_KEY; model CUTORY_CLAUDE_MODEL,
  default claude-haiku-5-5, the cheapest one).

``CUTORY_CHAT_BRAIN`` picks the default (``claude`` when a key is set, otherwise ``ollama``); the screen can also
ask for one per message. Every call reports its token use so the screen can show what Claude cost.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable

import httpx

from backend.app.services.llm_edit_interpreter import LLMEditError, ollama_num_ctx, ollama_timeout

DEFAULT_CLAUDE_MODEL = "claude-haiku-5-5"
DEFAULT_CHAT_OLLAMA_MODEL = "qwen2.5:7b"
TIMEOUT_SECONDS = 90.0
# USD per 1M tokens (input, output). Used only for the rough cost shown on screen.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}


@dataclass(frozen=True)
class BrainReply:
    text: str  # raw JSON text
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Brain:
    key: str  # "claude" | "ollama"
    model: str
    ask: Callable[[str, str, dict], BrainReply]  # (system, user, json_schema) -> reply

    @property
    def label(self) -> str:
        return f"{'Claude' if self.key == 'claude' else '로컬 AI'} · {self.model}"


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def _ollama(model: str, base: str) -> Brain:
    def ask(system: str, user: str, schema: dict) -> BrainReply:
        try:
            num_ctx = ollama_num_ctx(system, user, json.dumps(schema))  # TODO 32-2: long requests lost their start
            response = httpx.post(f"{base}/api/chat", timeout=max(TIMEOUT_SECONDS, ollama_timeout(num_ctx)), json={
                "model": model, "stream": False, "format": schema, "options": {"temperature": 0, "num_ctx": num_ctx},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        except httpx.TimeoutException as error:
            raise LLMEditError("LLM_TIMEOUT") from error
        except httpx.HTTPError as error:
            raise LLMEditError("LLM_UNAVAILABLE") from error
        if response.status_code != 200:
            raise LLMEditError("LLM_HTTP_ERROR")
        try:
            body = response.json()
            return BrainReply(body["message"]["content"], int(body.get("prompt_eval_count") or 0),
                              int(body.get("eval_count") or 0))
        except (ValueError, KeyError, TypeError) as error:
            raise LLMEditError("LLM_BAD_RESPONSE") from error
    return Brain("ollama", model, ask)


def _claude(model: str, key: str) -> Brain:
    def ask(system: str, user: str, schema: dict) -> BrainReply:
        import anthropic
        client = anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SECONDS, max_retries=1)
        try:
            response = client.messages.create(
                model=model, max_tokens=4000,
                # The cut table is the same for every message on one plan, so it is cached.
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APITimeoutError as error:
            raise LLMEditError("LLM_TIMEOUT") from error
        except anthropic.AuthenticationError as error:
            raise LLMEditError("CLAUDE_KEY_INVALID") from error
        except anthropic.RateLimitError as error:
            raise LLMEditError("CLAUDE_RATE_LIMITED") from error
        except anthropic.APIStatusError as error:
            raise LLMEditError("LLM_HTTP_ERROR") from error
        except anthropic.APIConnectionError as error:
            raise LLMEditError("LLM_UNAVAILABLE") from error
        if response.stop_reason == "refusal":
            raise LLMEditError("CLAUDE_REFUSED")
        text = next((block.text for block in response.content if block.type == "text"), "")
        usage = response.usage
        read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        # Cached input costs about a tenth, a cache write about 1.25x: fold both into "input tokens" for the bill.
        billed_input = int(usage.input_tokens) + round(read * 0.1) + round(written * 1.25)
        return BrainReply(text, billed_input, int(usage.output_tokens))
    return Brain("claude", model, ask)


def available_brains() -> dict[str, Brain]:
    brains: dict[str, Brain] = {}
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            pass
        else:
            brains["claude"] = _claude(os.environ.get("CUTORY_CLAUDE_MODEL") or DEFAULT_CLAUDE_MODEL, key)
    if os.environ.get("CUTORY_EDIT_LLM_PROVIDER", "").strip().lower() == "ollama":
        # TODO 27: chat editing has its own local model (qwen2.5:7b did best in the TODO 26 trial); the story
        # direction and reel captions keep CUTORY_EDIT_LLM_MODEL.
        model = os.environ.get("CUTORY_CHAT_LLM_MODEL") or DEFAULT_CHAT_OLLAMA_MODEL
        base = (os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        brains["ollama"] = _ollama(model, base)
    return brains


def default_brain_key(brains: dict[str, Brain]) -> str | None:
    wanted = os.environ.get("CUTORY_CHAT_BRAIN", "").strip().lower()
    if wanted in brains:
        return wanted
    for key in ("claude", "ollama"):
        if key in brains:
            return key
    return None


def parse_json(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError as error:
        raise LLMEditError("LLM_BAD_RESPONSE") from error
    if not isinstance(value, dict):
        raise LLMEditError("LLM_BAD_RESPONSE")
    return value
