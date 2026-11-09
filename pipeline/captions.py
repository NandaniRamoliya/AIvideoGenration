"""Word-by-word animated captions. Each speaker's current word glows in their own colour,
with a small name tag over character dialogue (ASS subtitles burned in by ffmpeg)."""
from __future__ import annotations

import re
from pathlib import Path

from . import cast


def _ts(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(w: str) -> str:
    return w.replace("\\", "").replace("{", "(").replace("}", ")")


def chunk_words(words: list[dict], size: int) -> list[list[dict]]:
    """1..size words per chunk; break on punctuation and whenever the speaker changes."""
    chunks, cur = [], []
    for w in words:
        if cur and w["speaker"] != cur[-1]["speaker"]:
            chunks.append(cur)
            cur = []
        cur.append(w)
        if len(cur) >= size or re.search(r"[.!?,;:—]$", w["w"]):
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def speaker_styles(cfg: dict, timing: dict) -> dict[str, tuple[str, str]]:
    out = {"narrator": (cfg["captions"]["narrator_highlight"], "")}
    for sp in {l["speaker"] for l in timing["lines"]} - {"narrator"}:
        ch = cast.Character(cfg, sp)
        out[sp] = (ch.data.get("caption_color") or cast.SPEAKER_COLOURS[1], ch.name)
    return out


def build_ass(cfg: dict, timing: dict, hook_text: str | None, out: Path) -> Path:
    c, r = cfg["captions"], cfg["render"]
    W, H = r["width"], r["height"]
    x, y = W // 2, c["position_y"]
    styles = speaker_styles(cfg, timing)
    hdr = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{c['font']},{c['size']},{c['color']},{c['color']},{c['outline_color']},&H80000000,-1,0,0,0,100,100,0,0,1,{c['outline']},3,5,70,70,0,1
Style: Name,{c['font']},{int(c['size'] * 0.52)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,2,0,3,10,0,5,60,60,0,1
Style: Hook,{c['font']},{int(c['size'] * 1.15)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,18,0,5,90,90,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    chunks = chunk_words(timing["words"], c["words_per_chunk"])
    for ci, chunk in enumerate(chunks):
        hl = styles.get(chunk[0]["speaker"], styles["narrator"])[0]
        nxt = chunks[ci + 1][0]["start"] if ci + 1 < len(chunks) else timing["duration"]
        chunk_end = min(chunk[-1]["end"] + 0.35, nxt)
        for wi, w in enumerate(chunk):
            start = w["start"]
            end = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else chunk_end
            if end <= start:
                continue
            parts = [f"{{\\c{hl}}}{_clean(ww['w']).upper()}{{\\c{c['color']}}}" if k == wi else _clean(ww["w"]).upper()
                     for k, ww in enumerate(chunk)]
            pop = "\\fscx82\\fscy82\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
            ev.append(f"Dialogue: 1,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{{\\pos({x},{y}){pop}}}{' '.join(parts)}")

    if c.get("show_speaker_name"):
        for ln in timing["lines"]:
            colour, name = styles.get(ln["speaker"], ("", ""))
            if name:
                ev.append(f"Dialogue: 2,{_ts(ln['start'])},{_ts(ln['end'] + 0.2)},Name,,0,0,0,,"
                          f"{{\\pos({x},{y - int(c['size'] * 1.05)})\\3c{colour}\\1c&H00000000&}}{_clean(name).upper()}")

    if hook_text and c.get("show_title_card"):
        ev.append(f"Dialogue: 3,{_ts(0)},{_ts(min(2.6, timing['duration']))},Hook,,0,0,0,,"
                  f"{{\\pos({x},{int(H * 0.2)})\\fad(120,250)}}{_clean(hook_text).upper()}")

    out.write_text(hdr + "\n".join(ev) + "\n", "utf-8")
    return out
