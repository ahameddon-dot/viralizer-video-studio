import unittest

from human_identity_lock import (
    IDENTITY_QC_FIELDS,
    apply_human_identity_lock,
    fallback_human_identity_lock,
    identity_qc_decision,
    normalize_human_identity_lock,
    shot_contains_human,
)


def human_shot():
    return {
        "approved_storyboard_shot": {
            "visual_subject": "the article-supported female martial arts performer holding eggs",
            "visual_description": "The 13-year-old performer begins the supported movement.",
            "source_support": ["She held eggs while delivering the supported punches."],
        },
        "shot_specification": {
            "core_subject": "martial arts performer",
            "subjects": ["one female martial arts performer", "eggs held in both hands"],
        },
    }


def pass_result(**changes):
    result = {"available": True, **{field: "PASS" for field in IDENTITY_QC_FIELDS}}
    result.update(changes)
    return result


class HumanIdentityLockTests(unittest.TestCase):
    def test_approved_human_reference_is_authoritative_identity(self):
        lock = fallback_human_identity_lock(human_shot())
        self.assertEqual(lock["source_of_truth"], "approved_reference_image")
        self.assertEqual(lock["gender_presentation"], "female-presenting")
        self.assertIn("approved reference", lock["face_visibility_requirements"])
        conflict = normalize_human_identity_lock(
            {"gender_presentation": "male", "approximate_age_band": "25-35 years"},
            human_shot(),
        )
        self.assertTrue(conflict["identity_authority_conflict"])

    def test_generic_noun_cannot_replace_locked_person(self):
        lock = fallback_human_identity_lock(human_shot())
        prompt = apply_human_identity_lock(
            "Create one shot centered strictly on a martial artist. The athlete raises both hands.",
            lock,
        )
        self.assertTrue(prompt.startswith("Animate the exact person shown in the supplied approved reference image."))
        self.assertIn("centered strictly on the exact person in the approved reference image", prompt)
        self.assertNotIn("centered strictly on a martial artist", prompt)

    def test_gender_drift_is_detected_before_later_qc(self):
        result = identity_qc_decision(pass_result(GENDER_PRESENTATION_PRESERVED="FAIL"), 0, 2)
        self.assertEqual(result["status"], "IDENTITY_DRIFT")
        self.assertIn("GENDER_PRESENTATION_PRESERVED", result["failed_checks"])

    def test_face_and_wardrobe_drift_are_detected(self):
        result = identity_qc_decision(pass_result(FACE_PRESERVED="FAIL", CLOTHING_PRESERVED="FAIL"), 0, 2)
        self.assertEqual(result["status"], "IDENTITY_DRIFT")
        self.assertEqual(result["failed_checks"], ["FACE_PRESERVED", "CLOTHING_PRESERVED"])

    def test_extra_person_is_rejected(self):
        result = identity_qc_decision(pass_result(SUBJECT_COUNT_PRESERVED="FAIL"), 0, 2)
        self.assertEqual(result["status"], "IDENTITY_DRIFT")
        self.assertIn("SUBJECT_COUNT_PRESERVED", result["failed_checks"])

    def test_identity_drift_routes_to_same_shot_retry(self):
        result = identity_qc_decision(pass_result(SAME_PERSON="FAIL"), 0, 2)
        self.assertTrue(result["retry"])
        self.assertEqual(result["status"], "IDENTITY_DRIFT")

    def test_provider_identity_limitation_after_retry_cap(self):
        result = identity_qc_decision(pass_result(SAME_PERSON="FAIL"), 1, 2)
        self.assertFalse(result["retry"])
        self.assertEqual(result["status"], "PROVIDER_IDENTITY_LIMITATION")

    def test_non_human_shot_is_unaffected(self):
        shot = {"shot_specification": {"core_subject": "an electric car", "subjects": ["one car", "road"]}}
        self.assertFalse(shot_contains_human(shot))
        self.assertEqual(apply_human_identity_lock("The car accelerates.", {}), "The car accelerates.")


if __name__ == "__main__":
    unittest.main()
