"""Private Viralizer YouTube trend-research and original-story automation.

The service deliberately stops at an approval-ready story. Source media is used
only for temporary analysis and is never copied into generated output.
"""
from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from creatorthon_store import list_reports, save_report


CATEGORIES = (
    "Food", "Fashion", "Real Estate", "Dental", "Beauty", "Automotive",
    "Technology", "Travel", "Sports", "Entertainment", "Business",
    "Politics", "Pets", "Prediction Markets", "Gaming", "Health",
    "Cryptocurrency", "Stocks",
)


class ChannelAutomationError(RuntimeError):
    pass


def _now() -> float:
    return time.time()


def _number(value: Any) -> float:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or "").replace(",", ""))
    return float(match.group(0)) if match else 0.0


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class ViralChannelAutomation:
    def __init__(self, root: Path, mcp_scorer: Callable[[str], Awaitable[dict[str, Any]]]):
        self.root = root
        data_root = Path(os.getenv("APP_DATA_DIR", str(root / "data")))
        self.path = data_root / "channel_automation" / "state.json"
        self.mcp_scorer = mcp_scorer
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None

    def state(self) -> dict[str, Any]:
        try:
            reports = list_reports(self.root, "__viralizer_channel_automation__", 1)
            if reports and isinstance(reports[0].get("content"), dict):
                return reports[0]["content"]
        except Exception:
            pass
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except (OSError, ValueError):
            pass
        return {
            "enabled": os.getenv("CHANNEL_AUTOMATION_ENABLED", "false").lower() == "true",
            "mode": "approval_required",
            "status": "idle",
            "categories": list(CATEGORIES),
            "runs": [],
            "drafts": [],
            "last_error": "",
        }

    def save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _now()
        _atomic_json(self.path, state)
        try:
            save_report(self.root, "__viralizer_channel_automation__", {
                "id": "viralizer-channel-automation-state", "title": "Viralizer Channel Automation State",
                "report_type": "channel-automation-state", "content": state,
            })
        except Exception:
            # Local JSON keeps development usable; production normally persists to PostgreSQL.
            pass

    def update_settings(self, *, enabled: bool, categories: list[str] | None = None) -> dict[str, Any]:
        state = self.state()
        state["enabled"] = bool(enabled)
        if categories is not None:
            allowed = {item.casefold(): item for item in CATEGORIES}
            selected = [allowed[item.casefold()] for item in categories if item.casefold() in allowed]
            state["categories"] = list(dict.fromkeys(selected)) or list(CATEGORIES)
        state["mode"] = "approval_required"
        self.save(state)
        return state

    async def _youtube_candidates(self, category: str) -> list[dict[str, Any]]:
        key = os.getenv("YOUTUBE_DATA_API_KEY", "").strip()
        if not key:
            raise ChannelAutomationError("YOUTUBE_DATA_API_KEY is not configured.")
        published_after = (datetime.now(timezone.utc) - timedelta(days=int(os.getenv("CHANNEL_LOOKBACK_DAYS", "14")))).isoformat().replace("+00:00", "Z")
        query = f"{category} trending shorts"
        async with httpx.AsyncClient(timeout=30.0) as client:
            search = await client.get("https://www.googleapis.com/youtube/v3/search", params={
                "key": key, "part": "snippet", "type": "video", "videoDuration": "short",
                "order": "viewCount", "maxResults": min(25, int(os.getenv("CHANNEL_CANDIDATES_PER_CATEGORY", "10"))),
                "publishedAfter": published_after, "q": query, "relevanceLanguage": "en",
            })
            search.raise_for_status()
            items = search.json().get("items") or []
            ids = [str(item.get("id", {}).get("videoId") or "") for item in items]
            ids = [value for value in ids if value]
            if not ids:
                return []
            details = await client.get("https://www.googleapis.com/youtube/v3/videos", params={
                "key": key, "part": "snippet,statistics,contentDetails", "id": ",".join(ids),
            })
            details.raise_for_status()
        candidates = []
        for item in details.json().get("items") or []:
            snippet, stats = item.get("snippet") or {}, item.get("statistics") or {}
            try:
                published = datetime.fromisoformat(str(snippet.get("publishedAt") or "").replace("Z", "+00:00"))
                age_hours = max(1.0, (datetime.now(timezone.utc) - published).total_seconds() / 3600)
            except ValueError:
                age_hours = 336.0
            views, likes, comments = (_number(stats.get(name)) for name in ("viewCount", "likeCount", "commentCount"))
            velocity = views / age_hours
            engagement = (likes + comments * 2) / max(1.0, views)
            metadata_score = min(100.0, 18 * math.log10(max(1.0, velocity)) + min(28.0, engagement * 650))
            thumbnails = snippet.get("thumbnails") or {}
            thumb = (thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}).get("url", "")
            candidates.append({
                "video_id": item.get("id"), "url": f"https://www.youtube.com/shorts/{item.get('id')}",
                "title": snippet.get("title", ""), "description": str(snippet.get("description") or "")[:1200],
                "channel_id": snippet.get("channelId", ""), "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""), "thumbnail_url": thumb,
                "views": int(views), "likes": int(likes), "comments": int(comments),
                "age_hours": round(age_hours, 2), "view_velocity": round(velocity, 2),
                "engagement_rate": round(engagement, 5), "metadata_score": round(metadata_score, 2),
                "category": category,
            })
        return sorted(candidates, key=lambda item: item["metadata_score"], reverse=True)

    async def _mcp_score(self, candidate: dict[str, Any]) -> dict[str, Any]:
        try:
            insight = await asyncio.wait_for(self.mcp_scorer(candidate["title"]), timeout=90)
        except Exception as exc:
            return {"score": 0.0, "status": "unavailable", "detail": str(exc)[:240]}
        metrics = insight.get("metrics") or {}
        score = max((_number(value) for value in metrics.values()), default=0.0)
        if score > 100:
            score = min(100.0, 25 + math.log10(score) * 12)
        return {"score": round(score, 2), "status": "ready", "metrics": metrics,
                "audience_insight": insight.get("audience_insight", ""),
                "creator_insight": insight.get("creator_insight", "")}

    async def _sample_frames(self, candidate: dict[str, Any]) -> list[str]:
        """Temporarily download one shortlisted public source and sample frames; always delete it."""
        if os.getenv("CHANNEL_FRAME_ANALYSIS_ENABLED", "true").lower() != "true":
            return []
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            return []
        temporary = Path(tempfile.mkdtemp(prefix="viralizer-channel-"))
        video_path = temporary / "source.mp4"
        frame_pattern = temporary / "frame-%02d.jpg"
        try:
            options = {
                "quiet": True, "no_warnings": True, "noplaylist": True,
                "format": "best[height<=720][ext=mp4]/best[height<=720]/best",
                "outtmpl": str(video_path), "socket_timeout": 25,
            }
            await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(options).download([candidate["url"]]))
            actual = video_path if video_path.exists() else next(temporary.glob("source.*"), None)
            if not actual:
                return []
            command = ["ffmpeg", "-y", "-i", str(actual), "-vf", "fps=1/2,scale=512:-2", "-frames:v", "12", str(frame_pattern)]
            await asyncio.to_thread(subprocess.run, command, capture_output=True, timeout=60, check=False)
            return [base64.b64encode(path.read_bytes()).decode("ascii") for path in sorted(temporary.glob("frame-*.jpg"))[:12]]
        except Exception:
            return []
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    async def _visual_analysis(self, candidate: dict[str, Any]) -> dict[str, Any]:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if not key:
            return {"status": "unavailable", "reason": "OPENAI_API_KEY is not configured"}
        frames = await self._sample_frames(candidate)
        images = ([{"type": "input_image", "image_url": f"data:image/jpeg;base64,{value}"} for value in frames]
                  if frames else ([{"type": "input_image", "image_url": candidate["thumbnail_url"]}] if candidate.get("thumbnail_url") else []))
        prompt = f"""Analyze this trending YouTube Short for internal creative research.
Title: {candidate['title']}
Description: {candidate['description']}
Return JSON only: {{"main_subject":"","hook":"","scene_beats":[""],"shot_rhythm":"","camera_language":"","emotional_arc":"","payoff":"","loop_method":"","audio_strategy":"","comment_trigger":"","recreatability":0,"originality_opportunity":0,"risks":[]}}.
Describe only visible evidence. Do not suggest copying footage, faces, wording, music, branding or a shot-for-shot sequence."""
        body = {"model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"), "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, *images]}], "max_output_tokens": 1200}
        try:
            async with httpx.AsyncClient(timeout=150.0) as client:
                response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=body)
                response.raise_for_status()
                data = response.json()
            text = str(data.get("output_text") or "")
            match = re.search(r"\{.*\}", text, re.S)
            result = json.loads(match.group(0) if match else text)
            result.update(status="ready", sampled_frames=len(frames), used_thumbnail_fallback=not bool(frames))
            return result
        except Exception as exc:
            return {"status": "failed", "detail": str(exc)[:240], "sampled_frames": len(frames)}

    async def _story(self, category: str, ranked: list[dict[str, Any]]) -> dict[str, Any]:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        evidence = [{k: item.get(k) for k in ("title", "url", "views", "view_velocity", "engagement_rate", "metadata_score", "mcp", "visual_analysis")} for item in ranked[:5]]
        prompt = f"""Create one ORIGINAL 15–25 second Viralizer YouTube Short story for category {category}, using the cross-video evidence below.
Evidence: {json.dumps(evidence, ensure_ascii=False)[:24000]}
Return JSON only: {{"title":"","category":"{category}","why_now":"","winning_patterns":[""],"originality_angle":"","hook":"","duration":20,"story_beats":[{{"time":"0-2s","visual":"","action":"","camera":"","audio":"","on_screen_text":""}}],"narration":"","music_direction":"","sound_design":"","loop":"","thumbnail":"","caption":"","hashtags":[""],"generation_prompt":"","negative_prompt":"","quality_requirements":[""],"source_video_ids":[]}}.
Use common successful mechanisms, never any source's protected execution. Do not copy faces, exact wording, footage, logos, copyrighted music or shot order. Keep claims supportable. Require Viralizer branding only in a compact final beat."""
        body = {"model": os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1-mini"), "input": prompt, "max_output_tokens": 2600}
        async with httpx.AsyncClient(timeout=150.0) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json=body)
            response.raise_for_status()
            data = response.json()
        text = str(data.get("output_text") or "")
        match = re.search(r"\{.*\}", text, re.S)
        story = json.loads(match.group(0) if match else text)
        story.update(id=uuid.uuid4().hex, status="awaiting_approval", created_at=_now(), mode="original_synthesis")
        return story

    async def run(self, categories: list[str] | None = None) -> dict[str, Any]:
        async with self.lock:
            state = self.state()
            state.update(status="running", last_error="", current_category="")
            self.save(state)
            run = {"id": uuid.uuid4().hex, "started_at": _now(), "categories": [], "status": "running"}
            try:
                selected = categories or state.get("categories") or list(CATEGORIES)
                for category in selected:
                    state["current_category"] = category
                    self.save(state)
                    candidates = await self._youtube_candidates(category)
                    shortlist = candidates[:min(5, len(candidates))]
                    for candidate in shortlist[:3]:
                        candidate["mcp"] = await self._mcp_score(candidate)
                        mcp = float(candidate["mcp"].get("score") or 0)
                        candidate["opportunity_score"] = round(candidate["metadata_score"] * .7 + mcp * .3, 2)
                    shortlist.sort(key=lambda item: item.get("opportunity_score", item["metadata_score"]), reverse=True)
                    if shortlist:
                        shortlist[0]["visual_analysis"] = await self._visual_analysis(shortlist[0])
                        story = await self._story(category, shortlist)
                        story["research"] = {"top_candidates": shortlist, "discovered_count": len(candidates)}
                        state.setdefault("drafts", []).insert(0, story)
                        state["drafts"] = state["drafts"][:100]
                    run["categories"].append({"category": category, "discovered": len(candidates), "shortlisted": len(shortlist)})
                    self.save(state)
                run.update(status="completed", completed_at=_now())
                state.update(status="idle", current_category="", last_run_at=_now())
            except Exception as exc:
                run.update(status="failed", completed_at=_now(), error=str(exc)[:500])
                state.update(status="failed", current_category="", last_error=str(exc)[:500])
            state.setdefault("runs", []).insert(0, run)
            state["runs"] = state["runs"][:30]
            self.save(state)
            return run

    def start(self, categories: list[str] | None = None) -> dict[str, Any]:
        if self.task and not self.task.done():
            raise ChannelAutomationError("A channel research cycle is already running.")
        self.task = asyncio.create_task(self.run(categories))
        return {"accepted": True, "status": "running", "categories": categories or self.state().get("categories") or list(CATEGORIES)}

    def set_draft_status(self, draft_id: str, status: str) -> dict[str, Any]:
        state = self.state()
        draft = next((item for item in state.get("drafts", []) if item.get("id") == draft_id), None)
        if not draft:
            raise ChannelAutomationError("Automation draft not found.")
        draft["status"] = status
        draft["reviewed_at"] = _now()
        self.save(state)
        return draft

    def update_draft(self, draft_id: str, values: dict[str, Any]) -> dict[str, Any]:
        state = self.state()
        draft = next((item for item in state.get("drafts", []) if item.get("id") == draft_id), None)
        if not draft:
            raise ChannelAutomationError("Automation draft not found.")
        draft.update(values, updated_at=_now())
        self.save(state)
        return draft

    async def scheduler(self) -> None:
        await asyncio.sleep(max(5, int(os.getenv("CHANNEL_AUTOMATION_STARTUP_DELAY_SECONDS", "60"))))
        while True:
            state = self.state()
            if state.get("enabled"):
                await self.run()
            await asyncio.sleep(max(1800, int(os.getenv("CHANNEL_AUTOMATION_INTERVAL_SECONDS", "14400"))))
