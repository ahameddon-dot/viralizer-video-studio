import unittest
from pathlib import Path

from starlette.requests import Request

import app


ROOT = Path(__file__).resolve().parents[1]


class CreatorthonV3Tests(unittest.TestCase):
    def test_product_video_builder_uses_secured_creatorthon_pipeline(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        page = (ROOT / "static" / "creatorthon-product.html").read_text(encoding="utf-8")
        catalog = (ROOT / "static" / "product-video-catalog.js").read_text(encoding="utf-8")
        v3_page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn('@app.get("/creatorthon/product")', app_source)
        self.assertIn('@app.get("/product")', app_source)
        self.assertIn('href="/product"', v3_page)
        self.assertIn("Food:{icon:'🍽️'", page)
        self.assertIn("'Real Estate':{icon:'🏡'", page)
        self.assertIn("Dental:{icon:'🦷'", page)
        self.assertIn("Chettinad Biryani", page)
        self.assertIn("Kitchen to table", page)
        self.assertIn("'Real Estate':[['🏡','Property walkthrough'", page)
        self.assertIn("Dental:[['✨','Smile transformation'", page)
        self.assertIn("const activeStyles=()=>productStyleCatalog[state.industry+':'+state.product]||styleCatalog[state.industry]||fallbackStyles", page)
        self.assertIn("'Fashion:Sarees'", page)
        self.assertIn("Saree unboxing", page)
        self.assertIn("Draping tutorial", page)
        self.assertIn("360° saree view", page)
        self.assertIn("/api/creatorthon/prepare-prompt", page)
        self.assertIn("/api/creatorthon/concept/generate", page)
        self.assertIn("prompt:''", page)
        self.assertIn("gaming controllers", page)
        self.assertIn("product_visual_spec:spec", page)
        self.assertIn("product-video-catalog.js", page)
        self.assertIn("'Fashion:Sarees'", catalog)
        self.assertIn("'Fashion:Innerwear'", catalog)
        self.assertIn("Kanjivaram silk", catalog)
        self.assertIn("Premium flat lay", catalog)
        self.assertIn("Adult model wearing — catalogue", catalog)
        self.assertIn("Fully transparent garment", catalog)
        self.assertIn("Agent guides buyer walkthrough", catalog)
        self.assertIn("Chef prepares and plates", catalog)
        self.assertIn("'Food:Biryani'", catalog)
        self.assertIn("Ladle tapping on the vessel", catalog)
        self.assertIn("Banana leaf", catalog)
        self.assertIn("Indian street-side service", page)
        self.assertIn("rhythmic ladle tapping and generous serving", page)
        self.assertIn("add '+side+', hand the complete serving across the counter", page)
        self.assertIn("product_attributes:state.attributes", page)
        self.assertIn("human_interaction:humanDirection()", page)
        self.assertIn("Three-shot storyboard", page)
        self.assertIn("function biryaniAuthenticity()", page)
        self.assertIn("Kolkata Biryani':'fragrant long-grain rice with the signature whole potato, boiled egg", page)
        self.assertIn("Thalassery Biryani':'short-grain kaima or jeerakasala rice", page)
        self.assertIn("Ladle clang, steam and crowd ambience", catalog)
        self.assertIn("Authentic rapid street service", catalog)
        self.assertIn("Family sharing portion", catalog)
        for schema in (
            "Food:Pizza", "Food:Desserts", "Food:Beverages",
            "Real Estate:Property for sale", "Real Estate:Property for rent", "Real Estate:New development",
            "Dental:Invisible braces", "Dental:Dental implants", "Dental:Smile care", "Dental:Preventive care",
            "Fashion:Apparel", "Fashion:Accessories",
            "Beauty:Skincare", "Beauty:Cosmetics", "Beauty:Salon",
            "Automotive:Vehicles", "Automotive:Auto services",
            "Technology:Software", "Technology:Devices",
            "Travel:Destinations", "Travel:Hospitality",
        ):
            self.assertIn(f"'{schema}'", catalog)
        self.assertIn("'Food:Pizza'", page)
        self.assertIn("Dough to slice", page)
        self.assertIn("'Food:Desserts'", page)
        self.assertIn("Cut and centre reveal", page)
        self.assertIn("'Food:Beverages'", page)
        self.assertIn("Pour and refresh", page)
        self.assertIn("function specializedVisualSpec()", page)
        self.assertIn("avoid:['clay pots','rice vessels','biryani','cake'", page)
        self.assertIn("single continuous micro-story", page)
        self.assertIn("same mountain skyline", page)
        self.assertIn("Snowy Himalayan hill town", catalog)
        self.assertIn("Lodge arrival and balcony reveal", catalog)
        self.assertIn("'Travel:Destinations:Beach Holiday'", catalog)
        self.assertIn("Maldives-style tropical island", catalog)
        self.assertIn("Barefoot beach arrival", catalog)
        self.assertIn("'Travel:Destinations:City Break'", catalog)
        self.assertIn("'Travel:Destinations:Mountain Escape'", catalog)
        self.assertIn("'Travel:Destinations:Cultural Tour'", catalog)
        self.assertIn("subtypeKey=key+':'+state.subtype", page)
        self.assertIn("mixing beach, mountain, city or cultural scenery", page)
        self.assertIn("lightweight resort clothing", page)
        self.assertIn("state.subtype=v;state.attributes={}", page)
        self.assertIn("updateSummary();$('#next').disabled=!canContinue()||state.generating", page)

    def test_prediction_market_category_has_two_live_source_buttons(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("['Prediction Markets','◒']", page)
        self.assertIn('data-prediction-source="kalshi"', page)
        self.assertIn('data-prediction-source="polymarket"', page)
        self.assertIn("/api/creatorthon/prediction-markets/", page)
        self.assertIn("Market probabilities are not confirmed facts or financial advice", page)
        self.assertIn("Viralizer does not recommend buying, selling or placing a trade", page)
        self.assertIn("What Yes means:", page)
        self.assertIn("kalshi-outcomes", page)
        self.assertIn('id="marketSearch"', page)
        self.assertIn("?q='+encodeURIComponent(state.predictionQuery)", page)
        self.assertIn("Coverage across the web", page)
        self.assertIn("/api/creatorthon/prediction-coverage", page)
        self.assertIn("selectCoverageArticle", page)

    def test_prediction_market_payloads_are_normalized_for_v3_topics(self):
        kalshi = app._kalshi_market_topic({
            "title": "Will rates change?", "last_price": 63, "price_change_24h": 4,
            "volume_24h": 2500000, "close_time": "2026-11-01T00:00:00Z", "ticker": "RATE-26",
        })
        self.assertEqual(kalshi["prediction_source"], "Kalshi")
        self.assertEqual(kalshi["probability"], 63.0)
        self.assertEqual(kalshi["movement_24h"], 4.0)
        self.assertIn("not a confirmed prediction", kalshi["summary"])
        kalshi_event = app._kalshi_event_topic({
            "title": "Who will win the city election?",
            "sub_title": "The candidate officially declared the winner",
            "category": "Politics",
            "event_ticker": "CITYWINNER-26",
            "settlement_sources": [{"name": "Election authority", "url": "https://example.com/results"}],
            "markets": [
                {
                    "status": "active", "yes_sub_title": "Candidate A", "last_price_dollars": "0.62",
                    "previous_price_dollars": "0.58", "volume_24h_fp": "25000",
                    "close_time": "2026-11-01T00:00:00Z",
                    "rules_primary": "Resolves Yes if Candidate A is officially declared the winner.",
                },
                {
                    "status": "active", "yes_sub_title": "Candidate B", "last_price_dollars": "0.31",
                    "previous_price_dollars": "0.30", "volume_24h_fp": "12000",
                    "close_time": "2026-11-01T00:00:00Z",
                },
            ],
        })
        self.assertEqual(kalshi_event["title"], "Who will win the city election?")
        self.assertEqual(kalshi_event["market_category"], "Politics")
        self.assertEqual(kalshi_event["outcomes"][0], {"label": "Candidate A", "probability": 62.0})
        self.assertEqual(kalshi_event["movement_24h"], 4.0)
        self.assertIn("officially declared", kalshi_event["what_yes_means"])
        self.assertEqual(kalshi_event["settlement_sources"][0]["name"], "Election authority")
        searched = app._search_prediction_market_topics(
            [kalshi_event, {"title": "Will rainfall exceed average?", "outcomes": []}],
            "candidate winner",
        )
        self.assertEqual([item["title"] for item in searched], ["Who will win the city election?"])
        usc_event = app._kalshi_event_topic({
            "title": "College Football: Teams to leave their Conference",
            "category": "Sports",
            "markets": [{"status": "active", "yes_sub_title": "USC", "title": "Will USC leave the Big Ten?", "last_price_dollars": "0.12"}],
        })
        self.assertEqual(app._search_prediction_market_topics([usc_event], "USC"), [usc_event])
        polymarket = app._polymarket_topic({
            "question": "Will an event happen?", "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.72","0.28"]', "oneDayPriceChange": 0.03,
            "volume24hr": 1000000, "endDate": "2026-12-01T00:00:00Z", "slug": "event-happen",
        })
        self.assertEqual(polymarket["prediction_source"], "Polymarket")
        self.assertEqual(polymarket["leading_outcome"], "Yes")
        self.assertEqual(polymarket["probability"], 72.0)
        self.assertEqual(polymarket["movement_24h"], 3.0)

    def test_product_prompt_enforces_continuous_travel_sequence(self):
        prompt = app._creatorthon_product_prompt({
            "category": "Travel",
            "product": "Destinations",
            "product_subtype": "Mountain Escape",
            "creative_style": "Destination film",
            "product_visual_spec": {
                "subject": "the same adult couple at one mountain lodge",
                "environment": "one lodge with the same mountain skyline",
                "sequence_mode": "single continuous micro-story; do not cut to a second destination",
                "beats": ["arrive outside the lodge", "walk to its viewpoint", "share a natural reaction"],
                "avoid": ["changing country", "teleporting between locations"],
            },
        }, 15, "9:16")
        self.assertIn("SEQUENCE RULE: single continuous micro-story", prompt)
        self.assertIn("natural temporal and spatial continuity", prompt)
        self.assertIn("same mountain skyline", prompt)
        self.assertIn("teleporting between locations", prompt)

    def test_product_prompt_adds_category_continuity_to_every_industry(self):
        expected = {
            "Food": "same dish, kitchen or counter",
            "Real Estate": "same property, architecture, floor plan",
            "Dental": "same adult patient, clinician, clinic",
            "Fashion": "same garment, fabric, colour",
            "Beauty": "same product, packaging, adult model",
            "Automotive": "same vehicle, body, paint",
            "Technology": "same device or software task",
            "Travel": "same destination, property, landscape",
        }
        for industry, lock in expected.items():
            with self.subTest(industry=industry):
                prompt = app._creatorthon_product_prompt({
                    "category": industry,
                    "product": "Example",
                    "product_subtype": "Example product",
                    "product_visual_spec": {"subject": "one exact subject", "beats": ["reveal", "demonstrate", "finish"]},
                }, 15, "9:16")
                self.assertIn("single continuous product story", prompt)
                self.assertIn(lock, prompt)
                self.assertIn("Do not jump to a second location", prompt)

    def test_product_narration_honours_tamil_language(self):
        narration = app._creatorthon_product_narration({
            "category": "Travel",
            "product_subtype": "Mountain Escape",
            "narration_language": "Tamil",
        }, 15)
        self.assertIn("மறக்க முடியாத", narration)
        self.assertIn("பயணத்தை முன்பதிவு", narration)
        self.assertNotIn("Your next unforgettable experience", narration)

    def test_product_prompt_locks_dental_aligner_identity(self):
        prompt = app._creatorthon_product_prompt({
            "topic": "Clear Aligners",
            "category": "Dental",
            "product": "Invisible braces",
            "product_subtype": "Clear Aligners",
            "creative_style": "Product showcase",
            "style_direction": "Clinical product detail and a confident patient outcome",
            "campaign_goal": "Bookings",
            "target_audience": "Young adults",
            "visual_mood": "Clinical and trustworthy",
            "product_attributes": {"benefit": "Natural appearance", "stage": "Consultation"},
            "human_interaction": "A dentist consults and treats a clearly adult patient.",
            "product_visual_spec": {
                "subject": "transparent medical dental aligners fitted over natural teeth",
                "environment": "a bright modern dental clinic",
                "beats": ["orthodontist holds aligners beside a dental model", "patient fits aligner over natural teeth", "finish on a natural smile"],
                "avoid": ["gaming controllers", "electronics", "futuristic gadgets"],
            },
        }, 10, "9:16")
        self.assertIn("PRODUCT IDENTITY LOCK", prompt)
        self.assertIn("transparent medical dental aligners", prompt)
        self.assertIn("ABSOLUTELY DO NOT SHOW: gaming controllers", prompt)
        self.assertIn("never be reinterpreted as another object", prompt)
        self.assertIn("CONVERSION ARC", prompt)
        self.assertIn("premium paid social campaign", prompt)
        self.assertIn("MANDATORY PRODUCT ATTRIBUTES", prompt)
        self.assertIn("benefit: Natural appearance", prompt)
        self.assertIn("objective Bookings", prompt)
        self.assertIn("HUMAN PRESENTATION", prompt)
        self.assertIn("adult patient", prompt)
        self.assertIn("Never expose nipples or genitals", prompt)

    def test_product_prompt_removes_identity_sensitive_provider_triggers(self):
        prompt = app._provider_safe_product_prompt(
            "Beef where locally appropriate at a Tamil Muslim wedding-style counter"
        )
        self.assertEqual(prompt, "regional meat biryani at a traditional Tamil wedding-service counter")
        self.assertNotIn("Muslim", prompt)
        self.assertNotIn("Beef", prompt)

        catalog = (ROOT / "static" / "product-video-catalog.js").read_text(encoding="utf-8")
        self.assertIn("Regional meat biryani", catalog)
        self.assertIn("Traditional Tamil wedding-service counter", catalog)
        self.assertNotIn("Tamil Muslim wedding-style counter", catalog)

        retry = app._provider_safe_product_retry_prompt({
            "product": "Biryani",
            "product_subtype": "Chettinad Biryani",
            "target_audience": "Students",
            "product_attributes": {
                "protein": "Beef where locally appropriate",
                "stall": "Tamil Muslim wedding-style counter",
            },
        }, 15, "9:16")
        self.assertIn("street-food stall", retry)
        self.assertIn("rhythmically taps a large rice ladle", retry)
        self.assertIn("boiled egg", retry)
        self.assertNotIn("Students", retry)
        self.assertNotIn("Muslim", retry)
        self.assertNotIn("Beef", retry)

        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"sensitive information" in str(exc).casefold()', app_source)
        self.assertIn("Generating video with provider-safe direction", app_source)

    def test_v3_custom_domain_serves_v3_from_root(self):
        request = Request({
            "type": "http", "method": "GET", "scheme": "https", "path": "/", "query_string": b"",
            "headers": [(b"host", b"v3.viralizer.ai")], "server": ("v3.viralizer.ai", 443),
        })
        self.assertTrue(app._is_creatorthon_v3_host(request))
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn('if _is_creatorthon_v3_host(request) and is_v3_clean_route:', source)
        self.assertIn('return await creatorthon_v3_login(request, next="/")', source)

    def test_v3_clean_routes_support_refresh_and_browser_history(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        for route in ("/profile", "/topics/{category_slug:path}", "/markets/{source}", "/create/{topic_slug:path}", "/review/{project_id}", "/generating/{project_id}", "/result/{project_id}", "/project/{project_id}"):
            self.assertIn(f'@app.get("{route}")', app_source)
        self.assertIn("window.addEventListener('popstate'", page)
        self.assertIn("sessionStorage.setItem('viralizerV3RouteState'", page)
        self.assertIn("async function restoreBrowserRoute", page)
        self.assertIn("dashboardPromise=loadDashboard()", page)
        self.assertIn("if(dashboardPromise)await dashboardPromise", page)
        self.assertIn("const categoryTopicRequests=new Map()", page)
        self.assertIn("async function fetchCategoryTopics", page)

    def test_product_wizard_steps_are_refresh_safe(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        page = (ROOT / "static" / "creatorthon-product.html").read_text(encoding="utf-8")
        self.assertIn('@app.get("/product/{step:path}")', app_source)
        self.assertIn("const productSteps=['industry','product','type','style','details','campaign','direction','review']", page)
        self.assertIn("sessionStorage.setItem(productStorageKey", page)
        self.assertIn("window.addEventListener('popstate'", page)

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
        self.assertIn('href="/logout?next=/"', v3_page)

    def test_v3_contains_requested_creator_journey(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        for expected in (
            "your categories to create content",
            "Choose an output",
            "Create video",
            "/api/creatorthon/topics",
            "/api/video/prompt",
            "/api/video/generate",
        ):
            self.assertIn(expected, page)
        options = page.split("function renderOptions()", 1)[1].split("function beginObjective", 1)[0]
        self.assertNotIn("HEYGEN", options)
        self.assertNotIn("CHATGPT IMAGE", options)
        self.assertNotIn("TOPIC RESEARCH", options)
        self.assertEqual(options.count('<article class="option ready">'), 1)

    def test_v3_uses_official_logo_and_responsive_layout(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("/static/viralizer-logo-black.png", page)
        self.assertIn("Professional scale and alignment pass", page)
        self.assertIn("@media(max-width:960px)", page)
        self.assertIn("@media(max-width:680px)", page)

    def test_v3_uses_supplied_favicon(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertTrue((ROOT / "static" / "viralizer-v3-favicon-v2.png").is_file())
        self.assertIn('/static/viralizer-v3-favicon-v2.png?v=2', page)
        self.assertIn('/static/viralizer-v3-favicon-v2.png?v=2', app_source)

    def test_v3_uses_confirmation_gates_and_shows_video_results(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn('id="ownPromptButton"', page)
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
        self.assertIn("'alternate'", page)
        self.assertIn("function currentPrepared()", page)
        self.assertNotIn("prompt:(source.prompt||'')+configurationSuffix()", page)

    def test_custom_prompt_is_developed_and_stored_before_generation(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('id="developCustomPrompt"', page)
        self.assertIn("Developing your idea into a professional video prompt", page)
        self.assertIn("prompt_mode:promptMode", page)
        self.assertIn("prompt:'',custom_prompt_confirmed:state.promptMode==='custom'", page)
        self.assertIn('"custom-developed" if payload.prompt_mode == "custom"', app_source)
        self.assertIn('stored_prompt.get("mode") == "custom-developed"', app_source)
        self.assertIn("state.alternatePrepared=await compilePrompt(state.activeContent,idea.text,'alternate')", page)
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
        self.assertIn("/api/creatorthon/finish-async", page)
        self.assertIn("const finalVideoUrl=await finishV3Video(rawVideoUrl,provider,job)", page)
        self.assertIn("provider_job_id:providerJobId", page)
        self.assertNotIn("api('/api/creatorthon/finish'", page)
        self.assertIn("nativeSpeech=['heygen','hybrid'].includes(provider)", page)
        self.assertIn("narration=nativeSpeech?'':", page)
        self.assertIn("Open narrated finished video", page)

    def test_category_topics_load_progressively_with_visible_animation(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn("loading-orbit", page)
        self.assertIn("cat-card loading", page)
        self.assertIn("@keyframes shimmer", page)
        self.assertIn("state.loadingCategories=new Set(state.categories)", page)
        self.assertIn("show('home');let ready=state.categories.length-state.loadingCategories.size", page)
        self.assertIn("categories ready", page)
        self.assertIn("state.loadingCategories.delete(c)", page)

    def test_category_topic_lists_require_ten_items_and_keep_relevant_subcategories(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("cached.topics.length>=10", page)
        self.assertIn("topics=(d.topics||[]).slice(0,10)", page)
        self.assertNotIn("filter(t=>String(t.category||'').toLowerCase()===category.toLowerCase())", page)
        self.assertIn('CREATORTHON_TOPICS_PER_CATEGORY", "10"', app_source)
        self.assertIn("len(category_topics) < minimum_topics", app_source)

    def test_topic_selection_opens_one_proprietary_insight_panel_before_video_creation(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        self.assertIn('id="topicInsight" class="topic-insight" hidden', page)
        self.assertIn("Viralizer Proprietary Insights", page)
        self.assertIn("Refined MCP search term", page)
        self.assertIn("Value proposition", page)
        self.assertIn("Article Intelligence", page)
        self.assertIn("Viral Topic Rank", page)
        self.assertIn("Total Audience", page)
        self.assertIn("Est. Remaining Views", page)
        self.assertIn("Audience Insight", page)
        self.assertIn("Creator Insight", page)
        self.assertNotIn("Resonance", page)
        self.assertNotIn("Boost", page)
        self.assertIn("/api/creatorthon/insight-queue", page)
        self.assertIn("function closeTopicInsight()", page)
        self.assertIn("if(state.insightTopic)selectTopic(state.insightTopic)", page)
        self.assertIn(".insight-loading[hidden]", page)
        self.assertIn('id="insightContent" class="insight-content" hidden', page)

    def test_v3_exposes_event_review_and_publishing_controls(self):
        page = (ROOT / "static" / "creatorthon-v3.html").read_text(encoding="utf-8")
        for expected in (
            "/api/creatorthon/event-status",
            'id="eventStatus"',
            'id="adminLink"',
            'id="ownPromptButton"',
            'id="topicAlignment"',
            'id="reviewDuration"',
            'id="reviewAspect"',
            'id="reviewPlatform"',
            'id="reviewSpeech"',
            'id="reviewCaption"',
            'id="reviewHashtags"',
            "/api/creatorthon/hashtags",
            "/api/creatorthon/youtube/status",
            'id="publishVideo"',
            "YouTube URL:",
        ):
            self.assertIn(expected, page)
        self.assertIn("custom_prompt_confirmed:state.promptMode==='custom'", page)
        self.assertIn("speech_script_reviewed:$('#speechReviewed').checked", page)
        self.assertIn("hashtags_reviewed:$('#hashtagsReviewed').checked", page)
        self.assertIn("topic_mismatch_acknowledged:", page)
        self.assertIn("duration:state.duration", page)
        self.assertIn("aspect_ratio:state.aspectRatio", page)


if __name__ == "__main__":
    unittest.main()
