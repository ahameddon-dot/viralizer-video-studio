import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creatorthon_store import add_asset, create_project, list_projects, save_report, update_project, workspace
from object_store import configured


ROOT = Path(__file__).resolve().parents[1]


class CreatorthonWorkspaceTests(unittest.TestCase):
    def test_existing_database_migrates_and_complete_project_round_trips(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"APP_DATA_DIR": folder}):
            project = create_project(ROOT, "user-1", {"title": "Saved fashion story", "category": "Fashion"}, {
                "provider": "pixverse", "prompt": {"text": "A precise saved prompt"},
                "narration": {"text": "Saved narration"}, "configuration": {"face": "Female"},
                "article_intelligence": {"core_message": "A concrete message"}, "aspect_ratio": "9:16", "quality": "720p",
            })
            updated = update_project(ROOT, "user-1", project["id"], {
                "status": "completed", "video_url": "/api/finished-video/viralizer-test.mp4",
                "production": {"job_id": "job-1"}, "qc": {"passed": True},
            })
            self.assertEqual(updated["prompt"]["text"], "A precise saved prompt")
            self.assertEqual(updated["configuration"]["face"], "Female")
            self.assertEqual(updated["status"], "completed")
            self.assertTrue(updated["qc"]["passed"])

    def test_workspace_is_strictly_scoped_to_signed_in_user(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {"APP_DATA_DIR": folder}):
            mine = create_project(ROOT, "user-1", {"title": "Mine"})
            create_project(ROOT, "user-2", {"title": "Not mine"})
            save_report(ROOT, "user-1", {"project_id": mine["id"], "title": "My report", "content": {"summary": "Saved"}})
            save_report(ROOT, "user-2", {"title": "Private report", "content": {"summary": "Hidden"}})
            add_asset(ROOT, "user-1", {"project_id": mine["id"], "kind": "video", "url": "/mine.mp4"})
            result = workspace(ROOT, {"sub": "user-1", "email": "me@example.com", "name": "Creator"})
            self.assertEqual([item["title"] for item in result["projects"]], ["Mine"])
            self.assertEqual([item["title"] for item in result["reports"]], ["My report"])
            self.assertEqual([item["url"] for item in result["assets"]], ["/mine.mp4"])

    def test_workspace_page_and_authenticated_routes_exist(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        page = (ROOT / "static" / "creatorthon-workspace.html").read_text(encoding="utf-8")
        self.assertIn('@app.get("/creatorthon/workspace")', app_source)
        self.assertIn('@app.get("/api/creatorthon/workspace")', app_source)
        self.assertIn('@app.post("/api/creatorthon/reports")', app_source)
        self.assertIn("My Workspace", page)
        self.assertIn("My videos", page)
        self.assertIn("/api/creatorthon/workspace", page)

    def test_all_creatorthon_versions_link_to_shared_workspace(self):
        for filename in ("creatorthon.html", "creatorthon-v2.html", "creatorthon-v3.html"):
            page = (ROOT / "static" / filename).read_text(encoding="utf-8")
            self.assertIn('/creatorthon/workspace', page, filename)

    def test_cloud_storage_is_optional_for_local_development(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(configured())

    def test_production_dependencies_and_environment_are_documented(self):
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("psycopg[binary]", requirements)
        self.assertIn("boto3", requirements)
        self.assertIn("DATABASE_URL=", example)
        self.assertIn("R2_BUCKET_NAME=viralizer-media", example)
        self.assertIn("await upload_object_file", app_source)
        self.assertIn("await restore_object_file", app_source)


if __name__ == "__main__":
    unittest.main()
