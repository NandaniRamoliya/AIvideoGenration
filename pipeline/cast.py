"""Character library: every character has a fixed look, personality, voice and a reference sheet.

characters/<id>/
    character.yaml   name, look, personality, voice_type / voice_id, caption colour
    front.png        front-facing reference (generated once)
    side.png         3/4 view reference, made FROM front.png so it's the same person
"""
from __future__ import annotations

import base64
import re
import time
from pathlib import Path

import yaml

from .common import download, log, rel, run_ffmpeg

# caption highlight colours for speakers (ASS &HBBGGRR)
SPEAKER_COLOURS = ["&H0000E5FF", "&H00FFB347", "&H0066FF66", "&H00FF77FF", "&H004FA3FF", "&H00FFFF55"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "character"


class Character:
    def __init__(self, cfg: dict, cid: str):
        self.cfg = cfg
        self.id = cid
        self.dir = rel(cfg["paths"]["characters_dir"]) / cid
        f = self.dir / "character.yaml"
        self.data: dict = yaml.safe_load(f.read_text("utf-8")) if f.exists() else {"id": cid}

    # -- basic fields
    @property
    def exists(self) -> bool:
        return (self.dir / "character.yaml").exists()

    @property
    def name(self) -> str:
        return self.data.get("name", self.id)

    @property
    def look(self) -> str:
        return self.data.get("look", "")

    @property
    def front(self) -> Path:
        return self.dir / "front.png"

    @property
    def side(self) -> Path:
        return self.dir / "side.png"

    @property
    def has_refs(self) -> bool:
        return self.front.exists() and self.side.exists()

    def voice_id(self) -> str:
        if self.data.get("voice_id"):
            return self.data["voice_id"]
        voices = self.cfg["voices"]
        return voices.get(self.data.get("voice_type", ""), voices["narrator"])

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "character.yaml").write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True), "utf-8")

    def summary(self) -> dict:
        return {k: self.data.get(k) for k in ("id", "name", "look", "personality", "voice_type")}


def load_all(cfg: dict) -> list[Character]:
    root = rel(cfg["paths"]["characters_dir"])
    return [Character(cfg, p.name) for p in sorted(root.iterdir()) if (p / "character.yaml").exists()] if root.exists() else []


def assign_colour(cfg: dict) -> str:
    used = {c.data.get("caption_color") for c in load_all(cfg)}
    free = [c for c in SPEAKER_COLOURS[1:] if c not in used]
    return (free or SPEAKER_COLOURS[1:])[0]


def register(cfg: dict, spec: dict) -> Character:
    """Create (or return) a character from a writer/CLI spec: {id?, name, look, personality, voice_type}."""
    cid = spec.get("id") or slug(spec["name"])
    ch = Character(cfg, cid)
    if ch.exists:
        return ch
    ch.data = {
        "id": cid,
        "name": spec["name"],
        "look": spec["look"],
        "personality": spec.get("personality", ""),
        "voice_type": spec.get("voice_type", "narrator"),
        "voice_id": spec.get("voice_id"),
        "caption_color": assign_colour(cfg),
        "style": spec.get("style"),
    }
    ch.save()
    log.info("New character: %s (%s)", ch.name, cid)
    return ch


# ---------------------------------------------------------------- reference sheets
def file_url(path: Path) -> str:
    """URL fal.ai can read: upload via fal_client if installed, else a base64 data URI."""
    try:
        import fal_client
        return fal_client.upload_file(str(path))
    except Exception:
        small = path.with_suffix(".ref.jpg")
        if not small.exists() or small.stat().st_mtime < path.stat().st_mtime:
            run_ffmpeg(["-i", str(path), "-vf", "scale='min(1024,iw)':-2", "-q:v", "3", str(small)])
        return "data:image/jpeg;base64," + base64.b64encode(small.read_bytes()).decode()


def ref_urls(ch: Character) -> dict:
    """Cached URLs for a character's reference images (re-uploaded only when images change)."""
    cache = ch.data.get("_urls", {})
    stamp = f"{ch.front.stat().st_mtime:.0f}-{ch.side.stat().st_mtime:.0f}"
    stale = time.time() - cache.get("uploaded", 0) > 3 * 86400   # re-upload every few days
    if cache.get("stamp") != stamp or stale or cache.get("front", "").startswith("data:"):
        cache = {"stamp": stamp, "uploaded": int(time.time()), "front": file_url(ch.front), "side": file_url(ch.side)}
        if not cache["front"].startswith("data:"):
            ch.data["_urls"] = cache
            ch.save()
    return cache


def build_refs(cfg: dict, ch: Character, style: str, mock: bool = False) -> None:
    """Generate the reference sheet once. Delete front.png/side.png to redesign a character."""
    marker = ch.dir / ".mock"
    if not mock and marker.exists():          # placeholder cards from a --mock run: replace with real designs
        for p in (ch.front, ch.side, marker):
            p.unlink(missing_ok=True)
        ch.data.pop("_urls", None)
    if ch.has_refs:
        return
    ch.dir.mkdir(parents=True, exist_ok=True)
    if mock:
        _mock_card(cfg, ch)
        marker.touch()
        return

    from .visuals import fal_run   # local import avoids a cycle
    img = cfg["images"]
    if not ch.front.exists():
        prompt = (f"Character reference portrait of {ch.name}: {ch.look}. Full body, standing, facing the camera, "
                  f"neutral expression, plain light-grey studio background, even lighting. Style: {style}. No text.")
        res = fal_run(img["text_to_image"], {"prompt": prompt, "aspect_ratio": img["aspect_ratio"], "num_images": 1})
        download(res["images"][0]["url"], ch.front)
        log.info("  %s: front reference created", ch.name)
    res = fal_run(img["edit"], {
        "prompt": (f"The same character as in the image, {ch.name}, now in a three-quarter side view, upper body, "
                   f"same face, hair, outfit, colours and art style. Plain light-grey background. No text."),
        "image_urls": [file_url(ch.front)],
        "aspect_ratio": img["aspect_ratio"],
        "num_images": 1,
    })
    download(res["images"][0]["url"], ch.side)
    log.info("  %s: side reference created", ch.name)


MOCK_BG = ["0x2b4162", "0x7a2e3a", "0x2e6b4f", "0x6b4e2e", "0x4b2e6b", "0x2e5e6b"]


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def _mock_card(cfg: dict, ch: Character) -> None:
    """Placeholder reference card (name + look) so mock runs show who is who."""
    bg = MOCK_BG[sum(map(ord, ch.id)) % len(MOCK_BG)]
    look = ch.look[:150]
    lines = [look[i:i + 34] for i in range(0, len(look), 34)]
    look_txt = _esc("\n".join(lines))
    for out, label in ((ch.front, "FRONT"), (ch.side, "SIDE")):
        vf = (f"drawbox=x=340:y=380:w=400:h=560:color=white@0.25:t=fill,"
              f"drawtext=text='{_esc(ch.name.upper())}':fontcolor=white:fontsize=96:x=(w-tw)/2:y=1020,"
              f"drawtext=text='{look_txt}':fontcolor=white@0.85:fontsize=40:line_spacing=12:x=(w-tw)/2:y=1160,"
              f"drawtext=text='{label} REFERENCE (mock)':fontcolor=white@0.6:fontsize=36:x=(w-tw)/2:y=1700")
        run_ffmpeg(["-f", "lavfi", "-i", f"color=c={bg}:s=1080x1920", "-vf", vf, "-frames:v", "1", str(out)])
