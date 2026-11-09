"""Stage 9: upload an approved video to YouTube (Shorts) with the official Data API v3."""
from __future__ import annotations

from datetime import datetime, timezone

from .common import Job, log, rel

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _service(cfg: dict):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise SystemExit("YouTube libraries missing. Run: pip install -r requirements.txt")

    yt = cfg["publish"]["youtube"]
    token, secrets = rel(yt["token_file"]), rel(yt["client_secrets_file"])
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets.exists():
                raise SystemExit(f"Put your OAuth client file at {secrets} (see README, 'YouTube setup').")
            creds = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES).run_local_server(port=0)
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json(), "utf-8")
    return build("youtube", "v3", credentials=creds)


def authorize(cfg: dict) -> None:
    _service(cfg)
    log.info("YouTube authorised. Token saved to %s", cfg["publish"]["youtube"]["token_file"])


def upload(cfg: dict, job: Job, script: dict, publish_at: datetime | None = None) -> str:
    from googleapiclient.http import MediaFileUpload

    yt_cfg = cfg["publish"]["youtube"]
    meta = script.get("youtube", {})
    title = (meta.get("title") or script["title"])[:100]
    desc = meta.get("description", "")
    if "#shorts" not in desc.lower():
        desc += "\n#shorts"

    status = {
        "privacyStatus": yt_cfg["privacy"],
        "selfDeclaredMadeForKids": yt_cfg["made_for_kids"],
        "containsSyntheticMedia": yt_cfg["contains_synthetic_media"],
    }
    if publish_at:  # scheduled release: must be private until then
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    body = {
        "snippet": {"title": title, "description": desc, "tags": meta.get("tags", [])[:15], "categoryId": yt_cfg["category_id"]},
        "status": status,
    }
    media = MediaFileUpload(str(job.path("final.mp4")), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = _service(cfg).videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        prog, resp = req.next_chunk()
        if prog:
            log.info("  uploading... %d%%", int(prog.progress() * 100))
    url = f"https://youtube.com/shorts/{resp['id']}"
    log.info("Uploaded: %s", url)
    return url
