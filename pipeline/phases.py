"""The video pipeline as 9 phases. Each phase has its own output files, is skipped when
they already exist, and can be redone on its own (python run.py run <id> --phase <name>).

  1 idea        premise for the episode (idea bank)       idea.json
  2 story       script, dialogue, shot list (Gemini)      script.json
  3 voices      every line spoken (Edge TTS)              voice.wav, timing.json
  4 characters  character designs, ONCE per character     characters/<id>/front.png
  5 scenes      one image or clip per shot                inbox/01.png, 02.mp4 ...
  6 motion      camera motion on stills, clips fitted     shotNN_clip.mp4
  7 captions    word-by-word captions, names, hook card   captions.ass
  8 segments    shots cut to the voice timing, joined     visuals.mp4
  9 final       captions + voice + music, 9:16 MP4        final.mp4, thumbnail.jpg, post_kit.txt

Voices come before the pictures because each shot's length comes from its lines, so the
pipeline stops for you only once (characters + scenes, in free 'manual' mode).
"""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from typing import Callable

from . import assemble, captions, cast, flowpack, llm, visuals, voice, writer
from .common import Job, log, media_duration


class Waiting(Exception):
    """A phase needs something from you (images, clips) before it can finish."""


@dataclass
class Ctx:
    cfg: dict
    job: Job
    mock: bool = False
    genre: str | None = None
    idea: str | None = None

    @property
    def series(self) -> dict | None:
        return writer.get_series(self.cfg, self.job.data.get("series"))

    @property
    def style(self) -> str:
        return writer.style_for(self.cfg, self.series)

    @property
    def manual(self) -> bool:
        return self.cfg["providers"]["visuals"] == "manual" and not self.mock

    def load(self, name: str):
        p = self.job.path(name)
        return json.loads(p.read_text("utf-8")) if p.exists() else None

    @property
    def script(self) -> dict | None:
        return self.load("script.json")

    @property
    def timing(self) -> dict | None:
        return self.load("timing.json")

    def shots(self) -> int:
        s = self.script
        return len(s["shots"]) if s else 0

    def cast(self) -> list[cast.Character]:
        s = self.script
        return [cast.Character(self.cfg, c["id"]) for c in s["cast"]] if s else []

    def pack(self) -> None:
        flowpack.write_pack(self.cfg, self.job, self.script, self.timing, self.style)


def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def _short(text: str, n: int = 60) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------- 1 idea
def idea_done(c: Ctx) -> bool:
    return c.job.path("idea.json").exists() or c.job.path("script.json").exists()


def idea_run(c: Ctx) -> str:
    series = c.series
    genre = writer.pick_genre(c.cfg, c.genre, series)
    if c.idea:
        idea, source = c.idea, "your idea"
    elif c.mock:
        from .mock import MOCK_SCRIPT
        idea, source = MOCK_SCRIPT["logline"], "mock"
    else:
        idea, left = writer.take_idea(c.cfg, genre, series)
        source = f"idea bank, {left} left"
    c.job.path("idea.json").write_text(json.dumps({"genre": genre, "idea": idea, "source": source},
                                                  indent=2, ensure_ascii=False), "utf-8")
    c.job.set(genre=genre)
    return f'"{_short(idea)}"  ({genre} · {source})'


# ---------------------------------------------------------------- 2 story
def story_done(c: Ctx) -> bool:
    return c.job.path("script.json").exists()


def story_run(c: Ctx) -> str:
    meta = c.load("idea.json") or {}
    genre = meta.get("genre") or writer.pick_genre(c.cfg, c.genre, c.series)
    if c.mock:
        from .mock import MOCK_SCRIPT
        script = json.loads(json.dumps(MOCK_SCRIPT))
    else:
        script = writer.write_story(c.cfg, genre, meta.get("idea"), c.series)
    script["genre"] = script.get("genre") or genre
    for spec in script["cast"]:                       # new characters join the library
        if not cast.Character(c.cfg, spec["id"]).exists:
            if not spec.get("look"):
                raise RuntimeError(f"Character '{spec['id']}' isn't in characters/ and the script gave no look for it")
            cast.register(c.cfg, {**spec, "style": c.style})
    c.job.path("script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), "utf-8")
    c.job.set(title=script["title"], genre=script["genre"])
    words = sum(len(ln["text"].split()) for s in script["shots"] for ln in s["lines"])
    model = "mock" if c.mock else (llm.last_model or c.cfg["providers"]["llm"])
    return f'"{_short(script["title"], 40)}" · {len(script["shots"])} shots · {words} words · {model}'


# ---------------------------------------------------------------- 3 voices
def voices_done(c: Ctx) -> bool:
    return c.job.path("timing.json").exists() and c.job.path("voice.wav").exists()


def voices_run(c: Ctx) -> str:
    t = voice.narrate(c.cfg, c.script, c.job.dir, mock=c.mock)
    speakers = sorted({ln["speaker"] for ln in t["lines"]})
    return f"{t['duration']:.1f} s · {len(t['lines'])} lines · {', '.join(speakers)}"


# ---------------------------------------------------------------- 4 characters
def chars_missing(c: Ctx) -> list[cast.Character]:
    """Characters without a saved design (mock placeholder cards don't count in real runs)."""
    return [ch for ch in c.cast() if not ch.has_refs or ((ch.dir / ".mock").exists() and not c.mock)]


def chars_done(c: Ctx) -> bool:
    # scenes made without saved designs are fine too: the video only needs the scenes
    return c.script is not None and (not chars_missing(c) or scenes_done(c))


def chars_run(c: Ctx) -> str:
    before = {ch.id for ch in chars_missing(c)}
    if c.manual:
        flowpack.ingest_characters(c.cfg, c.job)
        c.pack()
        missing = chars_missing(c)
        if missing and not scenes_done(c):
            raise Waiting("make once, save as " + ", ".join(f"inbox/char_{ch.id}.png" for ch in missing))
        if missing:
            return "skipped: scenes were made without saved designs"
    else:
        for ch in chars_missing(c):
            log.info("  designing %s ...", ch.name)
            cast.build_refs(c.cfg, ch, ch.data.get("style") or c.style, mock=c.mock)
            if not c.mock:
                c.job.add_cost(2 * c.cfg["images"]["price_per_image"])
    names = [ch.name for ch in c.cast()]
    new = [ch.name for ch in c.cast() if ch.id in before]
    reused = [n for n in names if n not in new]
    return " · ".join(p for p in (f"new: {', '.join(new)}" if new else "",
                                  f"reused: {', '.join(reused)}" if reused else "") if p) or "no characters"


# ---------------------------------------------------------------- 5 scenes
def scenes_done(c: Ctx) -> bool:
    n = c.shots()
    return n > 0 and len(flowpack.find_media(c.job, n)) == n


def scenes_progress(c: Ctx) -> tuple[int, int, list[int]]:
    n = c.shots()
    media = flowpack.find_media(c.job, n) if n else {}
    return len(media), n, [i + 1 for i in range(n) if i not in media]


def scenes_run(c: Ctx) -> str:
    have, n, missing = scenes_progress(c)
    if missing and not c.manual:
        visuals.fill_inbox(c.cfg, c.job, c.script, c.timing, c.style, mock=c.mock, missing=[m - 1 for m in missing])
    if c.manual:
        c.pack()
    have, n, missing = scenes_progress(c)
    if missing:
        c.job.set(missing=missing)
        raise Waiting(f"{have}/{n} shots ready · missing " + ", ".join(f"{m:02d}" for m in missing))
    media = flowpack.find_media(c.job, n)
    clips = sum(1 for p in media.values() if p.suffix.lower() in flowpack.VID_EXT)
    c.job.set(missing=[])
    return f"{n}/{n} shots · {_n(n - clips, 'image')} · {_n(clips, 'clip')}"


# ---------------------------------------------------------------- 6 motion
def motion_done(c: Ctx) -> bool:
    n = c.shots()
    return n > 0 and all(c.job.path(f"shot{i:02d}_clip.mp4").exists() for i in range(n))


def motion_run(c: Ctx) -> str:
    clips, stills = flowpack.make_motion(c.cfg, c.job, c.script, c.timing)
    return f"{_n(stills, 'still')} got camera motion · {_n(clips, 'clip')} fitted"


# ---------------------------------------------------------------- 7 captions
def captions_done(c: Ctx) -> bool:
    return c.job.path("captions.ass").exists()


def captions_run(c: Ctx) -> str:
    t, s = c.timing, c.script
    captions.build_ass(c.cfg, t, s.get("hook_text"), c.job.path("captions.ass"))
    tags = sum(1 for ln in t["lines"] if ln["speaker"] != "narrator")
    return f"{len(t['words'])} words timed · {_n(tags, 'name tag')} · hook: \"{_short(s.get('hook_text') or '-', 30)}\""


# ---------------------------------------------------------------- 8 segments
def segments_done(c: Ctx) -> bool:
    return c.job.path("visuals.mp4").exists()


def segments_run(c: Ctx) -> str:
    n = c.shots()
    clips = [c.job.path(f"shot{i:02d}_clip.mp4") for i in range(n)]
    out = assemble.fit_segments(c.cfg, c.job, clips, c.timing)
    return f"{n} segments joined · {media_duration(out):.1f} s"


# ---------------------------------------------------------------- 9 final
def final_done(c: Ctx) -> bool:
    return c.job.path("final.mp4").exists()


def final_run(c: Ctx) -> str:
    final, music = assemble.render_final(c.cfg, c.job, c.timing, c.script)
    mb = final.stat().st_size / 1e6
    return f"final.mp4 · {media_duration(final):.1f} s · {mb:.1f} MB · music: {music or 'none'}"


# ---------------------------------------------------------------- registry
@dataclass
class Phase:
    name: str
    title: str
    run: Callable[[Ctx], str]
    done: Callable[[Ctx], bool]
    outputs: tuple[str, ...] = ()       # removed when the phase is redone (globs in the job folder)
    you: bool = False                   # needs you in free mode


PHASES = [
    Phase("idea", "premise for the episode", idea_run, idea_done, ("idea.json",)),
    Phase("story", "script, dialogue, shot list", story_run, story_done, ("script.json",)),
    Phase("voices", "every line in its own voice", voices_run, voices_done, ("voice.wav", "timing.json", "lines")),
    Phase("characters", "character designs (once per character)", chars_run, chars_done, (), you=True),
    Phase("scenes", "one picture or clip per shot", scenes_run, scenes_done, (), you=True),
    Phase("motion", "camera motion on stills, clips fitted", motion_run, motion_done, ("shot*_clip.mp4",)),
    Phase("captions", "word-by-word captions + name tags", captions_run, captions_done, ("captions.ass",)),
    Phase("segments", "shots cut to the voices and joined", segments_run, segments_done, ("visuals.mp4",)),
    Phase("final", "captions + voice + music → final.mp4", final_run, final_done,
          ("final.mp4", "thumbnail.jpg", "post_kit.txt")),
]
NAMES = [p.name for p in PHASES]


def _tag(i: int) -> str:
    return f"[{i + 1}/{len(PHASES)}] {PHASES[i].name:<10}"


def summary(c: Ctx, p: "Phase") -> str:
    """Short description of a finished phase, worked out from its files."""
    try:
        if p.name == "idea":
            meta = c.load("idea.json")
            return f'"{_short(meta["idea"])}"  ({meta["genre"]})' if meta else "(made before phases existed)"
        if p.name == "story":
            s = c.script
            words = sum(len(ln["text"].split()) for sh in s["shots"] for ln in sh["lines"])
            return f'"{_short(s["title"], 40)}" · {len(s["shots"])} shots · {words} words'
        if p.name == "voices":
            t = c.timing
            return f"{t['duration']:.1f} s · {len(t['lines'])} lines"
        if p.name == "characters":
            return "saved: " + ", ".join(ch.name for ch in c.cast() if ch.has_refs)
        if p.name == "scenes":
            n = c.shots()
            clips = sum(1 for f in flowpack.find_media(c.job, n).values() if f.suffix.lower() in flowpack.VID_EXT)
            return f"{n}/{n} shots · {_n(n - clips, 'image')} · {_n(clips, 'clip')}"
    except Exception:
        pass
    return ""


def _record(job: Job, name: str, **kw) -> None:
    phases = job.data.get("phases", {})
    phases[name] = {**kw, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    job.set(phases=phases)


def clear_from(c: Ctx, name: str) -> None:
    """Delete the outputs of phase `name` and every later phase, so they run again.
    Your own files (inbox, character designs) are never deleted."""
    phases = c.job.data.get("phases", {})
    for p in PHASES[NAMES.index(name):]:
        for pattern in p.outputs:
            for f in c.job.dir.glob(pattern):
                shutil.rmtree(f) if f.is_dir() else f.unlink()
        phases.pop(p.name, None)
    c.job.set(phases=phases, status="draft")


def run(c: Ctx, start: str | None = None, only: bool = False) -> str:
    """Run phases in order from `start` (default: the first one not done yet).
    Returns 'done' (final.mp4 made, or the one phase with only=True), or 'waiting'."""
    job = c.job
    first = NAMES.index(start) if start else 0
    skipped = []
    for i in range(first, len(PHASES)):
        p = PHASES[i]
        forced = start is not None and i == first
        if not forced and p.done(c):
            skipped.append(p.name)
            if job.data.get("phases", {}).get(p.name, {}).get("status") != "done":
                _record(job, p.name, status="done", note=summary(c, p))      # e.g. scenes you just finished
            continue
        if skipped:
            log.info("· already done: %s", ", ".join(skipped))
            skipped = []
        job.set(phase=p.name)
        log.info("▶ %s %s ...", _tag(i), p.title)
        t0 = time.monotonic()
        try:
            note = p.run(c)
        except Waiting as w:
            _record(job, p.name, status="waiting", note=str(w))
            job.set(status="needs_visuals", error=None)
            log.info("⏸ %s waiting for you: %s", _tag(i), w)
            return "waiting"
        except (Exception, SystemExit) as e:          # SystemExit: e.g. a missing API key
            _record(job, p.name, status="failed", error=str(e))
            job.set(status="failed", error=str(e))
            log.error("✘ %s failed: %s", _tag(i), e)
            raise
        secs = time.monotonic() - t0
        _record(job, p.name, status="done", seconds=round(secs, 1), note=note)
        log.info("✔ %s %6.1fs  %s", _tag(i), secs, note)
        if only:
            job.set(status="rendered" if final_done(c) else "draft")
            return "done"
    if skipped:
        log.info("· already done: %s", ", ".join(skipped))
    if job.data.get("status") not in ("approved", "published", "rejected"):
        job.set(status="rendered", phase="final", error=None, mock=c.mock)
    if not c.mock and not job.data.get("remembered"):
        script = c.script
        writer.add_history(c.cfg, {"title": script["title"], "genre": script["genre"], "job": job.id,
                                   "series": job.data.get("series")})
        if job.data.get("series"):
            writer.add_series_memory(c.cfg, job.data["series"], script)
        job.set(remembered=True)
    return "done"


# ---------------------------------------------------------------- tracking
def position(c: Ctx) -> tuple[int, str]:
    """(phases done, current phase name) for the list view."""
    if final_done(c):
        return len(PHASES), "final"
    for i, p in enumerate(PHASES):
        if not p.done(c):
            return i, p.name
    return len(PHASES), "final"


def _live_note(c: Ctx, p: Phase) -> str:
    if p.name == "characters":
        missing = chars_missing(c)
        return "need: " + ", ".join(f"char_{ch.id}.png" for ch in missing) if missing else ""
    if p.name == "scenes":
        have, n, missing = scenes_progress(c)
        return f"{have}/{n} shots" + (" · missing " + ", ".join(f"{m:02d}" for m in missing) if missing else "")
    return ""


def table(c: Ctx) -> str:
    job, rec = c.job, c.job.data.get("phases", {})
    title = job.data.get("title") or "(no story yet)"
    rows = [f"\n  {title}   {job.id}" + ("   [mock]" if job.data.get("mock") else "")]
    finished = final_done(c)
    blocked = False                     # once a phase is open, later ones are just pending
    for i, p in enumerate(PHASES):
        r = rec.get(p.name, {})
        if r.get("status") == "failed" and not p.done(c):
            mark, word, secs, note = "✘", "failed", "", _short(r.get("error", ""), 70)
            blocked = True
        elif (p.done(c) or finished) and not blocked:
            mark, word = "✔", "done"
            fresh = r.get("status") == "done"
            secs = f"{r['seconds']:>5.1f}s" if fresh and r.get("seconds") is not None else ""
            note = r.get("note", "") if fresh and r.get("note") else summary(c, p)
        elif p.you and c.manual and not blocked and c.script:
            mark, word, secs, note = "⏸", "waiting", "", _live_note(c, p)
            blocked = p.name == "scenes"
        else:
            mark, word, secs, note = "·", "pending", "", ""
            blocked = True
        rows.append(f"  {i + 1} {p.name:<11}{mark} {word:<8}{secs:>7}  {note}")
    rows.append("  Next → " + next_hint(c))
    return "\n".join(rows) + "\n"


def next_hint(c: Ctx) -> str:
    job = c.job
    st = job.data.get("status")
    if final_done(c):
        if st == "rendered":
            return f"watch {job.path('final.mp4')}  then: python run.py approve {job.id}"
        return f"status: {st}"
    if st == "failed":
        return f"fix the error above, then: python run.py next {job.id}"
    done, name = position(c)
    if c.manual and name in ("characters", "scenes"):
        return (f"open {job.path('FLOW_PACK.html')}, save the files into {flowpack.inbox(job)}, "
                f"then: python run.py next {job.id}")
    return f"python run.py next {job.id}"
