"""Multi-voice audio: narrator + each character in their own voice, with word timestamps.

Every line is synthesised separately, then stitched with short gaps. The word timings
drive captions (coloured per speaker) and the exact length of every video shot.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from . import cast
from .common import env, http, log, media_duration, run_ffmpeg

FLITE_VOICES = ["slt", "rms", "awb", "kal"]  # mock voices


def flatten_lines(script: dict) -> list[dict]:
    out = []
    for si, shot in enumerate(script["shots"]):
        for ln in shot["lines"]:
            if ln["text"].strip():
                out.append({"shot": si, "speaker": ln["speaker"], "text": ln["text"].strip()})
    return out


def words_from_chars(chars, starts, ends, offset: float, speaker: str) -> list[dict]:
    words, cur, s, e = [], "", None, None
    for c, a, b in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append({"w": cur, "start": round(s + offset, 3), "end": round(e + offset, 3), "speaker": speaker})
            cur, s = "", None
            continue
        if s is None:
            s = a
        cur += c
        e = b
    if cur:
        words.append({"w": cur, "start": round(s + offset, 3), "end": round(e + offset, 3), "speaker": speaker})
    return words


def estimate_alignment(text: str, duration: float):
    lead, tail = 0.08, 0.12
    step = max(duration - lead - tail, 0.3) / max(len(text), 1)
    starts = [lead + i * step for i in range(len(text))]
    return list(text), starts, [t + step for t in starts]


# ---------------------------------------------------------------- per-line synthesis
def _voice_for(cfg: dict, speaker: str) -> str:
    if speaker == "narrator":
        return cfg["voices"]["narrator"]
    return cast.Character(cfg, speaker).voice_id()


def tts_line(cfg: dict, speaker: str, text: str, out_wav: Path) -> tuple[list, list, list]:
    t = cfg["tts"]
    r = http(
        "POST", f"https://api.elevenlabs.io/v1/text-to-speech/{_voice_for(cfg, speaker)}/with-timestamps",
        headers={"xi-api-key": env("ELEVENLABS_API_KEY"), "Content-Type": "application/json"},
        params={"output_format": "mp3_44100_128"},
        json={"text": text, "model_id": t["model_id"],
              "voice_settings": {"stability": t["stability"], "similarity_boost": t["similarity_boost"], "style": t.get("style", 0)}},
        timeout=300,
    )
    data = r.json()
    mp3 = out_wav.with_suffix(".mp3")
    mp3.write_bytes(base64.b64decode(data["audio_base64"]))
    run_ffmpeg(["-i", str(mp3), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)])
    mp3.unlink()
    a = data["alignment"]
    return a["characters"], a["character_start_times_seconds"], a["character_end_times_seconds"]


def _edge_voice(cfg: dict, speaker: str) -> dict:
    voices = cfg["edge_voices"]
    if speaker == "narrator":
        return voices["narrator"]
    ch = cast.Character(cfg, speaker)
    if ch.data.get("edge_voice"):                       # per-character override
        v = ch.data["edge_voice"]
        return v if isinstance(v, dict) else {"voice": v}
    return voices.get(ch.data.get("voice_type", ""), voices["narrator"])


FEMALE_TYPES = {"woman", "old_woman", "girl", "boy"}   # 'boy' uses a pitched-down young female voice
_edge_catalog: dict[str, dict] | None = None
_swapped: dict[str, str] = {}


def _edge_available() -> dict[str, dict]:
    """ShortName -> voice info from Microsoft's live list (empty if it can't be fetched)."""
    global _edge_catalog
    if _edge_catalog is None:
        import asyncio
        import edge_tts
        try:
            _edge_catalog = {v["ShortName"]: v for v in asyncio.run(edge_tts.list_voices())}
        except Exception as e:
            log.warning("Could not fetch the Edge voice list (%s); voice names are not checked.", e)
            _edge_catalog = {}
    return _edge_catalog


def _checked_voice(cfg: dict, speaker: str, name: str) -> str:
    """Edge answers 'No audio was received' for a voice it doesn't have. Swap such a
    voice for a real one with the same language and gender, and say so once."""
    voices = _edge_available()
    if not voices or name in voices:
        return name
    if name not in _swapped:
        vtype = "narrator" if speaker == "narrator" else cast.Character(cfg, speaker).data.get("voice_type", "")
        gender = "Female" if vtype in FEMALE_TYPES else "Male"
        locale = "-".join(name.split("-")[:2])
        pick = (next((v for v, i in voices.items() if i.get("Locale") == locale and i.get("Gender") == gender), None)
                or next((v for v, i in voices.items() if i.get("Locale") == locale), None)
                or next((v for v, i in voices.items() if i.get("Locale", "").startswith(locale[:2]) and i.get("Gender") == gender), None)
                or "en-US-EmmaMultilingualNeural")
        log.warning("Edge has no voice '%s' (used for %s); using '%s' instead. "
                    "Fix it in config.yaml > edge_voices or the character's edge_voice "
                    "(list voices: python run.py voices --lang %s)", name, speaker, pick, locale)
        _swapped[name] = pick
    return _swapped[name]


def _norm(t: str) -> str:
    return "".join(ch for ch in t.lower() if ch.isalnum())


def _attach_punctuation(text: str, words: list[tuple[str, float, float]]) -> tuple[list, list, list]:
    """Edge word events drop punctuation and may split hyphenated words; map them back
    onto the original tokens so captions show the real text."""
    tokens = text.split()
    out: list[list] = []          # [token, start, end]
    ti = 0
    for w, s, e in words:
        nw = _norm(w)
        if not nw:
            continue
        hit = next((k for k in range(ti, min(ti + 4, len(tokens))) if nw in _norm(tokens[k])), None)
        if hit is not None:
            out.append([tokens[hit], s, e])
            ti = hit + 1
        elif out and nw in _norm(out[-1][0]):     # second half of "ten-year-old" etc.
            out[-1][2] = e
        else:
            out.append([w, s, e])
    chars, starts, ends = [], [], []
    for tok, s, e in out:
        n = max(len(tok), 1)
        for k, c in enumerate(tok):
            chars.append(c)
            starts.append(s + (e - s) * k / n)
            ends.append(s + (e - s) * (k + 1) / n)
        chars.append(" "); starts.append(e); ends.append(e)
    return chars, starts, ends


def tts_line_edge(cfg: dict, speaker: str, text: str, out_wav: Path) -> tuple[list, list, list]:
    """Free Microsoft Edge neural voices (pip install edge-tts). Gives word timings."""
    try:
        import asyncio
        import edge_tts
    except ImportError:
        raise SystemExit("Free voices need the edge-tts package: pip install edge-tts")
    v = _edge_voice(cfg, speaker)
    name = _checked_voice(cfg, speaker, v["voice"])
    kw = {"rate": v.get("rate", "+0%"), "pitch": v.get("pitch", "+0Hz")}

    async def run():
        try:
            comm = edge_tts.Communicate(text, name, boundary="WordBoundary", **kw)
        except TypeError:          # older edge-tts versions always send word boundaries
            comm = edge_tts.Communicate(text, name, **kw)
        audio, words = bytearray(), []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append((chunk["text"], s, s + chunk["duration"] / 1e7))
        return bytes(audio), words

    for attempt in range(3):
        try:
            audio, words = asyncio.run(run())
            if audio:
                break
        except Exception as e:   # the free service occasionally drops a connection
            log.warning("Edge TTS failed (%s), retrying...", e)
    else:
        raise RuntimeError(f"Edge TTS failed for line: {text[:40]}")
    mp3 = out_wav.with_suffix(".mp3")
    mp3.write_bytes(audio)
    run_ffmpeg(["-i", str(mp3), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)])
    mp3.unlink()
    if not words:
        return estimate_alignment(text, media_duration(out_wav))
    return _attach_punctuation(text, words)


def tts_line_mock(cfg: dict, speaker: str, text: str, out_wav: Path) -> tuple[list, list, list]:
    voice = "kal16" if speaker == "narrator" else FLITE_VOICES[sum(map(ord, speaker)) % len(FLITE_VOICES)]
    txt = out_wav.with_suffix(".txt")
    txt.write_text(text, "utf-8")
    p = txt.resolve().as_posix().replace(":", "\\:")
    try:
        run_ffmpeg(["-f", "lavfi", "-i", f"flite=textfile='{p}':voice={voice}", "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)])
    except RuntimeError:
        run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{max(len(text.split()) * 0.38, 1):.2f}", "-c:a", "pcm_s16le", str(out_wav)])
    txt.unlink()
    return estimate_alignment(text, media_duration(out_wav))


# ---------------------------------------------------------------- stitch
def narrate(cfg: dict, script: dict, job_dir: Path, mock: bool = False) -> dict:
    lines = flatten_lines(script)
    tmp = job_dir / "lines"
    tmp.mkdir(exist_ok=True)
    gap = cfg["tts"]["gap_between_lines"]
    silence = tmp / "gap.wav"
    run_ffmpeg(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{gap}", "-c:a", "pcm_s16le", str(silence)])

    provider = cfg["providers"]["tts"]
    fn = tts_line_mock if mock else {"edge": tts_line_edge, "elevenlabs": tts_line}.get(provider)
    if fn is None:
        raise SystemExit(f"Unknown providers.tts '{provider}' (use edge or elevenlabs)")
    words, line_times, playlist, t = [], [], [], 0.0
    for i, ln in enumerate(lines):
        wav = tmp / f"line{i:03d}.wav"
        chars, st, en = fn(cfg, ln["speaker"], ln["text"], wav)
        dur = media_duration(wav)
        words += words_from_chars(chars, st, en, t, ln["speaker"])
        line_times.append({**ln, "start": round(t, 3), "end": round(t + dur, 3)})
        playlist += [wav, silence]
        t += dur + gap

    lst = tmp / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in playlist), "utf-8")
    audio = job_dir / "voice.wav"
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "pcm_s16le", str(audio)])
    total = media_duration(audio)

    # each shot starts with its first line; ends where the next shot starts
    starts = []
    for si in range(len(script["shots"])):
        first = next((l for l in line_times if l["shot"] == si), None)
        starts.append(first["start"] if first else (starts[-1] if starts else 0.0))
    starts[0] = 0.0
    shots = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else total
        shots.append({"start": s, "end": round(e, 3), "duration": round(e - s, 3)})

    timing = {"duration": total, "words": words, "lines": line_times, "shots": shots}
    (job_dir / "timing.json").write_text(json.dumps(timing, indent=2, ensure_ascii=False), "utf-8")
    speakers = sorted({l["speaker"] for l in lines})
    log.debug("Voices: %.1fs, %d lines, speakers: %s", total, len(lines), ", ".join(speakers))
    return timing
