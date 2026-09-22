import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CreatorthonV3Tests(unittest.TestCase):
    def test_v3_is_an_isolated_route(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('@app.get("/creatorthon-v3/login"', app_source)
        self.assertIn('@app.get("/creatorthon-v3")', app_source)
        self.assertIn('ROOT / "static" / "creatorthon-v3.html"', app_source)

    def test_creatorthon_versions_have_context_aware_sign_out(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        v1_page = (ROOT / "static" / "creatorthon.html").read_text(encoding="utf-8")
        v3_page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn('@app.get("/creatorthon/login"', app_source)
        self.assertIn('async def logout(next: str = "/login")', app_source)
        self.assertIn('href="/logout?next=/creatorthon/login"', v1_page)
        self.assertIn('href="/logout?next=/creatorthon-v3/login"', v3_page)

    def test_v3_contains_requested_creator_journey(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        for expected in (
            "Your categories to create content",
            "Choose an output",
            "Create with PixVerse",
            "Create with HeyGen",
            "CHATGPT IMAGE",
            "TOPIC RESEARCH",
            "/api/creatorthon/topics",
            "/api/video/prompt",
            "/api/video/generate",
        ):
            self.assertIn(expected, page)

    def test_v3_uses_official_logo_and_responsive_layout(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("/static/viralizer-logo-black.png", page)
        self.assertIn("Professional scale and alignment pass", page)
        self.assertIn("@media(max-width:960px)", page)
        self.assertIn("@media(max-width:680px)", page)

    def test_v3_uses_confirmation_gates_and_shows_video_results(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertNotIn('id="ownPromptButton"', page)
        self.assertIn('id="settings" class="settings" hidden', page)
        self.assertIn("Confirm configuration", page)
        self.assertIn("Review before generation", page)
        self.assertIn("Confirm &amp; generate", page)
        self.assertIn("if(state.generationLocked)return", page)
        self.assertIn("d.video_url||d.url||d.output_url", page)
        self.assertIn("['complete','completed','success','succeeded']", page)

    def test_selected_categories_are_visually_persistent(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn(".cat-card.selected", page)
        self.assertIn("✓ Selected", page)
        self.assertIn("state.categories.includes(n)?' on'", page)
        self.assertIn("aria-pressed", page)

    def test_alternate_ideas_compile_separately_and_configuration_rewrites_working_prompt(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("Alternate ideas", page)
        self.assertIn("function alternateConcepts()", page)
        self.assertIn("async function selectAlternateIdea", page)
        self.assertIn("state.alternatePrepared=await compilePrompt(state.activeContent,idea.text)", page)
        self.assertIn("function rewriteConfiguredPrompt()", page)
        self.assertIn("content:state.activeContent||state.topic", page)
        self.assertIn("prompt:state.workingPrepared?.prompt", page)

    def test_generation_reuses_prepared_article_intelligence(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("state.activeContent=d.content||state.topic", page)
        self.assertIn("state.activeContent=state.prepared?.content||state.topic", page)
        self.assertIn("state.activeContent=state.alternatePrepared.content||state.activeContent", page)
        self.assertIn("content:state.activeContent||state.topic", page)

    def test_configuration_defaults_do_not_modify_prompt_until_confirmed(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("No preference", page)
        self.assertIn("state.confirmedConfig=readDraftConfig()", page)
        self.assertIn("function configurationSuffix()", page)
        self.assertNotIn('value="Premium editorial setting"', page)
        self.assertIn('<select id="face"><option value="">No preference</option>', page)

    def test_failed_storage_can_resume_existing_job_without_new_generation(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("resumeJob:null", page)
        self.assertIn("saved.job_id?{provider:saved.provider||'pixverse',job:saved.job_id}", page)
        self.assertIn("Recovering your existing generated video without spending another credit", page)
        self.assertIn("await pollVideo(existing.provider,existing.job)", page)

    def test_completed_video_is_finished_with_speech_and_mandatory_branding(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("async function finishV3Video", page)
        self.assertIn("/api/creatorthon/finish", page)
        self.assertIn("const finalVideoUrl=await finishV3Video", page)
        self.assertIn("nativeSpeech=['heygen','hybrid'].includes(provider)", page)
        self.assertIn("narration=nativeSpeech?'':", page)
        self.assertIn("Open narrated finished video", page)

    def test_category_topics_load_progressively_with_visible_animation(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("loading-orbit", page)
        self.assertIn("cat-card loading", page)
        self.assertIn("@keyframes shimmer", page)
        self.assertIn("state.loadingCategories=new Set(state.categories)", page)
        self.assertIn("show('home');let ready=0", page)
        self.assertIn("categories ready", page)
        self.assertIn("state.loadingCategories.delete(c)", page)


if __name__ == "__main__":
    unittest.main()
