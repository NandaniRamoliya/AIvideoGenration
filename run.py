#!/usr/bin/env python3
"""
AI Character Story Shorts (₹0 by default). Every video goes through 9 phases:

  1 idea · 2 story · 3 voices · 4 characters · 5 scenes · 6 motion · 7 captions · 8 segments · 9 final

  python run.py make --series grandma-tales      new episode: runs the phases until it needs your pictures
  python run.py make --count 3                   3 stand-alone stories
  python run.py make --genre "sci-fi" --idea "a robot who is afraid of the dark"
  python run.py status [id]                      phase-by-phase progress of a video (default: the latest)
  python run.py next <id>                        continue a video from where it stopped
  python run.py run <id> --phase voices          redo one phase (and the ones after it); --only for just that one
  python run.py list                             all videos and the phase each one is on

  python run.py pack <id>                        refresh FLOW_PACK.html (✓ marks) while you add pictures
  python run.py redo <id> --shots 2,5            put shots 2 and 5 aside so you can make new pictures
  python run.py ideas --series space-cadets      brainstorm episode ideas
  python run.py cast list | cast new ... | series list | voices --lang en-IN
  python run.py approve <id> | reject <id> | publish --approved [--at "2026-11-10 18:30"] | auth-youtube

  finish / resume are kept as other names for 'next'.
Add --mock to make: robot voices + storyboard pictures, no API keys, nothing to make by hand.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime

from pipeline import cast, flowpack, phases, writer
from pipeline.common import Job, load_config, log, setup_logging


# ---------------------------------------------------------------- pipeline
def ctx_for(cfg: dict, job: Job, **kw) -> phases.Ctx:
    return phases.Ctx(cfg, job, mock=bool(job.data.get("mock")), **kw)


def drive(c: phases.Ctx, **kw) -> str:
    """Run phases, then print the phase table. Returns 'done', 'waiting' or 'failed'."""
    log.info("──── %s ────", c.job.id)
    try:
        result = phases.run(c, **kw)
    except (Exception, SystemExit):           # already logged + recorded by the phase runner
        result = "failed"
    print(phases.table(c))
    return result


def latest_job(cfg: dict) -> Job:
    jobs = Job.all(cfg)
    if not jobs:
        raise SystemExit("No videos yet. Run: python run.py make --mock")
    return jobs[-1]


# ---------------------------------------------------------------- commands
def cmd_make(cfg, a):
    results = []
    for n in range(a.count):
        if a.count > 1:
            log.info("════ Video %d/%d ════", n + 1, a.count)
        job = Job.create(cfg)
        writer.get_series(cfg, a.series)            # fails early on a wrong --series
        job.set(series=a.series, mock=a.mock)
        results.append(drive(ctx_for(cfg, job, genre=a.genre, idea=a.idea)))
    if a.count > 1:
        log.info("Done: %d finished · %d waiting for your pictures · %d failed",
                 results.count("done"), results.count("waiting"), results.count("failed"))
    return 1 if results.count("failed") == len(results) else 0


def cmd_next(cfg, a):
    return 1 if drive(ctx_for(cfg, Job.load(cfg, a.id))) == "failed" else 0


def cmd_status(cfg, a):
    job = Job.load(cfg, a.id) if a.id else latest_job(cfg)
    print(phases.table(ctx_for(cfg, job)))


def cmd_run(cfg, a):
    job = Job.load(cfg, a.id)
    c = ctx_for(cfg, job)
    if a.only:                                    # redo just this phase: clear only its own outputs
        for pattern in phases.PHASES[phases.NAMES.index(a.phase)].outputs:
            for f in job.dir.glob(pattern):
                shutil.rmtree(f) if f.is_dir() else f.unlink()
    else:
        phases.clear_from(c, a.phase)
    log.info("Redoing %s%s", a.phase, "" if a.only else " and the phases after it")
    return 1 if drive(c, start=a.phase, only=a.only) == "failed" else 0


def cmd_redo(cfg, a):
    """Put the pictures of some shots aside (kept in inbox/_replaced) and redo from 'scenes'."""
    job = Job.load(cfg, a.id)
    c = ctx_for(cfg, job)
    script = c.script
    idx = [int(x) - 1 for x in a.shots.split(",")]
    media = flowpack.find_media(job, len(script["shots"]))
    for i in idx:
        if i in media:
            aside = job.path("inbox") / "_replaced"
            aside.mkdir(exist_ok=True)
            media[i].replace(aside / media[i].name)
        script["shots"][i].pop("image_url", None)
        if a.prompt:
            script["shots"][i]["image_prompt"] = a.prompt
    job.path("script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False), "utf-8")
    phases.clear_from(c, "motion")
    log.info("Shot(s) %s put aside; make new pictures for them.", a.shots)
    return 1 if drive(c) == "failed" else 0


def cmd_list(cfg, a):
    jobs = Job.all(cfg)
    if not jobs:
        print("No videos yet. Run: python run.py make --mock")
        return
    print(f"{'ID':<21} {'PHASE':<15} {'STATUS':<15} {'GENRE':<20} TITLE")
    for j in jobs:
        d = j.data
        if a.status and d.get("status") != a.status:
            continue
        done, name = phases.position(ctx_for(cfg, j))
        mark = {"rendered": "✔", "approved": "✔", "published": "✔", "failed": "✘", "needs_visuals": "⏸"}.get(d.get("status"), "·")
        print(f"{d['id']:<21} {done}/{len(phases.PHASES)} {name:<11} {mark} {d.get('status', ''):<13} "
              f"{d.get('genre', '')[:20]:<20} {d.get('title', '')}{'  [mock]' if d.get('mock') else ''}")
    print("\nDetails of one video: python run.py status <id>")


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
    for name in ("next", "finish", "resume"):
        sub.add_parser(name).add_argument("id")
    st = sub.add_parser("status"); st.add_argument("id", nargs="?")
    rn = sub.add_parser("run"); rn.add_argument("id"); rn.add_argument("--phase", required=True, choices=phases.NAMES); rn.add_argument("--only", action="store_true", help="redo just this phase")
    rd = sub.add_parser("redo"); rd.add_argument("id"); rd.add_argument("--shots", required=True, help="e.g. 2,5"); rd.add_argument("--prompt", help="new image prompt for these shots")
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
    pk = sub.add_parser("pack"); pk.add_argument("id")
    sub.add_parser("auth-youtube")

    a = p.parse_args(argv)
    setup_logging(a.verbose)
    cfg = load_config(a.config) if a.config else load_config()

    if a.cmd == "publish" and not (a.id or a.approved):
        p.error("publish needs a job id or --approved")

    handlers = {
        "make": cmd_make, "next": cmd_next, "finish": cmd_next, "resume": cmd_next,
        "status": cmd_status, "run": cmd_run, "redo": cmd_redo, "list": cmd_list,
        "approve": lambda c, x: cmd_review(c, x, "approved"), "reject": lambda c, x: cmd_review(c, x, "rejected"),
        "publish": cmd_publish, "ideas": cmd_ideas, "clean": cmd_clean,
        "cast": cmd_cast, "series": cmd_series, "voices": cmd_voices, "pack": cmd_pack,
        "auth-youtube": lambda c, x: __import__("pipeline.youtube", fromlist=["authorize"]).authorize(c),
    }
    return handlers[a.cmd](cfg, a) or 0


if __name__ == "__main__":
    sys.exit(main())
