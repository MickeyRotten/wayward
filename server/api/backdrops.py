"""Chat backdrops — static scene art in server/backdrops (repo-shipped, not
per-campaign). The client picks one deterministically from the declared scene —
location + time-of-day tokens matched against the filename (city_day.png, …),
defaulting to forest_day.png (see client lib/backdrops.ts). This doubles as the
foundation for a future narrator-driven pick: drop in more images and they
start matching, no narrator changes needed."""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from server.api.common import BACKDROPS_DIR, _MEDIA_CACHE

router = APIRouter()

_BACKDROP_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


@router.get("/backdrops")
async def list_backdrops():
    if not BACKDROPS_DIR.is_dir():
        return []
    return [
        {"file": p.name, "url": f"/api/backdrops/{p.name}"}
        for p in sorted(BACKDROPS_DIR.iterdir(), key=lambda p: p.name.lower())
        if p.is_file() and p.suffix.lower() in _BACKDROP_EXTS
    ]


@router.get("/backdrops/{filename}")
async def get_backdrop(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(400, "Bad filename")
    path = BACKDROPS_DIR / filename
    if not path.is_file() or path.suffix.lower() not in _BACKDROP_EXTS:
        raise HTTPException(404, "No such backdrop")
    return FileResponse(str(path), headers=_MEDIA_CACHE)


@router.post("/backdrops/upload")
async def upload_backdrop(file: UploadFile):
    """Add a backdrop image. The filename's words are what the scene matcher
    scores against the declared location + time of day ("city_day.png" → city +
    day), so the sanitized original name is kept."""
    original = Path(file.filename or "").name
    ext = Path(original).suffix.lower()
    if ext not in _BACKDROP_EXTS:
        raise HTTPException(400, "Backdrops must be .png, .jpg or .webp")
    stem = re.sub(r"[^\w\-]+", "_", Path(original).stem).strip("_.") or "backdrop"
    BACKDROPS_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKDROPS_DIR / f"{stem}{ext}"
    dest.write_bytes(await file.read())
    return {"file": dest.name, "url": f"/api/backdrops/{dest.name}"}


@router.delete("/backdrops/{filename}", status_code=204)
async def delete_backdrop(filename: str):
    if Path(filename).name != filename:
        raise HTTPException(400, "Bad filename")
    path = BACKDROPS_DIR / filename
    if not path.is_file() or path.suffix.lower() not in _BACKDROP_EXTS:
        raise HTTPException(404, "No such backdrop")
    path.unlink()
