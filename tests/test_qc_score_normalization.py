import unittest

from qc_score_normalization import normalize_qc_scores


class QCScoreNormalizationTests(unittest.TestCase):
    def test_explicit_zero_to_one_scale(self):
        result = normalize_qc_scores({"overall_quality_score": 0.86, "score_scale": "0-1"})
        self.assertEqual(result["raw_score"], 0.86)
        self.assertEqual(result["normalized_score"], 86)
        self.assertEqual(result["detected_scale"], "0-1")

    def test_fractional_zero_to_one_scale_is_safely_detected(self):
        result = normalize_qc_scores({"overall_quality_score": 0.9, "visual_quality": 0.8})
        self.assertEqual(result["overall_quality_score"], 90)
        self.assertEqual(result["visual_quality"], 80)
        self.assertEqual(result["detected_scale"], "0-1")

    def test_explicit_zero_to_ten_scale(self):
        result = normalize_qc_scores({"overall_quality_score": 8, "score_scale": "0-10"})
        self.assertEqual(result["normalized_score"], 80)
        self.assertEqual(result["detected_scale"], "0-10")

    def test_ten_with_unanimous_pass_context_normalizes_to_one_hundred(self):
        result = normalize_qc_scores({
            "overall_quality_score": 10,
            "APPROVED_S1_ACTION_ONLY": "PASS",
            "TECHNICAL_QUALITY_ACCEPTABLE": "PASS",
            "issues": [],
        })
        self.assertEqual(result["raw_score"], 10)
        self.assertEqual(result["normalized_score"], 100)
        self.assertEqual(result["overall_quality_score"], 100)
        self.assertEqual(result["detected_scale"], "0-10")

    def test_zero_to_one_hundred_is_preserved(self):
        result = normalize_qc_scores({"overall_quality_score": 92, "visual_quality": 88})
        self.assertEqual(result["overall_quality_score"], 92)
        self.assertEqual(result["detected_scale"], "0-100")

    def test_ambiguous_low_integer_is_not_converted(self):
        result = normalize_qc_scores({"overall_quality_score": 7})
        self.assertEqual(result["overall_quality_score"], 7)
        self.assertIsNone(result["normalized_score"])
        self.assertEqual(result["score_normalization_status"], "SCORE_SCALE_AMBIGUOUS")

    def test_out_of_range_score_is_ambiguous(self):
        result = normalize_qc_scores({"overall_quality_score": 120})
        self.assertIsNone(result["normalized_score"])
        self.assertEqual(result["detected_scale"], "SCORE_SCALE_AMBIGUOUS")

    def test_categorical_results_are_not_modified(self):
        result = normalize_qc_scores({
            "overall_quality_score": 10,
            "SAME_PERSON": "PASS",
            "GENDER_PRESENTATION_PRESERVED": "PASS",
            "failure_reasons": [],
        })
        self.assertEqual(result["SAME_PERSON"], "PASS")
        self.assertEqual(result["GENDER_PRESENTATION_PRESERVED"], "PASS")


if __name__ == "__main__":
    unittest.main()
