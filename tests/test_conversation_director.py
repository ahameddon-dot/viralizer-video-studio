import unittest

from conversation import director as d


def user(text):
    return {"role": "user", "content": {"type": "text", "text": text}}


def tool(name, data, status="completed"):
    return {"role": "tool", "content": {"tool": name, "call_id": "c", "output": {"status": status, "tool": name, "data": data}}}


def produced(name, index, media="https://x/y.png", status="completed"):
    return {"role": "assistant", "content": {"type": "tool_result", "tool": name, "media_url": media,
                                             "result": {"scene_index": index, "status": status}}}


OPPS = [
    {"id": "o1", "title": "AI video tools hit mainstream", "category": "Tech", "score": 82.5, "rationale": "High brand fit.",
     "components": {"viral_rank": 3}, "source": {}},
    {"id": "o2", "title": "Small business automation boom", "category": "Business", "score": 77.0, "rationale": "Strong impact.",
     "components": {}, "source": {}},
    {"id": "o3", "title": "Short-form SEO shift", "category": "Marketing", "score": 70.1, "rationale": "Good timing.",
     "components": {}, "source": {}},
]


def concept(scenes=3):
    return {"id": "k1", "opportunity_id": "o1", "name": "Fast Insight",
            "content": {"title": "Fast Insight", "duration_seconds": 15,
                        "storyboard": [{"start": i * 5, "end": i * 5 + 5, "purpose": "p", "narration": f"line {i + 1}"} for i in range(scenes)]}}


class StageTests(unittest.TestCase):
    def test_onboarding_until_brand_confirmed(self):
        self.assertEqual(d.ONBOARDING, d.derive_state([], False).stage)
        self.assertEqual(d.DISCOVER, d.derive_state([], True).stage)

    def test_full_journey(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS})]
        self.assertEqual(d.CHOOSE_TOPIC, d.derive_state(msgs, True).stage)
        msgs.append(tool("create_concepts", {"concepts": [concept()]}))
        state = d.derive_state(msgs, True)
        self.assertEqual(d.STORYBOARD, state.stage)
        self.assertEqual(3, state.scene_count)
        self.assertEqual("o1", state.selected_opportunity["id"])
        msgs += [produced("generate_keyframe", i) for i in range(3)]
        state = d.derive_state(msgs, True)
        self.assertEqual(d.IMAGES, state.stage)
        self.assertTrue(state.images_ready)
        msgs += [produced("animate_scene", i, media="", status="started") for i in range(3)]
        self.assertEqual(d.ANIMATING, d.derive_state(msgs, True).stage)
        msgs.append(produced("finalize_video", 0, media="https://x/final.mp4"))
        self.assertEqual(d.FINAL, d.derive_state(msgs, True).stage)

    def test_new_ranking_resets_downstream_state(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}), tool("create_concepts", {"concepts": [concept()]}),
                produced("generate_keyframe", 0), tool("rank_opportunities", {"opportunities": OPPS[:2]})]
        state = d.derive_state(msgs, True)
        self.assertEqual(d.CHOOSE_TOPIC, state.stage)
        self.assertEqual({}, state.keyframes)
        self.assertEqual(2, len(state.opportunities))

    def test_failed_tool_does_not_advance_state(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}, status="failed")]
        self.assertEqual(d.DISCOVER, d.derive_state(msgs, True).stage)

    def test_final_publish_flow_remembers_platform_and_advances_one_question(self):
        msgs = [tool("create_concepts", {"concepts": [concept(2)]}),
                produced("generate_keyframe", 0), produced("generate_keyframe", 1),
                produced("finalize_video", 0, media="https://x/final.mp4"),
                user("I approve the final video. Ask which connected platform to publish it to.")]
        state = d.derive_state(msgs, True)
        self.assertEqual("platform", state.publication_step)
        self.assertIn("Instagram", [item["label"] for item in d.suggested_replies(state)])

        msgs.append(user("instagaram"))
        state = d.derive_state(msgs, True)
        self.assertEqual("instagram", state.publish_platform)
        self.assertEqual("caption", state.publication_step)
        self.assertEqual("Write caption for me", d.suggested_replies(state)[0]["label"])

        msgs.append(user("Write the Instagram caption for me according to this video."))
        state = d.derive_state(msgs, True)
        self.assertEqual("__ai__", state.publish_caption)
        self.assertEqual("timing", state.publication_step)
        self.assertEqual("Post now", d.suggested_replies(state)[0]["label"])

        msgs.append(user("Post it now."))
        state = d.derive_state(msgs, True)
        self.assertEqual("now", state.publish_timing)
        self.assertEqual("approval", state.publication_step)

        # Repeating approval must not erase the destination or completed post details.
        msgs.append(user("I approve the final video. Ask me which connected platform to publish it to."))
        state = d.derive_state(msgs, True)
        self.assertEqual("instagram", state.publish_platform)
        self.assertEqual("approval", state.publication_step)


class TranscriptReplayTests(unittest.TestCase):
    """The three real failures from the handoff transcripts."""

    def setUp(self):
        self.msgs = [tool("rank_opportunities", {"opportunities": OPPS})]
        self.state = d.derive_state(self.msgs, True)

    def test_why_is_the_first_topic_best_is_grounded(self):
        turn = d.director_turn(self.msgs + [user("Why is the first topic best?")], True, "Why is the first topic best?")
        self.assertEqual(d.ASK_ABOUT_OPPORTUNITIES, turn["intent"])
        self.assertEqual("o1", turn["refs"]["opportunity"]["id"])
        self.assertIn("AI video tools hit mainstream", turn["context"])
        self.assertIn("Never ask the customer to restate", turn["context"])

    def test_compare_these_opportunities_is_grounded(self):
        turn = d.director_turn(self.msgs, True, "Compare these opportunities")
        self.assertEqual(d.ASK_ABOUT_OPPORTUNITIES, turn["intent"])
        for item in OPPS:
            self.assertIn(item["title"], turn["context"])

    def test_reddit_question_is_off_topic_and_steered_back(self):
        text = "Why does Reddit want me to use the iOS app on my desktop?"
        turn = d.director_turn(self.msgs, True, text)
        self.assertEqual(d.OFF_TOPIC, turn["intent"])
        self.assertIn("steer back", turn["context"])

    def test_what_did_we_learn_routes_to_results(self):
        self.assertEqual(d.SHOW_RESULTS, d.classify_intent("What did we learn?", self.state))

    def test_empty_discovery_is_flagged_not_dead_end(self):
        empty = [tool("discover_topics", {"topics": []})]
        state = d.derive_state(empty, True)
        self.assertTrue(state.discovery_empty)
        turn = d.director_turn(empty, True, "give top 3 topics")
        self.assertEqual(d.FIND_TRENDS, turn["intent"])
        self.assertIn("fallback", turn["context"])
        self.assertIn("returned nothing", turn["context"])


class ReferenceAndIntentTests(unittest.TestCase):
    def setUp(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}), tool("create_concepts", {"concepts": [concept()]})]
        self.state = d.derive_state(msgs, True)

    def test_ordinals_and_hash(self):
        state = d.derive_state([tool("rank_opportunities", {"opportunities": OPPS})], True)
        self.assertEqual("o2", d.resolve_references("go with the second one", state)["opportunity"]["id"])
        self.assertEqual("o3", d.resolve_references("what about #3", state)["opportunity"]["id"])
        self.assertEqual("o3", d.resolve_references("the last one", state)["opportunity"]["id"])

    def test_scene_edit_resolves_scene(self):
        refs = d.resolve_references("Make scene 2 more dramatic", self.state)
        self.assertEqual(1, refs["scene_index"])
        self.assertEqual(d.EDIT_SCENE, d.classify_intent("Make scene 2 more dramatic", self.state))

    def test_out_of_range_scene_is_ignored(self):
        self.assertNotIn("scene_index", d.resolve_references("change scene 9", self.state))

    def test_whole_video_edit(self):
        self.assertEqual(d.EDIT_WHOLE, d.classify_intent("make the whole video funnier", self.state))

    def test_confirmations(self):
        for text in ("yes", "Go ahead", "looks good", "The images are approved. Create the video."):
            self.assertEqual(d.CONFIRM, d.classify_intent(text, self.state), text)

    def test_duration_parsing(self):
        self.assertEqual(10, d.parse_duration("make it 10 seconds"))
        self.assertEqual(30, d.parse_duration("a 30s video"))
        self.assertIsNone(d.parse_duration("make it 90 seconds"))
        self.assertIsNone(d.parse_duration("make it 2 seconds"))


class ScenePlanTests(unittest.TestCase):
    def test_plans_are_whole_five_second_scenes(self):
        for seconds, scenes, total in ((5, 1, 5), (10, 2, 10), (15, 3, 15), (30, 6, 30), (60, 12, 60), (12, 3, 15), (1, 1, 5), (500, 12, 60)):
            plan = d.scene_plan(seconds)
            self.assertEqual(scenes, len(plan), seconds)
            self.assertEqual(total, plan[-1][1], seconds)
            self.assertEqual(0, plan[0][0])
            for (_, end), (start, _) in zip(plan, plan[1:]):
                self.assertEqual(end, start)
            self.assertTrue(all(end - start == 5 for start, end in plan))

    def test_bad_input_defaults_to_fifteen(self):
        self.assertEqual(15, d.normalize_duration("abc"))
        self.assertEqual(15, d.normalize_duration(None))


class DurationFlowTests(unittest.TestCase):
    def test_custom_idea_brief_is_one_question_at_a_time(self):
        msgs = [user("I have my own idea")]
        state = d.derive_state(msgs, True)
        self.assertEqual("idea", state.brief_step)
        msgs.append(user("A Rolex watch transforms into a horse"))
        self.assertEqual("duration", d.derive_state(msgs, True).brief_step)
        msgs.append(user("Make it 15 seconds"))
        self.assertEqual("narration", d.derive_state(msgs, True).brief_step)
        msgs.append(user("Write the narration for me according to the content"))
        self.assertEqual("style", d.derive_state(msgs, True).brief_step)
        msgs.append(user("Use a cinematic visual style"))
        self.assertEqual("platform", d.derive_state(msgs, True).brief_step)
        msgs.append(user("Create it for YouTube Shorts in 9:16"))
        state = d.derive_state(msgs, True)
        self.assertEqual("ready", state.brief_step)
        self.assertEqual("A Rolex watch transforms into a horse", state.custom_idea)
        self.assertEqual("youtube", state.target_platform)
        self.assertEqual("9:16", state.aspect_ratio)

    def test_own_idea_never_requires_a_trend_or_opportunity_id(self):
        msgs = [user("I have my own idea"), user("Rolex watch transforms to a horse")]
        state = d.derive_state(msgs, True)
        self.assertEqual("Rolex watch transforms to a horse", state.custom_idea)
        self.assertEqual(d.CREATE_FROM_IDEA, d.classify_intent("proceed", state))
        context = d.build_context(state, d.CREATE_FROM_IDEA, {})
        self.assertIn("Never ask for an opportunity ID", context)

    def test_create_from_idea_advances_to_storyboard(self):
        idea_concept = concept()
        idea_concept["opportunity_id"] = "idea-o1"
        msgs = [user("I have my own idea"), user("Rolex watch transforms to a horse"),
                tool("create_from_idea", {"concepts": [idea_concept]})]
        state = d.derive_state(msgs, True)
        self.assertEqual(d.STORYBOARD, state.stage)
        self.assertFalse(state.idea_mode_requested)
        self.assertEqual("", state.custom_idea)

    def test_old_model_rejection_is_recovered_as_custom_idea(self):
        assistant = {"role": "assistant", "content": {"type": "text", "text":
            "Since your idea is custom, I cannot create concepts without an existing ranked opportunity."}}
        msgs = [user("Rolex watch transforms to horse"), assistant, user("yes")]
        state = d.derive_state(msgs, True)
        self.assertTrue(state.idea_mode_requested)
        self.assertEqual("Rolex watch transforms to horse", state.custom_idea)
        self.assertEqual(d.CREATE_FROM_IDEA, d.classify_intent("yes", state))

    def test_selected_topic_without_length_asks_for_length(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}), user("I select this opportunity: X. Use opportunity ID o2. Create it.")]
        state = d.derive_state(msgs, True)
        self.assertEqual("o2", state.selected_opportunity["id"])
        labels = [c["label"] for c in d.suggested_replies(state)]
        self.assertEqual(["5 seconds", "10 seconds", "15 seconds", "30 seconds", "60 seconds"], labels)
        self.assertIn("not chosen a video length", d.build_context(state, d.GENERAL, {}))

    def test_stated_length_tells_model_to_create_with_that_duration(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}), user("Use opportunity ID o1"), user("Make it 30 seconds.")]
        context = d.build_context(d.derive_state(msgs, True), d.SET_DURATION, {})
        self.assertIn("duration_seconds=30", context)
        self.assertIn("6 scenes", context)

    def test_rebuild_offer_when_length_differs_from_existing_storyboard(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}), tool("create_concepts", {"concepts": [concept()]}), user("Make it 30 seconds.")]
        context = d.build_context(d.derive_state(msgs, True), d.SET_DURATION, {})
        self.assertIn("offer to rebuild", context)


class RevisionStateTests(unittest.TestCase):
    def base(self):
        msgs = [tool("rank_opportunities", {"opportunities": OPPS}), tool("create_concepts", {"concepts": [concept()]})]
        msgs += [produced("generate_keyframe", i) for i in range(3)]
        msgs += [produced("animate_scene", i, media="", status="started") for i in range(3)]
        return msgs

    def test_revising_one_scene_invalidates_only_that_scene(self):
        revised = concept(); revised["content"]["storyboard"][1]["narration"] = "new line"
        msgs = self.base() + [tool("revise_storyboard", {"concept": revised, "changed_scenes": [1], "stale_images": [1]})]
        state = d.derive_state(msgs, True)
        self.assertEqual([1], state.missing_images)
        self.assertEqual({0, 2}, set(state.keyframes))
        self.assertEqual({0, 2}, set(state.animations))
        self.assertEqual("new line", state.scenes[1]["narration"])
        context = d.build_context(state, d.EDIT_SCENE, {})
        self.assertIn("still need a new image", context)
        self.assertIn("ONLY these", context)

    def test_whole_video_edit_invalidates_everything(self):
        msgs = self.base() + [tool("revise_storyboard", {"concept": concept(), "changed_scenes": [0, 1, 2], "stale_images": [0, 1, 2]})]
        state = d.derive_state(msgs, True)
        self.assertEqual([0, 1, 2], state.missing_images)
        self.assertEqual(d.STORYBOARD, state.stage)

    def test_stale_scene_offers_targeted_regeneration(self):
        msgs = self.base() + [tool("revise_storyboard", {"concept": concept(), "changed_scenes": [1], "stale_images": [1]})]
        chips = d.suggested_replies(d.derive_state(msgs, True))
        self.assertIn("scene 2", chips[0]["label"])
        self.assertIn("only", chips[0]["prompt"])

    def test_revision_of_other_concept_is_ignored(self):
        other = concept(); other["id"] = "other"
        msgs = self.base() + [tool("revise_storyboard", {"concept": other, "changed_scenes": [0], "stale_images": [0]})]
        self.assertEqual([], d.derive_state(msgs, True).missing_images)


class FallbackTests(unittest.TestCase):
    def test_brand_seeds_are_honest_and_grounded(self):
        profile = {"profile": {"keywords": ["AI video"], "audiences": ["small business owners"], "products_services": ["content automation"]}}
        seeds = d.brand_seed_topics(profile, 4)
        self.assertEqual(4, len(seeds))
        self.assertTrue(all(s["is_live_trend"] is False for s in seeds))
        self.assertTrue(all("Not a live trend" in s["summary"] for s in seeds))
        self.assertIn("small business owners", seeds[0]["title"])

    def test_empty_profile_returns_nothing_instead_of_inventing(self):
        self.assertEqual([], d.brand_seed_topics({"profile": {}}, 5))


class SuggestionTests(unittest.TestCase):
    def test_every_stage_has_replies(self):
        for stage in d.STAGES:
            state = d.DirectorState(stage=stage, concept_id="k1")
            self.assertTrue(d.suggested_replies(state), stage)

    def test_context_never_leaks_instructions_to_customer(self):
        turn = d.director_turn([], True, "hello")
        self.assertIn("Never expose IDs", turn["context"])


if __name__ == "__main__":
    unittest.main()


