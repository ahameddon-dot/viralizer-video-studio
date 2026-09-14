import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx


class SavedVideoError(RuntimeError):
    pass


def _folder(root: Path) -> Path:
    path = Path(os.getenv("APP_DATA_DIR", str(root / "data"))) / "finished_videos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path(root: Path) -> Path:
    return _folder(root) / "library.json"


def _read_index(root: Path) -> list[dict]:
    path = _index_path(root)
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_index(root: Path, items: list[dict]) -> None:
    path = _index_path(root)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def list_saved_videos(root: Path) -> list[dict]:
    folder = _folder(root)
    items = [item for item in _read_index(root) if (folder / str(item.get("filename", ""))).is_file()]
    indexed = {str(item.get("filename", "")) for item in items}
    for path in folder.glob("viralizer-*.mp4"):
        if path.name in indexed:
            continue
        items.append({
            "id": uuid.uuid4().hex,
            "filename": path.name,
            "url": f"/api/finished-video/{path.name}",
            "title": "Previously generated video",
            "provider": "Hybrid" if path.name.startswith("viralizer-hybrid-") else "Viralizer",
            "created_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        })
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    if {str(item.get("filename", "")) for item in items} != indexed:
        _write_index(root, items[:100])
    return items


async def save_video(root: Path, video_url: str, title: str, provider: str) -> dict:
    folder = _folder(root)
    source = str(video_url or "").strip()
    if not source:
        raise SavedVideoError("The generated video URL is missing.")

    if source.startswith("/api/finished-video/"):
        filename = Path(source).name
        path = folder / filename
        if not path.is_file():
            raise SavedVideoError("The finished video file was not found.")
    else:
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"}:
            raise SavedVideoError("The generated video URL is invalid.")
        filename = f"viralizer-{uuid.uuid4().hex}.mp4"
        path = folder / filename
        temporary = path.with_suffix(".download")
        try:
            async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
                async with client.stream("GET", source) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and "video" not in content_type and "octet-stream" not in content_type:
                        raise SavedVideoError("The provider did not return a video file.")
                    size = 0
                    with temporary.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 250 * 1024 * 1024:
                                raise SavedVideoError("The generated video is larger than 250 MB.")
                            output.write(chunk)
            temporary.replace(path)
        except SavedVideoError:
            temporary.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            raise SavedVideoError("Could not copy the generated video into the library.") from exc

    items = _read_index(root)
    existing = next((item for item in items if item.get("filename") == filename), None)
    if existing:
        return existing
    record = {
        "id": uuid.uuid4().hex,
        "filename": filename,
        "url": f"/api/finished-video/{filename}",
        "title": " ".join(str(title or "Generated video").split())[:180] or "Generated video",
        "provider": " ".join(str(provider or "video").split())[:40] or "video",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items.insert(0, record)
    await asyncio.to_thread(_write_index, root, items[:100])
    return record