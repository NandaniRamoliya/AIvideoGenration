"""₹0 visuals: a 'Flow pack' page with every prompt, a drop folder, and animated stills.

You make the pictures/clips on any free website (Google Flow, Gemini app, Luma, Kling...),
save them into   output/jobs/<id>/inbox/   and run   python run.py next <id>.

File names in the inbox:
    01.png / 01.jpg / 01.webp   still image for shot 1  → animated with camera motion
    01.mp4 / 01.mov / 01.webm   video clip for shot 1   → used as-is (preferred if both exist)
    char_dadi.png               reference image for character 'dadi' (first time only)
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
from pathlib import Path

from . import cast
from .common import Job, log, run_ffmpeg
from .visuals import clip_seconds, speakers_in_shot

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
VID_EXT = (".mp4", ".mov", ".webm", ".mkv")


# ---------------------------------------------------------------- inbox
def inbox(job: Job) -> Path:
    p = job.path("inbox")
    p.mkdir(exist_ok=True)
    return p


def ingest_characters(cfg: dict, job: Job) -> list[str]:
    """Move char_<id>.* files from the inbox into the character library."""
    done = []
    for f in inbox(job).iterdir():
        m = re.match(r"char[_-]([a-z0-9_-]+)\.", f.name.lower())     # ids like cloud_sprite
        if not m or f.suffix.lower() not in IMG_EXT:
            continue
        ch = cast.Character(cfg, m.group(1))
        if not ch.exists:
            log.warning("Ignoring %s: no character '%s' in this story", f.name, m.group(1))
            continue
        run_ffmpeg(["-i", str(f), str(ch.front)])
        if not ch.side.exists():
            shutil.copy(ch.front, ch.side)
        (ch.dir / ".mock").unlink(missing_ok=True)
        f.unlink()
        done.append(ch.name)
    if done:
        log.info("Saved character references: %s", ", ".join(done))
    return done


def find_media(job: Job, n: int) -> dict[int, Path]:
    """Shot index (0-based) → best media file in the inbox. Clips win over stills."""
    found: dict[int, Path] = {}
    for f in sorted(inbox(job).iterdir()):
        ext = f.suffix.lower()
        if ext not in IMG_EXT + VID_EXT or f.name.lower().startswith("char"):
            continue
        m = re.search(r"\d+", f.stem)
        if not m:
            continue
        i = int(m.group(0)) - 1
        if not 0 <= i < n:
            continue
        if i not in found or (ext in VID_EXT and found[i].suffix.lower() not in VID_EXT):
            found[i] = f
    return found


# ---------------------------------------------------------------- stills → motion
MOTIONS = [
    # (zoom expr, x expr, y expr) — 'on' = output frame, D = total frames
    ("1+0.14*on/D", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),                  # slow push in
    ("1.14-0.14*on/D", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),               # pull out
    ("1.15", "(iw-iw/zoom)*on/D", "ih/2-(ih/zoom/2)"),                        # pan right
    ("1+0.10*on/D", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/D)"),             # push in + tilt up
    ("1.15", "(iw-iw/zoom)*(1-on/D)", "ih/2-(ih/zoom/2)"),                    # pan left
    ("1+0.12*on/D", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*0.35"),                 # push in on faces (upper third)
]


def animate_still(cfg: dict, img: Path, seconds: float, idx: int, out: Path) -> Path:
    r = cfg["render"]
    W, H, fps = r["width"], r["height"], r["fps"]
    frames = max(int(round(seconds * fps)), 1)
    z, x, y = MOTIONS[idx % len(MOTIONS)]
    z, x, y = (e.replace("D", str(frames)) for e in (z, x, y))
    vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"   # 2x = smooth motion
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={fps},format=yuv420p")
    run_ffmpeg(["-i", str(img), "-vf", vf, "-frames:v", str(frames),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)])
    return out


def fit_clip(src: Path, need: float, out: Path, idx: int) -> Path:
    """Use a downloaded clip; if it's shorter than the shot, slow it down (max 1.5x)
    so it doesn't freeze. Warn when it isn't vertical."""
    import subprocess
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:format=duration", "-of", "json", str(src)],
                           capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    st = info["streams"][0]
    dur = float(info["format"]["duration"])
    if st["width"] > st["height"]:
        log.warning("  shot %d: %s is landscape; it will be centre-cropped to 9:16 (choose 9:16 on the site next time)",
                    idx + 1, src.name)
    factor = min(need / dur, 1.5) if dur < need else 1.0
    if factor > 1.01:
        log.info("  shot %d: clip is %.1fs for a %.1fs shot → slowed to %.2fx", idx + 1, dur, need, factor)
        run_ffmpeg(["-i", str(src), "-vf", f"setpts={factor:.3f}*PTS", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(out)])
    else:
        shutil.copy(src, out)
    return out


def make_motion(cfg: dict, job: Job, script: dict, timing: dict) -> tuple[int, int]:
    """Motion phase: every inbox file becomes shotNN_clip.mp4 of the right length.
    Stills get a camera move; clips are fitted. Returns (AI clips, animated stills)."""
    n = len(script["shots"])
    media = find_media(job, n)
    missing = [i + 1 for i in range(n) if i not in media]
    if missing:
        raise RuntimeError(f"no picture for shot(s) {missing} in {inbox(job)}")
    clips = 0
    for i in range(n):
        src, need = media[i], timing["shots"][i]["duration"]
        out = job.path(f"shot{i:02d}_clip.mp4")
        if src.suffix.lower() in VID_EXT:
            fit_clip(src, need, out, i)
            clips += 1
        else:
            animate_still(cfg, src, need + 0.2, i, out)
    return clips, n - clips


# ---------------------------------------------------------------- the pack page
def hero_shots(script: dict, k: int) -> set[int]:
    """Which shots deserve a real video clip if you only have a few free credits."""
    n = len(script["shots"])
    score = []
    for i, s in enumerate(script["shots"]):
        sc = len(s.get("characters", [])) + sum(1 for l in s["lines"] if l["speaker"] != "narrator")
        sc += 3 if i == 0 else 0            # the hook matters most
        sc += 2 if i == n - 1 else 0        # and the payoff
        score.append((sc, -i))
    return {-i for _, i in sorted(score, reverse=True)[:k]}


def image_prompt(script: dict, shot: dict, chars: list[cast.Character], style: str) -> str:
    who = "; ".join(f"{c.name}: {c.look}" for c in chars)
    ref = (" Use the attached reference image" + ("s" if len(chars) > 1 else "") +
           " so the character" + ("s look" if len(chars) > 1 else " looks") + " exactly the same.") if chars else ""
    return (f"{shot['image_prompt']}. Setting: {script.get('setting', '')}."
            + (f" Characters — {who}." if who else "") + ref +
            f" Style: {style}. Vertical 9:16 frame, cinematic composition, expressive faces, no text, no watermark.")


def video_prompt(shot: dict, chars: list[cast.Character], style: str) -> str:
    talking = speakers_in_shot(shot, chars)
    t = f" {' and '.join(talking)} {'is' if len(talking) == 1 else 'are'} talking with natural gestures." if talking else ""
    return f"{shot['motion_prompt']}.{t} Keep characters consistent with the start image. {style}. Vertical 9:16, no text, no music, no dialogue audio."


def character_prompt(ch: cast.Character, style: str) -> str:
    return (f"Character design of {ch.name}: {ch.look}. Full body, standing, facing camera, neutral expression, "
            f"plain light-grey background, even lighting. Style: {style}. Vertical 9:16, no text.")


def _copy_block(label: str, text: str) -> str:
    t = html.escape(text)
    return (f'<div class="pr"><div class="pl">{label}<button onclick="cp(this)">Copy</button></div>'
            f'<pre>{t}</pre></div>')


def write_pack(cfg: dict, job: Job, script: dict, timing: dict, style: str) -> Path:
    n = len(script["shots"])
    media = find_media(job, n)
    heroes = hero_shots(script, cfg.get("manual", {}).get("hero_shots", 2))
    cast_ids = [c["id"] for c in script["cast"]]
    chars = {cid: cast.Character(cfg, cid) for cid in cast_ids}
    box = inbox(job)

    def rel(p: Path) -> str:
        return html.escape(os.path.relpath(p, job.dir).replace(os.sep, "/"))

    char_html = []
    for cid, ch in chars.items():
        real = ch.front.exists() and not (ch.dir / ".mock").exists()
        status = '<span class="ok">✓ saved</span>' if real else f'<span class="todo">needed → save as <b>inbox/char_{cid}.png</b></span>'
        img = f'<img src="{rel(ch.front)}">' if real else '<div class="ph">?</div>'
        char_html.append(f'<div class="card ch">{img}<div><h3>{html.escape(ch.name)} {status}</h3>'
                         f'<p class="muted">{html.escape(ch.data.get("personality", ""))}</p>'
                         f'{"" if real else _copy_block("Design prompt", character_prompt(ch, style))}</div></div>')

    shot_html = []
    for i, shot in enumerate(script["shots"]):
        sc = [chars[c] for c in shot.get("characters", []) if c in chars]
        need = timing["shots"][i]["duration"]
        have = media.get(i)
        num = f"{i + 1:02d}"
        if have:
            prev = (f'<video src="{rel(have)}" muted loop autoplay playsinline></video>' if have.suffix.lower() in VID_EXT
                    else f'<img src="{rel(have)}">')
            status = f'<span class="ok">✓ {html.escape(have.name)}</span>'
        else:
            prev, status = '<div class="ph">' + num + '</div>', f'<span class="todo">save as <b>inbox/{num}.png</b> or <b>{num}.mp4</b></span>'
        lines = "".join(f'<li><b>{html.escape(chars[l["speaker"]].name if l["speaker"] in chars else "Narrator")}:</b> '
                        f'{html.escape(l["text"])}</li>' for l in shot["lines"])
        refs = ("Attach reference: " + ", ".join(f"<b>{html.escape(c.name)}</b>" for c in sc)) if sc else "No characters in this shot."
        hero = '<span class="hero">★ make this a video clip if you have credits</span>' if i in heroes else ""
        shot_html.append(f"""<div class="card shot" id="s{num}">{prev}<div class="body">
<h3>Shot {num} <span class="muted">· {need:.1f}s</span> {hero}</h3><p>{status}</p>
<ul class="lines">{lines}</ul><p class="muted">{refs}</p>
{_copy_block("1 · Image prompt", image_prompt(script, shot, sc, style))}
{_copy_block(f"2 · Video prompt (optional, from the image, ≥ {clip_seconds(cfg, need)}s)", video_prompt(shot, sc, style))}
</div></div>""")

    done = len(media)
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flow pack · {html.escape(script['title'])}</title><style>
:root{{--bg:#f6f4ef;--card:#fff;--ink:#1d1b18;--muted:#6f6a62;--line:#e4dfd6;--ok:#1f7a4d;--todo:#b4561f;--acc:#3b4cca}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16161a;--card:#202027;--ink:#ecebe7;--muted:#9a978f;--line:#33333c;--ok:#4fc28a;--todo:#f0995a;--acc:#8d9bff}}}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}}
main{{max-width:980px;margin:auto;padding:24px 16px 80px}}h1{{margin:.2em 0;font-size:28px}}h2{{margin:32px 0 12px;font-size:19px}}
h3{{margin:0 0 4px;font-size:16px}}.muted{{color:var(--muted)}}.ok{{color:var(--ok);font-weight:600;font-size:13px}}
.todo{{color:var(--todo);font-size:13px}}.hero{{background:var(--acc);color:#fff;border-radius:99px;padding:2px 9px;font-size:12px;margin-left:6px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;display:flex;gap:16px;margin-bottom:14px}}
.card img,.card video,.ph{{width:150px;aspect-ratio:9/16;object-fit:cover;border-radius:10px;flex:none;background:var(--line)}}
.ph{{display:grid;place-items:center;font-size:28px;color:var(--muted)}}.body{{flex:1;min-width:0}}
.lines{{margin:6px 0;padding-left:18px}}.pr{{margin-top:10px;border:1px solid var(--line);border-radius:10px;overflow:hidden}}
.pl{{display:flex;justify-content:space-between;align-items:center;padding:6px 10px;font-size:12px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--line)}}
pre{{margin:0;padding:10px;white-space:pre-wrap;font:13px/1.45 ui-monospace,Consolas,monospace}}
button{{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:7px;padding:3px 10px;cursor:pointer;font-size:12px}}
.steps li{{margin:4px 0}}code{{background:var(--card);border:1px solid var(--line);border-radius:5px;padding:1px 5px}}
@media (max-width:600px){{.card{{flex-direction:column}}.card img,.card video,.ph{{width:100%;max-width:240px}}}}
</style></head><body><main>
<p class="muted">{html.escape(job.id)} · {html.escape(script.get('genre', ''))} · {n} shots · {timing['duration']:.0f}s</p>
<h1>{html.escape(script['title'])}</h1><p>{html.escape(script.get('logline', ''))}</p>
<p><b>{done}/{n}</b> shots ready.</p>
<h2>How to finish this video (free)</h2>
<p class="muted">Two kinds of pictures. <b>Character designs</b> are each character's official look: made <b>once</b>, reused in every episode.
<b>Scenes</b> are this episode's shots: made every episode, with the character designs attached so faces and outfits match.</p>
<ol class="steps">
<li>Open <b>Google Flow</b> (labs.google/fx/tools/flow) — images there don't use credits. Any free image/video site works too.</li>
<li><b>Phase 4 · Characters</b> (only if one below says <i>needed</i>): generate it with its design prompt, save into the inbox as <code>char_&lt;id&gt;.png</code>.</li>
<li><b>Phase 5 · Scenes</b>: for every shot attach the listed character designs, paste the <b>image prompt</b>, choose 9:16, save as <code>01.png</code>, <code>02.png</code>…</li>
<li>Free video credits? Turn the <b>★</b> shots into clips with the <b>video prompt</b> and save as <code>01.mp4</code>. Every still gets camera motion automatically.</li>
<li>Save everything into: <code>{html.escape(str(box))}</code> &nbsp;(check progress: <code>python run.py status {html.escape(job.id)}</code>)</li>
<li>Run <code>python run.py next {html.escape(job.id)}</code> — phases 6–9 (motion, captions, segments, final) run by themselves.</li></ol>
<h2>Phase 4 · Characters <span class="muted">(once per character)</span></h2>{''.join(char_html)}
<h2>Phase 5 · Scenes <span class="muted">(this episode)</span></h2>{''.join(shot_html)}
</main><script>
function cp(b){{const t=b.closest('.pr').querySelector('pre').innerText;
(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>{{b.textContent='Copied';setTimeout(()=>b.textContent='Copy',1200)}})
.catch(()=>{{const r=document.createRange();r.selectNodeContents(b.closest('.pr').querySelector('pre'));getSelection().removeAllRanges();getSelection().addRange(r)}})}}
</script></body></html>"""
    out = job.path("FLOW_PACK.html")
    out.write_text(page, "utf-8")
    job.path("prompts.json").write_text(json.dumps([
        {"shot": i + 1, "seconds": timing["shots"][i]["duration"],
         "image_prompt": image_prompt(script, s, [chars[c] for c in s.get("characters", []) if c in chars], style),
         "video_prompt": video_prompt(s, [chars[c] for c in s.get("characters", []) if c in chars], style)}
        for i, s in enumerate(script["shots"])], indent=2, ensure_ascii=False), "utf-8")
    return out
