import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from app.models.task import OutputType
from app.routers.document import SLIDE_NAME_PATTERN, generated_image_id, validate_question
from app.schemas.document import DriveLinkInput, SlideAnnotationInput
from app.services.result_service import final_dataset_records, flatten_record, fleiss_agreement_stats
from app.services.gemini_service import generate_annotation


class Milestone3ValidationTests(unittest.TestCase):
    def test_backend_generates_stable_page_ids(self):
        self.assertEqual(generated_image_id("cake", 1), "cake_page_01")
        self.assertEqual(generated_image_id("cake", 10), "cake_page_10")
        self.assertEqual(generated_image_id("cake", 100), "cake_page_100")

    def test_slide_name_rejects_paths_and_invalid_characters(self):
        self.assertIsNotNone(SLIDE_NAME_PATTERN.fullmatch("Training01"))
        self.assertIsNone(SLIDE_NAME_PATTERN.fullmatch("../secret"))
        self.assertIsNone(SLIDE_NAME_PATTERN.fullmatch("slides/name"))
        self.assertIsNone(SLIDE_NAME_PATTERN.fullmatch(""))

    def test_annotation_schema_enforces_metadata_bounds(self):
        with self.assertRaises(ValidationError):
            SlideAnnotationInput(categories=5, slide_type=1, language=1, question={}, answer="A")
        with self.assertRaises(ValidationError):
            SlideAnnotationInput(categories=1, slide_type=4, language=1, question={}, answer="A")
        with self.assertRaises(ValidationError):
            SlideAnnotationInput(categories=1, slide_type=1, language=3, question={}, answer="A")

    def test_multiple_choice_requires_all_options_and_valid_answer(self):
        task = SimpleNamespace(output_type=OutputType.MULTIPLE_CHOICE)
        payload = SlideAnnotationInput(
            categories=4,
            slide_type=2,
            language=1,
            question={"question_text": "What?", "option_A": "A", "option_B": "B", "option_C": "C", "option_D": "D"},
            answer="A",
        )
        validate_question(task, payload)
        invalid_answer = payload.model_copy(update={"answer": "E"})
        with self.assertRaises(Exception):
            validate_question(task, invalid_answer)

    def test_short_answer_requires_question_text_and_answer(self):
        task = SimpleNamespace(output_type=OutputType.SHORT_ANSWER)
        payload = SlideAnnotationInput(categories=1, slide_type=1, language=2, question={"question_text": "Revenue?"}, answer="$2.5m")
        with self.assertRaises(Exception):
            validate_question(task, payload)
        valid_payload = payload.model_copy(update={"question": {"question_text": "What is the revenue."}})
        validate_question(task, valid_payload)
        invalid_payload = valid_payload.model_copy(update={"question": {"question_text": " "}})
        with self.assertRaises(Exception):
            validate_question(task, invalid_payload)

    def test_drive_link_accepts_http_and_https_only(self):
        self.assertEqual(DriveLinkInput(drive_link="https://drive.google.com/folder/abc").drive_link,
                         "https://drive.google.com/folder/abc")
        with self.assertRaises(ValidationError):
            DriveLinkInput(drive_link="C:/slides")

    @patch("app.services.gemini_service.settings")
    @patch("app.services.gemini_service.requests.post")
    def test_gemini_request_uses_backend_key_header(self, post, mocked_settings):
        mocked_settings.gemini_api_key = "test-key"
        mocked_settings.gemini_model = "gemini-test"
        response = SimpleNamespace(
            json=lambda: {"candidates": [{"content": {"parts": [{"text": '{"question":{"question_text":"What is shown?"},"answer":"A chart"}' }]}}]},
            raise_for_status=lambda: None,
        )
        post.return_value = response

        result = generate_annotation(b"png-bytes", "SHORT_ANSWER", 1, None)

        self.assertEqual(result["answer"], "A chart")
        request_args, request_kwargs = post.call_args
        request_url = request_args[0]
        self.assertEqual(request_url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
        self.assertEqual(request_kwargs["headers"], {"x-goog-api-key": "test-key"})
        self.assertNotIn("test-key", request_url)

    def test_main_label_and_export_fields_preserve_deferred_labels(self):
        from datetime import datetime, timezone

        record = SimpleNamespace(
            task_id=7, id=3, image_id="BusinessTraining_Page01", generated_image_id="BusinessTraining_Page01",
            slide_name="BusinessTraining", categories=1, slide_type=1, language=1,
            drive_link="https://drive.google.com/folder/abc", main_label=1, blind_label=None, reviewer_label=None,
            question={"question_text": "What?", "option_a": "A", "option_b": "B", "option_c": "C", "option_d": "D"},
            answer="A", main_annotator={"decision": 1}, blind_annotator=None, reviewer=None,
            annotation_status="SUBMITTED", created_by=9, page_number=1,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc), output_type="MULTIPLE_CHOICE",
        )
        exported = flatten_record(record)
        self.assertEqual(exported["output_type"], "MULTIPLE_CHOICE")
        self.assertEqual(exported["option_a"], "A")
        self.assertEqual(exported["drive_link"], "https://drive.google.com/folder/abc")
        self.assertEqual(exported["main_label"], 1)
        self.assertIsNone(exported["blind_label"])
        self.assertIsNone(exported["reviewer_label"])
        self.assertEqual(fleiss_agreement_stats([record])["observations"], 0)

    def test_final_dataset_requires_all_three_accept_labels(self):
        accepted = SimpleNamespace(main_label=1, blind_label=1, reviewer_label=1)
        rejected = SimpleNamespace(main_label=1, blind_label=1, reviewer_label=0)
        pending = SimpleNamespace(main_label=1, blind_label=None, reviewer_label=None)
        self.assertEqual(final_dataset_records([accepted, rejected, pending]), [accepted])


if __name__ == "__main__":
    unittest.main()
