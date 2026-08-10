import unittest
from types import SimpleNamespace

from app.services.result_service import fleiss_agreement_stats


MOCK_RATINGS = [
    ("MULTIPLE_CHOICE", (1, 1, 1)),
    ("MULTIPLE_CHOICE", (1, 0, 1)),
    ("MULTIPLE_CHOICE", (1, 1, 0)),
    ("MULTIPLE_CHOICE", (0, 1, 1)),
    ("MULTIPLE_CHOICE", (0, 0, 0)),
    ("MULTIPLE_CHOICE", (1, 1, 1)),
    ("MULTIPLE_CHOICE", (1, 0, 0)),
    ("MULTIPLE_CHOICE", (0, 0, 1)),
    ("MULTIPLE_CHOICE", (0, 1, 0)),
    ("MULTIPLE_CHOICE", (1, 1, 1)),
    ("SHORT_ANSWER", (1, 0, 1)),
    ("SHORT_ANSWER", (1, 1, 1)),
    ("SHORT_ANSWER", (0, 0, 0)),
    ("SHORT_ANSWER", (1, 1, 0)),
    ("SHORT_ANSWER", (0, 1, 1)),
]


def record(output_type, ratings, marker):
    main, blind, reviewer = ratings
    return SimpleNamespace(
        output_type=output_type,
        main_annotator={"decision": main},
        blind_annotator={"decision": blind},
        reviewer={"decision": reviewer},
        question={"question_text": marker, "option_A": "irrelevant"},
        answer="irrelevant",
        image_id=f"image-{marker}",
        categories=999,
        slide_type=999,
        language=999,
    )


class FleissKappaTests(unittest.TestCase):
    def setUp(self):
        self.records = [record(output_type, ratings, index) for index, (output_type, ratings) in enumerate(MOCK_RATINGS)]

    def test_three_scopes_use_actual_three_rater_observations(self):
        all_stats = fleiss_agreement_stats(self.records)
        mc_stats = fleiss_agreement_stats([row for row in self.records if row.output_type == "MULTIPLE_CHOICE"])
        sa_stats = fleiss_agreement_stats([row for row in self.records if row.output_type == "SHORT_ANSWER"])

        self.assertEqual(all_stats["total_records"], 15)
        self.assertEqual(all_stats["observations"], 15)
        self.assertEqual(all_stats["total_ratings"], 45)
        self.assertEqual(mc_stats["total_records"], 10)
        self.assertEqual(mc_stats["observations"], 10)
        self.assertEqual(mc_stats["total_ratings"], 30)
        self.assertEqual(sa_stats["total_records"], 5)
        self.assertEqual(sa_stats["observations"], 5)
        self.assertEqual(sa_stats["total_ratings"], 15)

    def test_label_distributions_match_mock_data(self):
        expected = {"label_0": 6, "label_1": 9}
        for stats in (
            fleiss_agreement_stats(self.records),
            fleiss_agreement_stats(self.records[:10]),
            fleiss_agreement_stats(self.records[10:]),
        ):
            self.assertEqual(stats["annotators"]["main"], expected if stats["total_records"] == 15 else {"label_0": 4 if stats["total_records"] == 10 else 2, "label_1": 6 if stats["total_records"] == 10 else 3})
            self.assertEqual(stats["annotators"]["blind"], stats["annotators"]["main"])
            self.assertEqual(stats["annotators"]["reviewer"], stats["annotators"]["main"])

    def test_standard_fleiss_formula_and_global_not_average(self):
        all_stats = fleiss_agreement_stats(self.records)
        mc_stats = fleiss_agreement_stats(self.records[:10])
        sa_stats = fleiss_agreement_stats(self.records[10:])

        self.assertAlmostEqual(all_stats["p_observed"], 0.6)
        self.assertAlmostEqual(all_stats["p_expected"], 0.52)
        self.assertAlmostEqual(all_stats["fleiss_kappa"], 0.1666666667)
        # This particular mock gives both scopes the same value by coincidence;
        # the direct P_o/P_e assertions prove the global matrix was used.
        self.assertAlmostEqual(
            (all_stats["p_observed"] - all_stats["p_expected"])
            / (1 - all_stats["p_expected"]),
            all_stats["fleiss_kappa"],
        )
        self.assertEqual(all_stats["total_ratings"], all_stats["observations"] * 3)
        self.assertAlmostEqual(all_stats["p_expected"], 0.4**2 + 0.6**2)

    def test_content_fields_do_not_affect_kappa(self):
        changed = [record(row.output_type, MOCK_RATINGS[index][1], f"different-{index}") for index, row in enumerate(self.records)]
        self.assertEqual(
            fleiss_agreement_stats(self.records)["fleiss_kappa"],
            fleiss_agreement_stats(changed)["fleiss_kappa"],
        )


if __name__ == "__main__":
    unittest.main()
