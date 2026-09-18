from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

import httpx


class SocialPublishError(RuntimeError):
    pass


MANDATORY_HASHTAG = "#viralizer.ai"


def build_hashtags(topic: dict[str, Any]) -> list[str]:
    text = " ".join(str(topic.get(key) or "") for key in ("topic", "category_label", "category", "summary"))
    words = re.findall(r"[A-Za-z][A-Za-z0-9]+", text)
    blocked = {"about", "after", "before", "from", "into", "news", "review", "shows", "showcases",
               "the", "this", "that", "their", "they", "with", "trend", "launch", "update", "offerings"}
    tags: list[str] = [MANDATORY_HASHTAG, "#ViralizerAI", "#ViralVideo", "#ContentCreator"]
    phrase = "".join(word[:1].upper() + word[1:] for word in words[:5] if word.lower() not in blocked)
    if phrase:
        tags.append("#" + phrase[:48])
    for word in words:
        normalized = word.lower()
        if normalized in blocked or len(word) < 4:
            continue
        tag = "#" + word[:1].upper() + word[1:]
        if tag.lower() not in {value.lower() for value in tags}:
            tags.append(tag)
        if len(tags) >= 14:
            break
    return tags


def publishing_status() -> dict[str, dict[str, Any]]:
    meta_token = bool(os.getenv("META_ACCESS_TOKEN", "").strip())
    return {
        "instagram": {
            "configured": meta_token and bool(os.getenv("INSTAGRAM_USER_ID", "").strip()) and bool(os.getenv("PUBLIC_BASE_URL", "").strip()),
            "label": "Instagram",
        },
        "facebook": {
            "configured": meta_token and bool(os.getenv("FACEBOOK_PAGE_ID", "").strip()),
            "label": "Facebook",
        },
        "linkedin": {
            "configured": bool(os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()) and bool(os.getenv("LINKEDIN_AUTHOR_URN", "").strip()),
            "label": "LinkedIn",
        },
    }


def _caption(caption: str, hashtags: list[str]) -> str:
    clean_tags = list(dict.fromkeys(tag.strip() for tag in hashtags if tag.strip()))
    if MANDATORY_HASHTAG.lower() not in {tag.lower() for tag in clean_tags}:
        clean_tags.insert(0, MANDATORY_HASHTAG)
    return (caption.strip() + "\n\n" + " ".join(clean_tags)).strip()


async def _instagram(caption: str, hashtags: list[str], video_url: str) -> dict[str, Any]:
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    user_id = os.getenv("INSTAGRAM_USER_ID", "").strip()
    public_base = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not token or not user_id or not public_base:
        raise SocialPublishError("Instagram publishing is not configured.")
    if public_base.startswith(("http://localhost", "http://127.0.0.1")):
        raise SocialPublishError("Instagram requires PUBLIC_BASE_URL to be a public HTTPS address.")
    graph = os.getenv("META_GRAPH_VERSION", "v24.0").strip()
    public_video = video_url if video_url.startswith("https://") else public_base + "/" + video_url.lstrip("/")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"https://graph.facebook.com/{graph}/{user_id}/media",
            data={"media_type": "REELS", "video_url": public_video, "caption": _caption(caption, hashtags),
                  "share_to_feed": "true", "access_token": token},
        )
        if response.is_error:
            raise SocialPublishError(response.json().get("error", {}).get("message") or "Instagram rejected the video container.")
        container_id = response.json().get("id")
        for _ in range(30):
            check = await client.get(
                f"https://graph.facebook.com/{graph}/{container_id}",
                params={"fields": "status_code,status", "access_token": token},
            )
            status = str(check.json().get("status_code") or "").upper()
            if status == "FINISHED":
                break
            if status in {"ERROR", "EXPIRED"}:
                raise SocialPublishError(check.json().get("status") or "Instagram could not process the reel.")
            await asyncio.sleep(4)
        else:
            raise SocialPublishError("Instagram is still processing the reel. Try publishing again shortly.")
        published = await client.post(
            f"https://graph.facebook.com/{graph}/{user_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
        )
        if published.is_error:
            raise SocialPublishError(published.json().get("error", {}).get("message") or "Instagram could not publish the reel.")
        return {"status": "published", "id": published.json().get("id", "")}


async def _facebook(caption: str, hashtags: list[str], video_path: Path) -> dict[str, Any]:
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    page_id = os.getenv("FACEBOOK_PAGE_ID", "").strip()
    if not token or not page_id:
        raise SocialPublishError("Facebook publishing is not configured.")
    graph = os.getenv("META_GRAPH_VERSION", "v24.0").strip()
    async with httpx.AsyncClient(timeout=180) as client:
        with video_path.open("rb") as source:
            response = await client.post(
                f"https://graph.facebook.com/{graph}/{page_id}/videos",
                data={"description": _caption(caption, hashtags), "access_token": token},
                files={"source": (video_path.name, source, "video/mp4")},
            )
    if response.is_error:
        raise SocialPublishError(response.json().get("error", {}).get("message") or "Facebook could not publish the video.")
    return {"status": "published", "id": response.json().get("id", "")}


async def _linkedin(caption: str, hashtags: list[str], video_path: Path) -> dict[str, Any]:
    token = os.getenv("LINKEDIN_ACCESS_TOKEN", "").strip()
    author = os.getenv("LINKEDIN_AUTHOR_URN", "").strip()
    version = os.getenv("LINKEDIN_VERSION", "202608").strip()
    if not token or not author:
        raise SocialPublishError("LinkedIn publishing is not configured.")
    headers = {"Authorization": f"Bearer {token}", "Linkedin-Version": version,
               "X-Restli-Protocol-Version": "2.0.0", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=180) as client:
        initialized = await client.post(
            "https://api.linkedin.com/rest/videos?action=initializeUpload",
            headers=headers,
            json={"initializeUploadRequest": {"owner": author, "fileSizeBytes": video_path.stat().st_size,
                                               "uploadCaptions": False, "uploadThumbnail": False,
                                               "templateName": "Viralizer"}},
        )
        if initialized.is_error:
            raise SocialPublishError("LinkedIn could not initialize the video upload.")
        value = initialized.json().get("value") or {}
        instructions = value.get("uploadInstructions") or []
        part_ids = []
        with video_path.open("rb") as source:
            for instruction in instructions:
                first, last = int(instruction["firstByte"]), int(instruction["lastByte"])
                source.seek(first)
                chunk = source.read(last - first + 1)
                uploaded = await client.put(instruction["uploadUrl"], content=chunk,
                                            headers={"Content-Type": "application/octet-stream"})
                uploaded.raise_for_status()
                part_ids.append(uploaded.headers.get("etag", "").strip('"'))
        finalized = await client.post(
            "https://api.linkedin.com/rest/videos?action=finalizeUpload",
            headers=headers,
            json={"finalizeUploadRequest": {"video": value.get("video"), "uploadToken": value.get("uploadToken", ""),
                                             "uploadedPartIds": part_ids}},
        )
        if finalized.is_error:
            raise SocialPublishError("LinkedIn could not finalize the video upload.")
        post = await client.post(
            "https://api.linkedin.com/rest/posts",
            headers=headers,
            json={"author": author, "commentary": _caption(caption, hashtags), "visibility": "PUBLIC",
                  "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
                  "content": {"media": {"id": value.get("video")}},
                  "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False},
        )
        if post.is_error:
            raise SocialPublishError("LinkedIn uploaded the video but could not create the post.")
        return {"status": "published", "id": post.headers.get("x-restli-id", "")}


async def publish_all(video_path: Path, video_url: str, caption: str, hashtags: list[str], platforms: list[str]) -> dict[str, Any]:
    selected = [value.lower() for value in platforms if value.lower() in {"instagram", "facebook", "linkedin"}]
    if not selected:
        raise SocialPublishError("Select at least one social platform.")
    handlers = {
        "instagram": lambda: _instagram(caption, hashtags, video_url),
        "facebook": lambda: _facebook(caption, hashtags, video_path),
        "linkedin": lambda: _linkedin(caption, hashtags, video_path),
    }
    results = {}
    for platform in selected:
        try:
            results[platform] = await handlers[platform]()
        except (SocialPublishError, httpx.HTTPError) as exc:
            results[platform] = {"status": "failed", "detail": str(exc)}
    return {"results": results, "all_published": all(item["status"] == "published" for item in results.values())}
