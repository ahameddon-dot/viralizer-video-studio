import asyncio
import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import app


def _request(path="/api/prototype/video/start", method="POST", origin="https://viralizer-onboarding-demo.intuition-in-7630.chatgpt.site", request_id="prototype-request-123456"):
    headers = [(b"origin", origin.encode())]
    if request_id:
        headers.append((b"x-prototype-request-id", request_id.encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b"", "scheme": "https", "server": ("testserver", 443)})


def _payload():
    return app.PrototypeVideoStartRequest(
        title="Premium product reveal",
        category="Product",
        creative_style="Cinematic commercial",
        scenes=[
            {"title": "Hook", "visual": "Hero product enters dramatic light", "duration_seconds": 3},
            {"title": "Benefit", "visual": "A customer naturally demonstrates the product", "duration_seconds": 3},
            {"title": "Reveal", "visual": "Premium final hero composition", "duration_seconds": 3},
        ],
    )


class PrototypeVideoAdapterTests(unittest.TestCase):
 def test_prototype_middleware_rejects_another_origin(self):
    called = False

    async def downstream(_request):
        nonlocal called
        called = True
        return JSONResponse({"ok": True})

    with patch.dict(os.environ, {"PROTOTYPE_ALLOWED_ORIGIN": "https://viralizer-onboarding-demo.intuition-in-7630.chatgpt.site"}):
        response = asyncio.run(app.require_password(_request(origin="https://example.com"), downstream))
    self.assertEqual(response.status_code, 403)
    self.assertFalse(called)


 def test_prototype_middleware_answers_preflight(self):
    allowed = "https://viralizer-onboarding-demo.intuition-in-7630.chatgpt.site"
    with patch.dict(os.environ, {"PROTOTYPE_ALLOWED_ORIGIN": allowed}):
        response = asyncio.run(app.require_password(_request(method="OPTIONS", request_id=""), lambda _request: None))
    self.assertEqual(response.status_code, 204)
    self.assertEqual(response.headers["access-control-allow-origin"], allowed)
    self.assertIn("X-Prototype-Request-Id", response.headers["access-control-allow-headers"])


 def test_prototype_middleware_allows_configured_comparison_origin(self):
    original = "https://viralizer-onboarding-demo.intuition-in-7630.chatgpt.site"
    comparison = "https://viralizer-concept-b.intuition-in-7630.chatgpt.site"
    configured = f"{original},{comparison}"

    async def downstream(_request):
        return JSONResponse({"ok": True})

    with patch.dict(os.environ, {"PROTOTYPE_ALLOWED_ORIGIN": configured}):
        response = asyncio.run(app.require_password(_request(origin=comparison), downstream))
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.headers["access-control-allow-origin"], comparison)


 def test_start_is_durable_and_idempotent(self):
    projects = []
    provider_calls = []

    def list_projects(_root, _user, limit=100):
        return list(projects)

    def create_project(_root, _user, topic, values):
        project = {"id": "p" * 32, "topic": topic, "created_at": 1, **values}
        projects.append(project)
        return project

    def update_project(_root, _user, project_id, values):
        project = next(item for item in projects if item["id"] == project_id)
        project.update(values)
        return project

    async def generate_video(request):
        provider_calls.append(request)
        return {"provider": "pixverse", "job_id": "provider-1"}

    with patch.dict(os.environ, {"PROTOTYPE_GENERATION_ENABLED": "true"}), \
         patch.object(app, "list_projects", list_projects), \
         patch.object(app, "create_project", create_project), \
         patch.object(app, "update_project", update_project), \
         patch.object(app, "generate_video", generate_video), \
         patch.object(app, "enqueue_durable_media_job", lambda *_a, **_k: {"id": "a" * 32, "status": "queued", "stage": "Queued"}):
        first = asyncio.run(app.start_prototype_video(_request(), _payload()))
        second = asyncio.run(app.start_prototype_video(_request(), _payload()))

    self.assertEqual(first["media_job_id"], "a" * 32)
    self.assertFalse(first["reused"])
    self.assertTrue(second["reused"])
    self.assertEqual(len(provider_calls), 1)
    self.assertIn("official Viralizer logo", provider_calls[0].prompt)


 def test_status_returns_only_safe_fields_and_signed_url(self):
    job = {
        "id": "a" * 32, "status": "completed", "stage": "Ready", "error": "",
        "output_url": "/api/finished-video/viralizer-" + "b" * 32 + ".mp4",
        "updated_at": 123, "payload": {"official_logo_data": "private"}, "raw_video_url": "private",
    }
    with patch.object(app, "get_durable_media_job", lambda *_a: job), \
         patch.object(app, "object_share_url", lambda key, expires_in=0: f"https://media.example/{key}?ttl={expires_in}"):
        result = asyncio.run(app.prototype_video_status("a" * 32))
    self.assertTrue(result["video_url"].startswith("https://media.example/finished_videos/"))
    self.assertNotIn("payload", result)
    self.assertNotIn("raw_video_url", result)


 def test_status_rejects_unknown_job(self):
    with patch.object(app, "get_durable_media_job", lambda *_a: None):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(app.prototype_video_status("a" * 32))
    self.assertEqual(exc.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
