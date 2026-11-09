"""Phase 8 (segments): cut every shot to its voice timing and join them.
Phase 9 (final): burn in captions, mix voice + music, loudness, export the 9:16 MP4."""
from __future__ import annotations

import random
from pathlib import Path

from .common import Job, rel, run_ffmpeg


def _filter_path(p: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument (works on Windows too)."""
    return "'" + p.resolve().as_posix().replace(":", r"\:").replace("'", r"\'") + "'"


def fit_segments(cfg: dict, job: Job, clips: list[Path], timing: dict) -> Path:
    r = cfg["render"]
    W, H, fps = r["width"], r["height"], r["fps"]
    segs = []
    for i, (clip, shot) in enumerate(zip(clips, timing["shots"])):
        frames = round(shot["end"] * fps) - round(shot["start"] * fps)
        dur = frames / fps
        seg = job.path(f"seg{i:02d}.mp4")
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},"
              f"tpad=stop_mode=clone:stop_duration={dur + 1:.2f},setpts=PTS-STARTPTS,format=yuv420p")
        run_ffmpeg(["-i", str(clip), "-vf", vf, "-frames:v", str(frames), "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-r", str(fps), str(seg)])
        segs.append(seg)
    lst = job.path("segments.txt")
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), "utf-8")
    visuals = job.path("visuals.mp4")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(visuals)])
    for seg in segs:
        seg.unlink(missing_ok=True)
    lst.unlink(missing_ok=True)
    return visuals


def pick_music(cfg: dict) -> Path | None:
    d = rel(cfg["render"]["music_dir"])
    tracks = [p for p in d.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a")] if d.exists() else []
    return random.choice(tracks) if tracks else None


def render_final(cfg: dict, job: Job, timing: dict, script: dict) -> tuple[Path, str | None]:
    """Needs visuals.mp4 (segments), captions.ass (captions) and voice.wav (voices).
    Returns (final.mp4, music track name or None)."""
    r = cfg["render"]
    visuals, ass = job.path("visuals.mp4"), job.path("captions.ass")

    fonts = rel(r["fonts_dir"])
    sub = f"subtitles={_filter_path(ass)}" + (f":fontsdir={_filter_path(fonts)}" if fonts.exists() else "")
    inputs = ["-i", str(visuals), "-i", str(job.path("voice.wav"))]
    music = pick_music(cfg)
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        audio = (f"[1:a]aresample=44100,asplit=2[vo][sc];"
                 f"[2:a]aresample=44100,volume={r['music_volume']}[m];"
                 f"[m][sc]sidechaincompress=threshold=0.04:ratio=6:attack=15:release=350[duck];"
                 f"[vo][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        audio = "[1:a]aresample=44100,loudnorm=I=-14:TP=-1.5:LRA=11[a]"

    final = job.path("final.mp4")
    run_ffmpeg([
        *inputs,
        "-filter_complex", f"[0:v]{sub}[v];{audio}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(r["crf"]), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-t", f"{timing['duration']:.3f}", str(final),
    ])

    # thumbnail + post kit for manual Instagram / TikTok upload
    run_ffmpeg(["-ss", "1.2", "-i", str(final), "-frames:v", "1", "-q:v", "3", str(job.path("thumbnail.jpg"))])
    yt = script.get("youtube", {})
    job.path("post_kit.txt").write_text(
        f"YOUTUBE TITLE\n{yt.get('title', '')}\n\nYOUTUBE DESCRIPTION\n{yt.get('description', '')}\n\n"
        f"TAGS\n{', '.join(yt.get('tags', []))}\n\nINSTAGRAM / TIKTOK CAPTION\n{script.get('social_caption', '')}\n\n"
        f"REMINDER: turn on the platform's 'AI-generated content' label when posting.\n", "utf-8")
    return final, (music.name if music else None)
