"""Text generation backends.

  gemini  — Google Gemini API free tier (no card). Key: GEMINI_API_KEY from aistudio.google.com
  claude  — Anthropic Claude API (paid)

Note: Google may use free-tier prompts to improve its products. Fine for story scripts.
"""
from __future__ import annotations

import requests

from .common import APIError, env, http, log


def chat(cfg: dict, system: str, prompt: str, want_json: bool = True) -> str:
    provider = cfg["providers"]["llm"]
    if provider == "gemini":
        return _gemini(cfg, system, prompt, want_json)
    if provider == "claude":
        return _claude(cfg, system, prompt)
    raise SystemExit(f"Unknown providers.llm '{provider}' (use gemini or claude)")


def _gemini(cfg: dict, system: str, prompt: str, want_json: bool) -> str:
    """Free-tier models get busy (503) or retired (404) without notice, so try the
    configured model first and fall back to the others instead of waiting on one."""
    c = cfg["llm"]["gemini"]
    gen = {"temperature": c.get("temperature", 1.0), "maxOutputTokens": c.get("max_tokens", 8000)}
    if want_json:
        gen["responseMimeType"] = "application/json"
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
    }
    key = env("GEMINI_API_KEY")
    models = [c["model"]] + [m for m in c.get("fallback_models") or [] if m != c["model"]]
    errors = []
    for model in models:
        try:
            r = http(
                "POST", f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                json=body, timeout=c.get("timeout", 120), retries=1,
            )
        except APIError as e:
            if " (404)" not in str(e):          # bad key / bad request: another model won't help
                raise
            errors.append(f"{model}: not available")
        except requests.RequestException as e:   # 429 / 5xx / timeout after retries
            errors.append(f"{model}: {str(e).splitlines()[0][:80]}")
        else:
            data = r.json()
            try:
                text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
            except (KeyError, IndexError):
                errors.append(f"{model}: no text ({str(data)[:200]})")
                continue
            if model != models[0]:
                log.info("Gemini: used fallback model %s", model)
            return text
        log.warning("Gemini %s unavailable, trying the next model ...", model)
    raise RuntimeError("All Gemini models failed. Try again in a few minutes or change llm.gemini in config.yaml:\n  "
                       + "\n  ".join(errors))


def _claude(cfg: dict, system: str, prompt: str) -> str:
    c = cfg["llm"]["claude"]
    r = http(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": c["model"], "max_tokens": c["max_tokens"], "system": system,
              "messages": [{"role": "user", "content": prompt}]},
    )
    return "".join(b.get("text", "") for b in r.json()["content"])
