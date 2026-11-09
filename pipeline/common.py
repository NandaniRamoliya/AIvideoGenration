"""Shared helpers: config, jobs on disk, HTTP with retries, logging."""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("shorts")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(path: str | Path = ROOT / "config.yaml") -> dict:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. Add it to .env (see .env.example) or run with --mock.")
    return value


def rel(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


# ---------------------------------------------------------------- jobs
class Job:
    """One video. Everything lives in output/jobs/<id>/ so any stage can resume."""

    STATUSES = ("draft", "rendered", "approved", "rejected", "published", "failed")

    def __init__(self, folder: Path):
        self.dir = folder
        self.file = folder / "job.json"
        self.data: dict = json.loads(self.file.read_text("utf-8")) if self.file.exists() else {}

    @classmethod
    def create(cls, cfg: dict) -> "Job":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        folder = rel(cfg["paths"]["jobs_dir"]) / f"{stamp}-{random.randint(100, 999)}"
        folder.mkdir(parents=True, exist_ok=False)
        job = cls(folder)
        job.data = {"id": folder.name, "status": "draft", "created": datetime.now().isoformat(timespec="seconds"), "cost_usd": 0.0}
        job.save()
        return job

    @classmethod
    def load(cls, cfg: dict, job_id: str) -> "Job":
        folder = rel(cfg["paths"]["jobs_dir"]) / job_id
        if not (folder / "job.json").exists():
            matches = [p for p in rel(cfg["paths"]["jobs_dir"]).glob(f"*{job_id}*") if (p / "job.json").exists()]
            if len(matches) != 1:
                raise SystemExit(f"No unique job matching '{job_id}'. Run: python run.py list")
            folder = matches[0]
        return cls(folder)

    @classmethod
    def all(cls, cfg: dict) -> list["Job"]:
        root = rel(cfg["paths"]["jobs_dir"])
        if not root.exists():
            return []
        return [cls(p) for p in sorted(root.iterdir()) if (p / "job.json").exists()]

    @property
    def id(self) -> str:
        return self.data["id"]

    def path(self, name: str) -> Path:
        return self.dir / name

    _lock = threading.Lock()   # clips are generated in parallel threads

    def set(self, **kw) -> None:
        with self._lock:
            self.data.update(kw)
            self._write()

    def add_cost(self, usd: float) -> None:
        with self._lock:
            self.data["cost_usd"] = round(self.data.get("cost_usd", 0.0) + usd, 4)
            self._write()

    def save(self) -> None:
        with self._lock:
            self._write()

    def _write(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(self.file)


# ---------------------------------------------------------------- HTTP
class APIError(RuntimeError):
    """A provider rejected the request (bad key, bad input, content filter...)."""


def http(method: str, url: str, *, retries: int = 4, timeout: int = 120, **kw) -> requests.Response:
    """Request with exponential backoff on network errors, 429 and 5xx."""
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, timeout=timeout, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}: {r.text[:300]}", response=r)
            if r.status_code >= 400:
                raise APIError(f"{method} {url} failed ({r.status_code}): {r.text[:500]}")
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == retries:
                raise
            wait = 2 ** attempt + random.random()
            log.warning("Request failed (%s); retrying in %.0fs", e, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def download(url: str, dest: Path) -> Path:
    r = http("GET", url, stream=True, timeout=300)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    tmp.replace(dest)
    return dest


# ---------------------------------------------------------------- ffmpeg
def run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    log.debug(" ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{res.stderr[-2000:]}")


def media_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)
