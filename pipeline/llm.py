"""Text generation backends.

  gemini  — Google Gemini API free tier (no card). Key: GEMINI_API_KEY from aistudio.google.com
  claude  — Anthropic Claude API (paid)

Note: Google may use free-tier prompts to improve its products. Fine for story scripts.
"""
from __future__ import annotations

import os
import queue
import socket
import threading
import time

import requests

from .common import APIError, env, http, log

GEMINI_HOST = "generativelanguage.googleapis.com"
NO_NET = f"Can't reach Google ({GEMINI_HOST}). Check your internet / Wi-Fi / VPN and try again."


class NoInternet(RuntimeError):
    pass


_skip: dict[str, str] = {}      # model -> why it's skipped for the rest of this run


def chat(cfg: dict, system: str, prompt: str, want_json: bool = True) -> str:
    provider = cfg["providers"]["llm"]
    if provider == "gemini":
        return _gemini(cfg, system, prompt, want_json)
    if provider == "claude":
        return _claude(cfg, system, prompt)
    raise SystemExit(f"Unknown providers.llm '{provider}' (use gemini or claude)")


def _deadline(fn, seconds: float):
    """Run fn() with a hard time limit. requests' timeout covers neither the DNS lookup
    nor a reply that trickles in slowly, so one call could otherwise hang for minutes."""
    box: queue.Queue = queue.Queue(1)

    def work():
        try:
            box.put((True, fn()))
        except BaseException as e:
            box.put((False, e))

    threading.Thread(target=work, daemon=True).start()   # daemon: an abandoned call can't block exit
    try:
        ok, value = box.get(timeout=seconds)
    except queue.Empty:
        raise TimeoutError(f"no answer within {seconds:.0f}s") from None
    if ok:
        return value
    raise value


def _online() -> bool:
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return True                      # behind a proxy the proxy resolves names, not this PC
    try:
        _deadline(lambda: socket.getaddrinfo(GEMINI_HOST, 443), 5)
        return True
    except Exception:
        return False


def _ask_gemini(model: str, key: str, body: dict, limit: int):
    """One request. Returns (text, None) or (None, (reason, retry_after_seconds_or_None))."""
    url = f"https://{GEMINI_HOST}/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    try:
        r = _deadline(lambda: requests.post(url, headers=headers, json=body, timeout=(10, limit)), limit + 5)
    except (TimeoutError, requests.Timeout):
        return None, (f"no answer within {limit}s (busy or slow)", None)
    except requests.ConnectionError:
        if not _online():
            raise NoInternet(NO_NET) from None
        return None, ("connection dropped", 3)
    if r.status_code == 200:
        try:
            data = r.json()
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]), None
        except (KeyError, IndexError, ValueError):
            return None, (f"empty answer: {r.text[:150]}", None)
    if r.status_code in (401, 403):
        raise APIError(f"Gemini refused your key ({r.status_code}). Check GEMINI_API_KEY in .env: {r.text[:200]}")
    if r.status_code == 404:
        return None, ("not available to your key", None)
    if r.status_code == 429:
        if "PerDay" in r.text:
            return None, ("free daily limit used up (resets in ~24h)", None)
        return None, ("free per-minute limit hit", 20)
    if r.status_code >= 500:
        return None, (f"Google busy ({r.status_code})", 3)
    return None, (f"rejected ({r.status_code}): {r.text[:150]}", None)


def _gemini(cfg: dict, system: str, prompt: str, want_json: bool) -> str:
    """Free-tier models get busy (503), hit daily limits (429) or retire (404) without
    notice, so try the configured model first and move down the fallback list."""
    c = cfg["llm"]["gemini"]
    gen = {"temperature": c.get("temperature", 1.0), "maxOutputTokens": c.get("max_tokens", 8000)}
    if want_json:
        gen["responseMimeType"] = "application/json"
    if c.get("thinking_level"):
        gen["thinkingConfig"] = {"thinkingLevel": c["thinking_level"]}
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
    }
    key = env("GEMINI_API_KEY")
    limit = int(c.get("timeout", 150))
    models = [c["model"]] + [m for m in c.get("fallback_models") or [] if m != c["model"]]
    if not _online():
        raise NoInternet(NO_NET)

    errors = []
    for n, model in enumerate(models):
        if model in _skip:                   # used up / too slow earlier in this run: don't wait on it again
            errors.append(f"{model}: {_skip[model]}")
            continue
        for attempt in (1, 2):
            text, fail = _ask_gemini(model, key, body, limit)
            if text is not None:
                if n:
                    log.info("Gemini: used fallback model %s", model)
                return text
            reason, retry_in = fail
            if attempt == 1 and retry_in:
                log.warning("Gemini %s: %s, retrying in %ds ...", model, reason, retry_in)
                time.sleep(retry_in)
                continue
            break
        if retry_in is None:
            _skip[model] = reason
        errors.append(f"{model}: {reason}")
        if n + 1 < len(models):
            log.warning("Gemini %s: %s, trying %s ...", model, reason, models[n + 1])
    raise RuntimeError("No Gemini model could answer:\n  " + "\n  ".join(errors) +
                       "\nWait a few minutes (or until tomorrow if the daily limits are used up).")


def _claude(cfg: dict, system: str, prompt: str) -> str:
    c = cfg["llm"]["claude"]
    r = http(
        "POST", "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": c["model"], "max_tokens": c["max_tokens"], "system": system,
              "messages": [{"role": "user", "content": prompt}]},
    )
    return "".join(b.get("text", "") for b in r.json()["content"])
