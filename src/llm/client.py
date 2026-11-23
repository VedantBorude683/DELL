"""Single unified LLM wrapper `llm(model_tier, messages, schema)` with token and latency logging."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from src.config import AppConfig, get_model_name

ModelTier = Literal["fast", "strong"]

_ACTIVE_USAGE_LIST: ContextVar[list[dict[str, Any]] | None] = ContextVar("active_llm_usage", default=None)
_ACTIVE_STEP_NAME: ContextVar[str] = ContextVar("active_llm_step", default="general")


@contextmanager
def capture_llm_usage() -> Iterator[list[dict[str, Any]]]:
    """Capture LLM call token, latency, and cost telemetry inside a scoped execution block."""
    records: list[dict[str, Any]] = []
    token = _ACTIVE_USAGE_LIST.set(records)
    try:
        yield records
    finally:
        _ACTIVE_USAGE_LIST.reset(token)


@contextmanager
def llm_step_context(step_name: str) -> Iterator[None]:
    """Tag subsequent llm() calls with the active pipeline stage for per-step cost attribution."""
    token = _ACTIVE_STEP_NAME.set(step_name)
    try:
        yield
    finally:
        _ACTIVE_STEP_NAME.reset(token)

# Approximate per-1M token pricing (USD) for observability logging
_PRICE_PER_1M_INPUT = {
    "gemini-2.5-flash": 0.15,
    "gemini-2.5-pro": 1.25,
}
_PRICE_PER_1M_OUTPUT = {
    "gemini-2.5-flash": 0.60,
    "gemini-2.5-pro": 5.00,
}


@dataclass(frozen=True)
class LLMCallResult:
    content: str
    parsed: dict[str, Any] | list[Any] | None
    model: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cost_usd: float


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    in_rate = _PRICE_PER_1M_INPUT.get(model, 0.50)
    out_rate = _PRICE_PER_1M_OUTPUT.get(model, 2.00)
    return round((prompt_tokens * in_rate + completion_tokens * out_rate) / 1_000_000, 6)


def _log_call(log_path: Path, payload: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def llm(
    model_tier: ModelTier,
    messages: list[dict[str, str]],
    schema: dict[str, Any] | type | None = None,
    *,
    cfg: AppConfig | None = None,
    log_path: Path = Path("logs/llm_calls.jsonl"),
) -> LLMCallResult:
    """Invoke configured model tier via Gemini SDK / REST and log tokens + latency."""
    active_cfg = cfg or AppConfig.load("config.yaml")
    model_name = get_model_name(model_tier, active_cfg)
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "MY_GEMINI_API_KEY":
        raise RuntimeError("GEMINI_API_KEY is not configured in environment.")

    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    contents = [
        {
            "role": "model" if m.get("role") == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in messages
        if m.get("role") != "system"
    ]

    started = time.perf_counter()
    raw_text = ""
    prompt_tokens = 0
    completion_tokens = 0

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore

        client = genai.Client(api_key=api_key)
        config_kwargs: dict[str, Any] = {}
        if system_parts:
            config_kwargs["system_instruction"] = "\n".join(system_parts)
        if schema is not None:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = schema

        prompt_text = "\n\n".join(f"[{m.get('role', 'user')}] {m['content']}" for m in messages)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt_text,
            config=types.GenerateContentConfig(**config_kwargs) if config_kwargs else None,
        )
        raw_text = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
            completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    except ImportError:
        # Pure-stdlib Gemini REST API fallback when google-genai Python wheel isn't installed
        body: dict[str, Any] = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        gen_cfg: dict[str, Any] = {"temperature": 0.0}
        if schema is not None:
            gen_cfg["responseMimeType"] = "application/json"
            if isinstance(schema, dict):
                gen_cfg["responseSchema"] = schema
        body["generationConfig"] = gen_cfg

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"Gemini REST error {exc.code}: {err_body}") from exc

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            raw_text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata", {})
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    cost_usd = _estimate_cost(model_name, prompt_tokens, completion_tokens)

    parsed: dict[str, Any] | list[Any] | None = None
    if schema is not None and raw_text.strip():
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            parsed = None

    call_payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "step": _ACTIVE_STEP_NAME.get(),
        "tier": model_tier,
        "model": model_name,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
    }
    _log_call(log_path, call_payload)
    active_list = _ACTIVE_USAGE_LIST.get()
    if active_list is not None:
        active_list.append(call_payload)

    return LLMCallResult(
        content=raw_text,
        parsed=parsed,
        model=model_name,
        tier=model_tier,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )
