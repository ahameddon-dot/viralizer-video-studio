import unittest

from creative_story_qc import creative_qc_authority, creative_qc_instruction, normalize_creative_qc


def result(**overrides):
    value = {
        "viewer_inferred_story": "A historically meaningful dress returns from isolation into public attention.",
        "subject_clarity": 90,
        "story_progression": 82,
        "shot_progression": [
            {"shot_id": "S1", "new_meaning": "isolated artifact", "adds_new_meaning": True},
            {"shot_id": "S2", "new_meaning": "threshold into public display", "adds_new_meaning": True},
            {"shot_id": "S3", "new_meaning": "renewed public significance", "adds_new_meaning": True},
        ],
        "visual_semantic_coverage": {"overall_score": 80, "communicated": ["subject", "return to public attention", "cultural significance"], "partial": ["empowerment"], "weak_or_missing": []},
        "article_specificity": 80,
        "visual_impact": 84,
        "visual_continuity": 90,
        "narrative_progression": 82,
        "environmental_storytelling": 78,
        "generic_ad_risk": 20,
        "fake_information_panel_detected": False,
        "model_final_story_pass": "PASS",
        "failure_reasons": [],
    }
    value.update(overrides)
    return value


class CreativeStoryQCTests(unittest.TestCase):
    def test_technically_good_generic_exhibition_video_fails(self):
        qc = normalize_creative_qc(result(
            viewer_inferred_story="An elegant black dress displayed in a museum gallery.",
            subject_clarity=96,
            visual_continuity=94,
            story_progression=38,
            narrative_progression=35,
            environmental_storytelling=42,
            article_specificity=40,
            generic_ad_risk=82,
            visual_semantic_coverage={"overall_score": 43, "communicated": ["black dress"], "partial": ["public exhibition"], "weak_or_missing": ["historical significance", "empowerment", "resilience"]},
            model_final_story_pass="PASS",
        ))
        self.assertEqual(qc["final_story_pass"], "FAIL")
        self.assertTrue(qc["checks"]["subject_clear"])
        self.assertFalse(qc["checks"]["story_progresses"])
        self.assertFalse(qc["checks"]["not_generic_ad"])

    def test_strong_visual_story_can_pass(self):
        self.assertEqual(normalize_creative_qc(result())["final_story_pass"], "PASS")

    def test_fake_information_panel_blocks_pass(self):
        qc = normalize_creative_qc(result(fake_information_panel_detected=True, fake_information_panel_detail="Unreadable museum wall plaque"))
        self.assertEqual(qc["final_story_pass"], "FAIL")
        self.assertFalse(qc["checks"]["no_fake_information_panel"])

    def test_repeated_wider_shots_are_not_progression(self):
        shots = [
            {"shot_id": "S1", "new_meaning": "dress", "adds_new_meaning": True},
            {"shot_id": "S2", "new_meaning": "same dress, wider", "adds_new_meaning": False},
            {"shot_id": "S3", "new_meaning": "same dress, wider again", "adds_new_meaning": False},
        ]
        qc = normalize_creative_qc(result(shot_progression=shots))
        self.assertEqual(qc["final_story_pass"], "FAIL")
        self.assertFalse(qc["checks"]["each_later_shot_adds_meaning"])

    def test_authority_exempts_exact_facts_but_keeps_primary_meaning(self):
        authority = creative_qc_authority(
            {"core_message": "The dress returns to public attention as a symbol of empowerment.", "viewer_takeaway": "Its meaning exceeds fashion."},
            {"visual_message": "Isolation becomes public significance.", "core_visual_subject": "Revenge Dress"},
        )
        self.assertIn("auction price", authority["facts_not_required_visually"])
        self.assertIn("empowerment", authority["core_message"])

    def test_instruction_demands_uninformed_viewer_and_generic_ad_detection(self):
        instruction = creative_qc_instruction("complete final video")
        self.assertIn("know NOTHING", instruction)
        self.assertIn("generic luxury advertisement", instruction)
        self.assertIn("Camera distance", instruction)

    def test_counted_achievement_does_not_fail_only_because_count_is_not_generated(self):
        storyboard = [{
            "visual_description": "The athlete punches rapidly while holding two fragile objects.",
            "action": "She completes the sequence and both objects remain intact.",
            "environment": "training room",
            "composition": "action remains readable",
            "foreground": "",
            "background": "",
            "must_show": [],
        }]
        qc = normalize_creative_qc(
            result(
                visual_semantic_coverage={"overall_score": 65, "communicated": ["distinctive feat"], "partial": ["count"], "weak_or_missing": ["numeric count"]},
                model_final_story_pass="FAIL",
                muted_primary_visual_story_pass="FAIL",
                failure_reasons=["The numeric record count is not visible."],
            ),
            coverage_target=70,
            storyboard=storyboard,
            authority={
                "story_type": "PERSON_ACTION",
                "core_visual_subject": "athlete",
                "achievement_representation": {
                    "visually_demonstrated": ["athlete punches rapidly while holding two fragile objects"],
                    "controlled_text_dependent": ["10 records"],
                },
            },
        )
        self.assertTrue(qc["achievement_allocation_override"])
        self.assertEqual(qc["final_story_pass"], "PASS")


if __name__ == "__main__":
    unittest.main()
