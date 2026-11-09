"""Idea → character-driven script: cast, dialogue lines, shot list. Remembers past episodes."""
from __future__ import annotations

import json
import random
import re

from . import cast, llm
from .common import log, rel


def _schema(cfg: dict) -> str:
    voice_types = ", ".join(k for k in cfg["voices"] if k != "narrator")
    return f"""{{
  "title": "short title",
  "logline": "one-sentence premise",
  "hook_text": "3-6 word on-screen hook for the first seconds",
  "setting": "where and when the story happens (visual description, reused in every shot)",
  "cast": [
    {{"id": "existing-character-id"}},
    {{"id": "new-id", "new": true, "name": "Name", "look": "FIXED visual description: age, face, skin, hair, body, exact outfit and colours, one signature prop", "personality": "3-6 words", "voice_type": "one of: {voice_types}"}}
  ],
  "shots": [
    {{
      "lines": [
        {{"speaker": "narrator", "text": "narration"}},
        {{"speaker": "character-id", "text": "what the character says out loud"}}
      ],
      "characters": ["ids of characters VISIBLE in this shot, max 3"],
      "image_prompt": "the keyframe: who is where, doing what, facial expressions, camera angle (close-up / wide / over-the-shoulder), lighting. Refer to characters by name.",
      "motion_prompt": "one sentence: camera movement + what the characters physically do in the clip (e.g. 'Dadi leans in and whispers while the lamp flickers, slow push in')"
    }}
  ],
  "episode_summary": "2 sentences: what happened + anything future episodes should remember",
  "youtube": {{"title": "<=70 chars, curiosity-driven", "description": "2-3 lines + 3-5 hashtags incl. #shorts", "tags": ["5-10 tags"]}},
  "social_caption": "caption for Instagram Reels / TikTok with 4-6 hashtags"
}}"""


def _llm(cfg: dict, system: str, prompt: str) -> str:
    return llm.chat(cfg, system, prompt)


def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Writer did not return JSON")
    return json.loads(m.group(0))


# ---------------------------------------------------------------- memory
def load_history(cfg: dict) -> list[dict]:
    p = rel(cfg["paths"]["history_file"])
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def add_history(cfg: dict, entry: dict) -> None:
    p = rel(cfg["paths"]["history_file"])
    p.parent.mkdir(parents=True, exist_ok=True)
    hist = load_history(cfg) + [entry]
    p.write_text(json.dumps(hist[-500:], indent=2, ensure_ascii=False), "utf-8")


def series_memory(cfg: dict, series_id: str) -> list[dict]:
    p = rel(cfg["paths"]["series_memory_dir"]) / f"{series_id}.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else []


def add_series_memory(cfg: dict, series_id: str, script: dict) -> None:
    p = rel(cfg["paths"]["series_memory_dir"]) / f"{series_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    mem = series_memory(cfg, series_id)
    mem.append({"episode": len(mem) + 1, "title": script["title"], "summary": script.get("episode_summary", script.get("logline", ""))})
    p.write_text(json.dumps(mem, indent=2, ensure_ascii=False), "utf-8")


def get_series(cfg: dict, series_id: str | None) -> dict | None:
    if not series_id:
        return None
    for s in cfg.get("series") or []:
        if s["id"] == series_id:
            return s
    raise SystemExit(f"No series '{series_id}' in config.yaml. Available: {[s['id'] for s in cfg.get('series') or []]}")


def pick_genre(cfg: dict, forced: str | None = None, series: dict | None = None) -> str:
    if forced:
        return forced
    if series:
        return random.choice(series["genres"])
    genres = cfg["genres"]
    recent = [h.get("genre") for h in load_history(cfg)[-3:]]
    pool = [g for g in genres if g["name"] not in recent] or genres
    return random.choices([g["name"] for g in pool], weights=[g["weight"] for g in pool])[0]


def style_for(cfg: dict, series: dict | None) -> str:
    return (series or {}).get("visual_style") or cfg["visual_style"]


# ---------------------------------------------------------------- writing
def system_prompt(cfg: dict) -> str:
    ch, st = cfg["channel"], cfg["story"]
    rules = "\n".join(f"- {r}" for r in st["rules"])
    return (
        f"You are the head writer of '{ch['name']}', a short-form animated story channel (YouTube Shorts, Reels, TikTok) "
        f"for a {ch['audience']}. You write character-driven micro-episodes in {ch['language']}: memorable characters, "
        f"real dialogue, a clear problem, and an ending people share.\n\nRules:\n{rules}"
    )


def write_story(cfg: dict, genre: str, idea: str | None = None, series: dict | None = None) -> dict:
    st = cfg["story"]
    library = [c.summary() for c in cast.load_all(cfg)]
    recent_titles = [h["title"] for h in load_history(cfg)[-40:]]

    if series:
        memory = series_memory(cfg, series["id"])[-8:]
        cast_rule = (
            f"This is the next episode of the series '{series['name']}'. Premise: {series['premise']}\n"
            f"World: {series['world']}\n"
            f"Main cast (MUST appear, use these ids): {json.dumps([c for c in library if c['id'] in series['cast']], ensure_ascii=False)}\n"
            f"You may add at most 1 new side character.\n"
            f"Previous episodes (keep continuity, don't repeat plots): {json.dumps(memory, ensure_ascii=False) if memory else 'none yet - this is episode 1'}"
        )
    else:
        cast_rule = (
            f"This is a stand-alone story. Invent 1-{st['max_characters']} vivid characters (mark them new: true), "
            f"or reuse a fitting character from this library: {json.dumps(library, ensure_ascii=False)}"
        )

    prompt = f"""Write one new short story episode.

Genre: {genre}
{cast_rule}
{f'Idea to develop: {idea}' if idea else 'Brainstorm 5 premises silently, then use the most surprising one.'}
Avoid repeating these recent titles: {json.dumps(recent_titles, ensure_ascii=False)}

Requirements:
- Total spoken words: about {st['target_words']}; {st['dialogue_share']}.
- Dialogue lines are short and natural (max ~15 words each) and reveal personality.
- {st['min_shots']}-{st['max_shots']} shots; each shot = one visual moment a 3-10 s AI clip can show, 1-3 lines each.
- Max {st['max_characters']} characters in the whole story, max 3 visible per shot.
- 'look' descriptions must be specific and unchanging (exact outfit + colours) so the character looks identical in every shot.
- The final line (narrator or character) ends with: "{cfg['channel']['call_to_action']}" or a natural variation.

Return ONLY valid JSON in this exact shape, no prose:
{_schema(cfg)}"""

    for _ in range(3):
        try:
            data = _extract_json(_llm(cfg, system_prompt(cfg), prompt))
            validate(data)
            log.info("Story: %s  (%s, %d shots, cast: %s)", data["title"], genre, len(data["shots"]),
                     ", ".join(c.get("name", c["id"]) for c in data["cast"]))
            return data
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            log.warning("Bad script output (%s), retrying...", e)
    raise RuntimeError("Could not get a valid script from the writer")


def validate(script: dict) -> None:
    ids = {c["id"] for c in script["cast"]}
    if not script.get("shots"):
        raise ValueError("no shots")
    for i, s in enumerate(script["shots"]):
        if not s.get("lines"):
            raise ValueError(f"shot {i + 1} has no lines")
        for ln in s["lines"]:
            if ln["speaker"] != "narrator" and ln["speaker"] not in ids:
                raise ValueError(f"unknown speaker '{ln['speaker']}' in shot {i + 1}")
        s["characters"] = [c for c in s.get("characters", []) if c in ids][:3]


def brainstorm(cfg: dict, genre: str, n: int = 10, series: dict | None = None) -> list[str]:
    ctx = f" for the series '{series['name']}' ({series['premise']})" if series else ""
    text = _llm(cfg, system_prompt(cfg),
                   f"Give {n} original, scroll-stopping {genre} episode premises{ctx}. "
                   f"One line each: characters + conflict + twist. Return a JSON list of strings only.")
    m = re.search(r"\[.*\]", text, re.S)
    return json.loads(m.group(0)) if m else [text]
