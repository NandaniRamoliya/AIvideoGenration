"""Text generation backends.

  gemini  — Google Gemini API free tier (no card). Key: GEMINI_API_KEY from aistudio.google.com
  claude  — Anthropic Claude API (paid)

Note: Google may use free-tier prompts to improve its products. Fine for story scripts.
"""
from __future__ import annotations

from .common import env, http


def chat(cfg: dict, system: str, prompt: str, want_json: bool = True) -> str:
    provider = cfg["providers"]["llm"]
    if provider == "gemini":
        return _gemini(cfg, system, prompt, want_json)
    if provider == "claude":
        return _claude(cfg, system, prompt)
    raise SystemExit(f"Unknown providers.llm '{provider}' (use gemini or claude)")


def _gemini(cfg: dict, system: str, prompt: str, want_json: bool) -> str:
    c = cfg["llm"]["gemini"]
    gen = {"temperature": c.get("temperature", 1.0), "maxOutputTokens": c.get("max_tokens", 8000)}
    if want_json:
        gen["responseMimeType"] = "application/json"
    r = http(
        "POST", f"https://generativelanguage.googleapis.com/v1beta/models/{c['model']}:generateContent",
        headers={"x-goog-api-key": env("GEMINI_API_KEY"), "Content-Type": "application/json"},
        json={
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen,
        },
        timeout=180,
    )
    data = r.json()
    try:
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise RuntimeError(f"Gemini returned no text: {str(data)[:400]}")


def _claude(cfg: dict, system: str, prompt: str) -> str:
    c = cfg["llm"]["claude"]
    r = http(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": c["model"], "max_tokens": c["max_tokens"], "system": system,
              "messages": [{"role": "user", "content": prompt}]},
    )
    return "".join(b.get("text", "") for b in r.json()["content"])
