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

    fn = tts_line_mock if mock else tts_line
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
    log.info("Voices: %.1fs, %d lines, speakers: %s", total, len(lines), ", ".join(speakers))
    return timing
