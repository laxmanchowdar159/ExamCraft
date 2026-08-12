"""
core/ai_text.py
Calls Gemini to generate the exam paper text.

WHY THIS FILE EXISTS (the old code took ~3 minutes):
The previous implementation tried every model (4-5 of them) on every
configured API key (up to 3), via LangChain *and* a raw REST fallback
for each combo, one attempt after another, each with a 180-second
timeout. Worst case that is ~20-30 sequential HTTP calls before
giving up. Even the common case — primary model briefly rate-limited
— meant waiting out a full attempt before moving on.

This version:
  1. Talks to the REST API directly (no LangChain — it added an
     import-time cost and duplicated every failure into a second
     identical REST call).
  2. Fires a small batch of (model, key) attempts CONCURRENTLY and
     takes the first success, instead of waiting for each to fail
     in turn.
  3. Gives every attempt a short, fixed timeout instead of 180s, and
     enforces one overall wall-clock budget for the whole call
     (core.config.BUDGET_TEXT_SECONDS).
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from core.config import ACTIVE_KEYS, GEMINI_MODELS, GEMINI_API_BASE, BUDGET_TEXT_SECONDS

_SYSTEM_MSG = (
    "You are an expert Indian school exam paper setter with 20 years of experience. "
    "You follow instructions with military precision. "
    "Output ONLY the exam paper and answer key — no preamble, "
    "no commentary, no markdown fences. "
    "Start directly with the paper content."
)

# Per-attempt HTTP timeout. Generous enough for a real generation,
# short enough that a stuck request doesn't eat the whole budget.
_ATTEMPT_TIMEOUT = 20


def _is_429(status, body_text):
    return status == 429 or "RESOURCE_EXHAUSTED" in body_text or "quota" in body_text.lower()


def _is_dead_model(status):
    return status in (400, 404)


def _call_one(model_name: str, api_key: str, prompt: str):
    """
    Single REST call to Gemini. Returns (text, status_kind) where
    status_kind is one of: 'ok', 'rate_limited', 'dead_model', 'error'.
    """
    is_gemma = "gemma" in model_name.lower()
    payload = {
        "contents": [{"parts": [{"text": _SYSTEM_MSG + "\n\n" + prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192 if is_gemma else 32768,
            "topP": 0.9 if is_gemma else 0.85,
            "topK": 40,
        },
    }
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent?key={api_key}"
    try:
        resp = requests.post(url, json=payload, timeout=_ATTEMPT_TIMEOUT)
    except requests.RequestException as e:
        return None, "error", str(e)

    if resp.status_code == 200:
        data = resp.json()
        candidates = data.get("candidates", [{}])
        candidate = candidates[0] if candidates else {}
        finish_reason = candidate.get("finishReason", "")
        text = (candidate.get("content", {})
                         .get("parts", [{}])[0]
                         .get("text", "")).strip()
        if finish_reason == "MAX_TOKENS":
            return None, "error", f"truncated at {len(text)} chars"
        if text:
            return text, "ok", None
        return None, "error", "empty response"

    body = resp.text[:200]
    if _is_429(resp.status_code, body):
        return None, "rate_limited", body
    if _is_dead_model(resp.status_code):
        return None, "dead_model", body
    return None, "error", f"HTTP {resp.status_code}: {body}"


def generate_paper_text(prompt: str):
    """
    Race a bounded set of (model, key) attempts in parallel and take
    the first success. Returns (text, model_used, error_summary).
    """
    if not ACTIVE_KEYS:
        return None, None, "No GEMINI_API_KEY configured."

    # Build the candidate queue: best model first, each on every key.
    candidates = [(m, k) for m in GEMINI_MODELS for k in ACTIVE_KEYS]

    deadline = time.monotonic() + BUDGET_TEXT_SECONDS
    errors = {}
    dead_models = set()

    # Launch in small waves so we're not hammering every model/key
    # combo at once (stays polite to per-key rate limits) while still
    # getting real parallelism across the first few candidates.
    wave_size = min(4, len(candidates))
    idx = 0
    with ThreadPoolExecutor(max_workers=wave_size) as ex:
        while idx < len(candidates) and time.monotonic() < deadline:
            wave = []
            while len(wave) < wave_size and idx < len(candidates):
                model_name, api_key = candidates[idx]
                idx += 1
                if model_name in dead_models:
                    continue
                wave.append((model_name, api_key))
            if not wave:
                continue

            remaining = max(1, deadline - time.monotonic())
            futures = {
                ex.submit(_call_one, model_name, api_key, prompt): (model_name, api_key)
                for model_name, api_key in wave
            }
            try:
                for future in as_completed(futures, timeout=min(_ATTEMPT_TIMEOUT, remaining)):
                    model_name, api_key = futures[future]
                    text, kind, detail = future.result()
                    if kind == "ok":
                        return text, model_name, None
                    if kind == "dead_model":
                        dead_models.add(model_name)
                    errors[f"{model_name}"] = detail
            except TimeoutError:
                pass  # wave didn't finish in time — move to next wave / give up at deadline

    summary = " | ".join(f"{k}={v}" for k, v in errors.items()) or "No response within time budget."
    return None, None, summary
