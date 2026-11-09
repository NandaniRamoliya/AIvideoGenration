#!/usr/bin/env python3
"""
AI Character Story Shorts (₹0 by default) — characters → episode script → voices → consistent AI shots → edit → review → publish.

  python run.py make --series grandma-tales      next episode of a series (recurring cast + memory)
  python run.py make --count 3                   3 stand-alone stories with freshly invented characters
  python run.py make --genre "sci-fi" --idea "a robot who is afraid of the dark"
  python run.py ideas --series space-cadets      brainstorm episode ideas

  python run.py cast list                        all characters + whether their reference sheet exists
  python run.py cast new --name "Meera" --look "..." --voice-type girl
  python run.py cast redesign kabir              regenerate a character's reference images
  python run.py series list                      series, cast and episode count
  python run.py voices                           list voices in your ElevenLabs account

  python run.py finish <id>                      (free mode) build the video after you added images/clips
  python run.py pack <id>                        (free mode) refresh the FLOW_PACK.html checklist

  python run.py list | approve <id> | reject <id> | redo <id> --shots 2,5 | resume <id>
  python run.py publish <id> | publish --approved [--at "2026-11-10 18:30"] | auth-youtube

Add --mock to make/redo/resume/cast to test free: robot voices + storyboard frames, no API keys.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime

from pipeline import assemble, cast, flowpack, visuals, voice, writer
from pipeline.common import Job, load_config, log, setup_logging


# ---------------------------------------------------------------- pipeline
def manual_mode(cfg: dict, mock: bool) -> bool:
    return cfg["providers"]["visuals"] == "manual" and not mock


def prepare_cast(cfg: dict, script: dict, style: str, job: Job, mock: bool) -> None:
    """Register new characters and make sure everyone has a reference sheet."""
    for spec in script["cast"]:
        ch = cast.Character(cfg, spec["id"])
        if not ch.exists:
            if not spec.get("look"):
                raise RuntimeError(f"Character '{spec['id']}' isn't in characters/ and the script gave no look for it")
            ch = cast.register(cfg, {**spec, "style": style})
        if manual_mode(cfg, mock):
            continue     # in free mode you design characters on Flow (the pack tells you how)
        placeholder = (ch.dir / ".mock").exists() and not mock
        if not ch.has_refs or placeholder:
            log.info("Designing %s ...", ch.name)
            cast.build_refs(cfg, ch, ch.data.get("style") or style, mock=mock)
            if not mock:
                job.add_cost(2 * cfg["images"]["price_per_image"])


def produce(cfg: dict, job: Job, mock: bool, genre: str | None = None, idea: str | None = None, series_id: str | None = None) -> bool:
    """Runs every stage that hasn't finished yet for this job (safe to re-run).
    Returns False when the job is waiting for you to add visuals (free mode)."""
    try:
        series_id = series_id or job.data.get("series")
        series = writer.get_series(cfg, series_id)
        style = writer.style_for(cfg, series)
        sp = job.path("script.json")
        if sp.exists():
            script = json.loads(sp.read_text("utf-8"))
        else:
            g = writer.pick_genre(cfg, genre, series)
            if mock:
                from pipeline.mock import MOCK_SCRIPT
                script = json.loads(json.dumps(MOCK_SCRIPT))
            else:
                script = writer.write_story(cfg, g, idea, series)
            script["genre"] = script.get("genre") or g
            sp.write_text(json.dumps(script, indent=2, ensure_ascii=False), "utf-8")
            job.set(title=script["title"], genre=script["genre"], series=series_id)

        prepare_cast(cfg, script, style, job, mock)

        tp = job.path("timing.json")
        timing = json.loads(tp.read_text("utf-8")) if tp.exists() else voice.narrate(cfg, script, job.dir, mock=mock)

        if manual_mode(cfg, mock):
            flowpack.ingest_characters(cfg, job)
            clips, missing = flowpack.build_clips(cfg, job, script, timing)
            pack = flowpack.write_pack(cfg, job, script, timing, style)
            if missing:
                job.set(status="needs_visuals", missing=missing, error=None)
                log.info("⏸ %s needs visuals for shot(s) %s", job.id, missing)
                log.info("   1. open  %s", pack)
                log.info("   2. save images/clips into  %s", flowpack.inbox(job))
                log.info("   3. run   python run.py finish %s", job.id)
                return False
        else:
            clips = visuals.make_all_shots(cfg, job, script, timing, style, mock=mock)
        assemble.render(cfg, job, clips, timing, script)
        job.set(status="rendered", mock=mock, error=None)
        if not mock and not job.data.get("remembered"):
            writer.add_history(cfg, {"title": script["title"], "genre": script["genre"], "job": job.id, "series": series_id})
            if series_id:
                writer.add_series_memory(cfg, series_id, script)
            job.set(remembered=True)
        log.info("✔ %s ready for review → %s  (est. cost $%.2f)", job.id, job.path("final.mp4"), job.data.get("cost_usd", 0))
        return True
    except Exception as e:
        job.set(status="failed", error=str(e))
        log.error("✘ %s failed: %s", job.id, e)
        raise


# ---------------------------------------------------------------- commands
def cmd_make(cfg, a):
    ok = waiting = 0
    for n in range(a.count):
        log.info("──── Video %d/%d ────", n + 1, a.count)
        job = Job.create(cfg)
        try:
            ok += 1 if produce(cfg, job, a.mock, a.genre, a.idea, a.series) else 0
            waiting += 0 if job.data.get("status") != "needs_visuals" else 1
        except Exception:
            if a.count == 1:
                return 1
    if waiting:
        log.info("Done: %d script(s) + voices ready, waiting for your visuals. Open each FLOW_PACK.html (python run.py list).", waiting)
    else:
        log.info("Done: %d/%d videos in the review queue. Next: python run.py list", ok, a.count)
    return 0


def cmd_resume(cfg, a):
    job = Job.load(cfg, a.id)
    produce(cfg, job, a.mock)


def cmd_redo(cfg, a):
    job = Job.load(cfg, a.id)
    script = json.loads(job.path("script.json").read_text("utf-8"))
    idx = [int(s) - 1 for s in a.shots.split(",")]
    media = flowpack.find_media(job, len(script["shots"])) if job.path("inbox").exists() else {}
    for i in idx:
        for name in (f"shot{i:02d}_clip.mp4", f"shot{i:02d}_key.png"):
            job.path(name).unlink(missing_ok=True)
        if i in media and manual_mode(cfg, a.mock):
            redo_dir = job.path("inbox") / "_replaced"
            redo_dir.mkdir(exist_ok=True)
            media[i].rename(redo_dir / media[i].name)      # kept, not deleted
        script["shots"][i].pop("image_url", None)
        if a.prompt:
            script["shots"][i]["image_prompt"] = a.prompt
    job.path("script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), "utf-8")
    job.set(status="draft")
    produce(cfg, job, a.mock)


def cmd_list(cfg, a):
    jobs = Job.all(cfg)
    if not jobs:
        print("No videos yet. Run: python run.py make --mock")
        return
    print(f"{'ID':<22} {'STATUS':<10} {'COST':>6}  {'GENRE':<22} TITLE")
    for j in jobs:
        d = j.data
        if a.status and d.get("status") != a.status:
            continue
        print(f"{d['id']:<22} {d.get('status', ''):<10} ${d.get('cost_usd', 0):>5.2f}  {d.get('genre', '')[:22]:<22} {d.get('title', '')}")
        if d.get("status") == "rendered":
            print(f"{'':<22} ↳ watch: {j.path('final.mp4')}")
        if d.get("status") == "needs_visuals":
            print(f"{'':<22} ↳ missing shots {d.get('missing')} · open {j.path('FLOW_PACK.html')}")
            print(f"{'':<22} ↳ drop files in {j.path('inbox')} then: python run.py finish {d['id']}")
        if d.get("youtube_url"):
            print(f"{'':<22} ↳ {d['youtube_url']}")


def cmd_review(cfg, a, status):
    job = Job.load(cfg, a.id)
    if status == "approved" and job.data.get("status") != "rendered":
        raise SystemExit(f"Only rendered videos can be approved (this one is '{job.data.get('status')}').")
    if status == "approved" and job.data.get("mock"):
        raise SystemExit("This is a --mock test video; make a real one before approving.")
    job.set(status=status, reviewed=datetime.now().isoformat(timespec="seconds"), review_note=getattr(a, "note", None))
    log.info("%s → %s", job.id, status)


def cmd_publish(cfg, a):
    from pipeline import youtube
    if not cfg["publish"]["youtube"]["enabled"]:
        raise SystemExit("YouTube publishing is disabled in config.yaml")
    jobs = [j for j in Job.all(cfg) if j.data.get("status") == "approved"] if a.approved else [Job.load(cfg, a.id)]
    if not jobs:
        print("Nothing approved yet. Approve with: python run.py approve <id>")
        return
    when = datetime.fromisoformat(a.at).astimezone() if a.at else None
    for j in jobs:
        if j.data.get("status") != "approved":
            log.warning("Skipping %s: status is '%s', approve it first.", j.id, j.data.get("status"))
            continue
        script = json.loads(j.path("script.json").read_text("utf-8"))
        url = youtube.upload(cfg, j, script, when)
        j.set(status="published", youtube_url=url, published=datetime.now().isoformat(timespec="seconds"))


def cmd_ideas(cfg, a):
    series = writer.get_series(cfg, a.series)
    genre = writer.pick_genre(cfg, a.genre, series)
    print(f"\n{genre.upper()}" + (f"  —  {series['name']}" if series else ""))
    for i, idea in enumerate(writer.brainstorm(cfg, genre, a.n, series), 1):
        print(f"{i:>2}. {idea}")
    extra = f' --series {series["id"]}' if series else ""
    print(f'\nUse one: python run.py make{extra} --genre "{genre}" --idea "..."')


def cmd_cast(cfg, a):
    if a.action == "list":
        chars = cast.load_all(cfg)
        print(f"{'ID':<16} {'NAME':<14} {'VOICE':<16} {'REFS':<5} LOOK")
        for c in chars:
            print(f"{c.id:<16} {c.name:<14} {(c.data.get('voice_type') or 'custom'):<16} {'yes' if c.has_refs else 'no':<5} {c.look[:70]}")
        print(f"\nReference images live in characters/<id>/front.png and side.png")
    elif a.action == "new":
        if not (a.name and a.look):
            raise SystemExit('cast new needs --name and --look')
        ch = cast.register(cfg, {"name": a.name, "look": a.look, "personality": a.personality or "", "voice_type": a.voice_type or "narrator"})
        cast.build_refs(cfg, ch, cfg["visual_style"], mock=a.mock)
        print(f"Created {ch.name}: {ch.front}  {ch.side}")
    elif a.action == "redesign":
        ch = cast.Character(cfg, a.id)
        if not ch.exists:
            raise SystemExit(f"No character '{a.id}'. Run: python run.py cast list")
        for p in (ch.front, ch.side):
            p.unlink(missing_ok=True)
        ch.data.pop("_urls", None)
        ch.save()
        cast.build_refs(cfg, ch, ch.data.get("style") or cfg["visual_style"], mock=a.mock)
        print(f"New reference images for {ch.name} in {ch.dir}")


def cmd_series(cfg, a):
    for s in cfg.get("series") or []:
        eps = writer.series_memory(cfg, s["id"])
        print(f"{s['id']:<16} {s['name']}  —  {len(eps)} episode(s)")
        print(f"{'':<16} cast: {', '.join(s['cast'])}   genres: {', '.join(s['genres'])}")
        for e in eps[-3:]:
            print(f"{'':<16}   ep{e['episode']}: {e['title']}")


def cmd_voices(cfg, a):
    if cfg["providers"]["tts"] == "edge":
        import asyncio
        try:
            import edge_tts
        except ImportError:
            raise SystemExit("pip install edge-tts")
        voices = asyncio.run(edge_tts.list_voices())
        lang = (a.lang or "").lower()
        for v in voices:
            if lang and not v["ShortName"].lower().startswith(lang):
                continue
            print(f"{v['ShortName']:<34} {v['Gender']:<7} {v.get('Locale', '')}")
        print("\nUse a name in config.yaml > edge_voices, or per character: edge_voice: \"en-IN-NeerjaNeural\"")
        print("Filter by language: python run.py voices --lang hi-IN   (gu-IN, en-IN, en-US ...)")
        return
    from pipeline.common import env, http
    r = http("GET", "https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": env("ELEVENLABS_API_KEY")})
    for v in r.json().get("voices", []):
        labels = ", ".join(f"{k}:{val}" for k, val in (v.get("labels") or {}).items())
        print(f"{v['voice_id']}  {v['name']:<22} {labels}")
    print("\nPaste IDs into config.yaml > voices, or into characters/<id>/character.yaml > voice_id")


def cmd_pack(cfg, a):
    job = Job.load(cfg, a.id)
    script = json.loads(job.path("script.json").read_text("utf-8"))
    timing = json.loads(job.path("timing.json").read_text("utf-8"))
    style = writer.style_for(cfg, writer.get_series(cfg, job.data.get("series")))
    flowpack.ingest_characters(cfg, job)
    print(flowpack.write_pack(cfg, job, script, timing, style))


def cmd_clean(cfg, a):
    """Delete working files of published/rejected jobs, keeping final.mp4 + metadata."""
    for j in Job.all(cfg):
        if j.data.get("status") in ("published", "rejected"):
            for p in j.dir.glob("shot*"):
                p.unlink()
            if j.data["status"] == "rejected" and a.rejected:
                shutil.rmtree(j.dir)
    log.info("Cleaned up.")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--config", default=None, help="alternate config file (default: config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make"); m.add_argument("--series"); m.add_argument("--count", type=int, default=1); m.add_argument("--genre"); m.add_argument("--idea"); m.add_argument("--mock", action="store_true")
    r = sub.add_parser("resume"); r.add_argument("id"); r.add_argument("--mock", action="store_true")
    rd = sub.add_parser("redo"); rd.add_argument("id"); rd.add_argument("--shots", required=True, help="e.g. 2,5"); rd.add_argument("--prompt", help="new image prompt for these shots"); rd.add_argument("--mock", action="store_true")
    ls = sub.add_parser("list"); ls.add_argument("--status")
    ap = sub.add_parser("approve"); ap.add_argument("id")
    rj = sub.add_parser("reject"); rj.add_argument("id"); rj.add_argument("--note")
    pb = sub.add_parser("publish"); pb.add_argument("id", nargs="?"); pb.add_argument("--approved", action="store_true"); pb.add_argument("--at", help='schedule, e.g. "2026-11-10 18:30"')
    idp = sub.add_parser("ideas"); idp.add_argument("--series"); idp.add_argument("--genre"); idp.add_argument("-n", type=int, default=10)
    cl = sub.add_parser("clean"); cl.add_argument("--rejected", action="store_true", help="also delete rejected jobs")
    cs = sub.add_parser("cast"); cs.add_argument("action", choices=["list", "new", "redesign"]); cs.add_argument("id", nargs="?")
    cs.add_argument("--name"); cs.add_argument("--look"); cs.add_argument("--personality"); cs.add_argument("--voice-type"); cs.add_argument("--mock", action="store_true")
    sr = sub.add_parser("series"); sr.add_argument("action", choices=["list"])
    vc = sub.add_parser("voices"); vc.add_argument("--lang")
    fi = sub.add_parser("finish"); fi.add_argument("id")
    pk = sub.add_parser("pack"); pk.add_argument("id")
    sub.add_parser("auth-youtube")

    a = p.parse_args(argv)
    setup_logging(a.verbose)
    cfg = load_config(a.config) if a.config else load_config()

    if a.cmd == "publish" and not (a.id or a.approved):
        p.error("publish needs a job id or --approved")

    handlers = {
        "make": cmd_make, "resume": cmd_resume, "redo": cmd_redo, "list": cmd_list,
        "approve": lambda c, x: cmd_review(c, x, "approved"), "reject": lambda c, x: cmd_review(c, x, "rejected"),
        "publish": cmd_publish, "ideas": cmd_ideas, "clean": cmd_clean,
        "cast": cmd_cast, "series": cmd_series, "voices": cmd_voices, "pack": cmd_pack,
        "finish": lambda c, x: produce(c, Job.load(c, x.id), False) and 0,
        "auth-youtube": lambda c, x: __import__("pipeline.youtube", fromlist=["authorize"]).authorize(c),
    }
    return handlers[a.cmd](cfg, a) or 0


if __name__ == "__main__":
    sys.exit(main())
