import unittest

from human_reference_identity import (
    build_human_reference_identity_spec,
    compile_human_reference_prompt,
    human_reference_identity_decision,
)


def fatima_shot():
    return {
        "visual_subject": "the article-supported martial arts performer holding eggs",
        "composition": "medium view with both hands visible",
        "environment": "neutral background",
        "visual_description": "The performer prepares the supported punching feat while holding eggs.",
    }


def evidence():
    return {
        "headline": "13-year-old martial arts star Fatima completes a record",
        "article_body": "She held eggs in her hands and delivered punches.",
    }


class HumanReferenceIdentityTests(unittest.TestCase):
    def test_fatima_spec_uses_approved_gender_age_and_single_subject(self):
        spec = build_human_reference_identity_spec(fatima_shot(), evidence())
        self.assertEqual(spec["gender_presentation"], "female")
        self.assertEqual(spec["age_band"], "adolescent")
        self.assertEqual(spec["subject_count"], 1)

    def test_prompt_places_identity_before_generic_role_and_composition(self):
        spec = build_human_reference_identity_spec(fatima_shot(), evidence())
        prompt, negative = compile_human_reference_prompt(spec, "Reference start frame.")
        self.assertTrue(prompt.startswith("IDENTITY PRIORITY ONE"))
        self.assertLess(prompt.index("female-presenting"), prompt.index("WARDROBE"))
        self.assertLess(prompt.index("WARDROBE"), prompt.index("HANDS"))
        self.assertIn("no adult male subject", negative)

    def test_any_identity_gate_failure_is_fatal_before_semantic_qc(self):
        result = {"available": True, "SUBJECT_COUNT_MATCH": "PASS", "GENDER_PRESENTATION_MATCH": "FAIL"}
        decision = human_reference_identity_decision(result, 0, 3)
        self.assertEqual(decision["status"], "REFERENCE_IDENTITY_FAIL")
        self.assertTrue(decision["retry"])

    def test_reference_provider_limit_after_two_retries(self):
        result = {"available": True}
        decision = human_reference_identity_decision(result, 2, 3)
        self.assertEqual(decision["status"], "REFERENCE_PROVIDER_IDENTITY_LIMITATION")
        self.assertFalse(decision["retry"])

    def test_missing_human_evidence_does_not_invent_identity(self):
        spec = build_human_reference_identity_spec({"visual_subject": "electric car"}, {"headline": "New car launch"})
        self.assertEqual(spec, {})


if __name__ == "__main__":
    unittest.main()
