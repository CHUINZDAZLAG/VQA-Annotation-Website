import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fitz
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.task import OutputType, TaskStatus
from app.routers.document import SLIDE_NAME_PATTERN, delete_draft_annotation, generated_image_id, render_and_upload_pages, validate_question
from app.schemas.document import DriveDocumentSelection, DriveLinkInput, SlideAnnotationInput
from app.services.result_service import filename, final_dataset_records, flatten_record, fleiss_agreement_stats, serialize_records
from app.services.gemini_service import generate_annotation, generate_annotations


class Milestone3ValidationTests(unittest.TestCase):
    @patch("app.routers.document.get_task")
    def test_published_annotation_cannot_be_deleted_as_draft(self, get_task):
        get_task.return_value = SimpleNamespace(status=TaskStatus.IN_PROGRESS)
        database_session = MagicMock()
        annotation = SimpleNamespace(slide_id=7, publication_status="PUBLISHED", is_deleted=False)
        slide = SimpleNamespace(id=7, document_id=11)
        document = SimpleNamespace(id=11, task_id=3)
        database_session.get.side_effect = [annotation, slide, document]

        with self.assertRaises(HTTPException) as raised:
            delete_draft_annotation(3, 7, 19, None, database_session)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertFalse(annotation.is_deleted)
        database_session.commit.assert_not_called()

    @patch("app.routers.document.get_task")
    def test_submitted_task_rejects_draft_deletion(self, get_task):
        get_task.return_value = SimpleNamespace(status=TaskStatus.SUBMITTED)
        database_session = MagicMock()

        with self.assertRaises(HTTPException) as raised:
            delete_draft_annotation(3, 7, 19, None, database_session)

        self.assertEqual(raised.exception.status_code, 409)
        database_session.get.assert_not_called()
        database_session.commit.assert_not_called()

    def test_backend_generates_stable_page_ids(self):
        self.assertEqual(generated_image_id("cake", 1), "cake_page_01")
        self.assertEqual(generated_image_id("cake", 10), "cake_page_10")
        self.assertEqual(generated_image_id("cake", 100), "cake_page_100")

    @patch("app.routers.document.drive_service.upload_page")
    def test_pdf_pipeline_uploads_every_page_incrementally(self, upload_page):
        upload_page.side_effect = [
            {"id": "page-1", "webViewLink": "drive://page-1", "created": True},
            {"id": "page-2", "webViewLink": "drive://page-2", "created": True},
        ]
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "two-pages.pdf"
            pdf = fitz.open()
            pdf.new_page()
            pdf.new_page()
            pdf.save(pdf_path)
            pdf.close()
            pages = render_and_upload_pages(pdf_path, "deck", "destination")
        self.assertEqual([page[1] for page in pages], ["deck_page_01", "deck_page_02"])
        self.assertEqual(
            [call.args[:2] for call in upload_page.call_args_list],
            [("destination", "deck_page_01.png"), ("destination", "deck_page_02.png")],
        )

    @patch("app.routers.document.drive_service.delete_files")
    @patch("app.routers.document.drive_service.upload_page")
    def test_pdf_pipeline_cleans_only_new_files_after_partial_failure(self, upload_page, delete_files):
        upload_page.side_effect = [
            {"id": "new-page-1", "webViewLink": "drive://page-1", "created": True},
            RuntimeError("upload failed"),
        ]
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "two-pages.pdf"
            pdf = fitz.open()
            pdf.new_page()
            pdf.new_page()
            pdf.save(pdf_path)
            pdf.close()
            with self.assertRaisesRegex(RuntimeError, "Page 2"):
                render_and_upload_pages(pdf_path, "deck", "destination")
        delete_files.assert_called_once_with(["new-page-1"])

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
        payload = SlideAnnotationInput(categories=1, slide_type=1, language=2, question={"question_text": "Revenue"}, answer="$2.5m")
        with self.assertRaises(Exception):
            validate_question(task, payload)
        valid_payload = payload.model_copy(update={"question": {"question_text": "What is the revenue?"}})
        validate_question(task, valid_payload)
        period_payload = valid_payload.model_copy(update={"question": {"question_text": "The revenue is reported."}})
        validate_question(task, period_payload)
        invalid_payload = valid_payload.model_copy(update={"question": {"question_text": " "}})
        with self.assertRaises(Exception):
            validate_question(task, invalid_payload)

    def test_drive_destination_accepts_folder_url_or_id(self):
        folder_url = "https://drive.google.com/drive/folders/abc"
        self.assertEqual(DriveLinkInput(drive_link=folder_url).drive_link, folder_url)
        self.assertEqual(DriveLinkInput(drive_link="abc_123").drive_link, "abc_123")
        with self.assertRaises(ValidationError):
            DriveLinkInput(drive_link="C:/slides")

    def test_drive_pdf_source_and_destination_are_independent(self):
        selection = DriveDocumentSelection(
            folder_id="source-folder",
            pdf_file_id="https://drive.google.com/file/d/pdf-file/view",
            destination_folder_id="destination-folder",
            slide_name="cake",
        )
        self.assertEqual(selection.pdf_file_id, "https://drive.google.com/file/d/pdf-file/view")
        self.assertEqual(selection.destination_folder_id, "destination-folder")

    @patch("app.services.gemini_service.settings")
    @patch("app.services.gemini_service.requests.post")
    def test_gemini_request_uses_backend_key_header(self, post, mocked_settings):
        mocked_settings.gemini_api_key = "test-key"
        mocked_settings.gemini_model = "gemini-test"
        response = SimpleNamespace(
            json=lambda: {"candidates": [{"content": {"parts": [{"text": '{"category":0,"question":{"question_text":"What is shown?"},"answer":"A chart"}' }]}}]},
            raise_for_status=lambda: None,
        )
        post.return_value = response

        result = generate_annotation(b"png-bytes", "SHORT_ANSWER", 1, None)

        self.assertEqual(result["answer"], "A chart")
        request_args, request_kwargs = post.call_args
        request_url = request_args[0]
        self.assertEqual(request_url, "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
        self.assertEqual(request_kwargs["headers"], {"x-goog-api-key": "test-key"})
        self.assertIn("Category: 0", request_kwargs["json"]["contents"][0]["parts"][0]["text"])
        self.assertNotIn("test-key", request_url)

    @patch("app.services.gemini_service.settings")
    @patch("app.services.gemini_service.requests.post")
    def test_gemini_rejects_answer_nested_inside_question(self, post, mocked_settings):
        mocked_settings.gemini_api_key = "test-key"
        mocked_settings.gemini_model = "gemini-test"
        post.return_value = SimpleNamespace(
            json=lambda: {"candidates": [{"content": {"parts": [{"text":
                '{"category":1,"question":{"question_text":"What is shown?","answer":"Text"},"answer":"Text"}'
            }]}}]},
            raise_for_status=lambda: None,
        )
        with self.assertRaisesRegex(ValueError, "nested answer"):
            generate_annotation(b"png-bytes", "SHORT_ANSWER", 1)

    @patch("app.services.gemini_service.settings")
    @patch("app.services.gemini_service.requests.post")
    def test_gemini_generates_ten_labels_in_one_request(self, post, mocked_settings):
        mocked_settings.gemini_api_key = "test-key"
        mocked_settings.gemini_model = "gemini-test"
        annotations = [
            {"category": 0, "question": {"question_text": f"Question {index}?"}, "answer": f"Answer {index}"}
            for index in range(1, 11)
        ]
        post.return_value = SimpleNamespace(
            json=lambda: {"candidates": [{"content": {"parts": [{"text": json.dumps({"annotations": annotations})}]}}]},
            raise_for_status=lambda: None,
        )

        generated = generate_annotations(b"png-bytes", "SHORT_ANSWER", 1, count=10)

        self.assertEqual(len(generated), 10)
        post.assert_called_once()
        instruction = post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Generate exactly 10 distinct annotations", instruction)

    @patch("app.services.gemini_service.settings")
    @patch("app.services.gemini_service.requests.post")
    def test_gemini_rejects_batch_with_fewer_than_ten_labels(self, post, mocked_settings):
        mocked_settings.gemini_api_key = "test-key"
        mocked_settings.gemini_model = "gemini-test"
        annotations = [
            {"category": 0, "question": {"question_text": f"Question {index}?"}, "answer": f"Answer {index}"}
            for index in range(1, 10)
        ]
        post.return_value = SimpleNamespace(
            json=lambda: {"candidates": [{"content": {"parts": [{"text": json.dumps({"annotations": annotations})}]}}]},
            raise_for_status=lambda: None,
        )

        with self.assertRaisesRegex(ValueError, "exactly 10"):
            generate_annotations(b"png-bytes", "SHORT_ANSWER", 1, count=10)

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
        self.assertEqual(exported["question_type"], "MULTIPLE_CHOICE")
        self.assertEqual(exported["category"], 1)
        self.assertEqual(exported["option_A"], "A")
        self.assertEqual(exported["main_annotator"], 1)
        self.assertEqual(exported["option_a"], "A")
        self.assertEqual(exported["drive_link"], "https://drive.google.com/folder/abc")
        self.assertEqual(exported["main_label"], 1)
        self.assertIsNone(exported["blind_label"])
        self.assertIsNone(exported["reviewer_label"])
        self.assertEqual(fleiss_agreement_stats([record])["observations"], 0)

        short_answer = SimpleNamespace(**vars(record))
        short_answer.output_type = "SHORT_ANSWER"
        short_answer.question = {"question_text": "What is the revenue?"}
        short_answer.answer = "$2.5m"
        content, media_type = serialize_records([record, short_answer], "CSV")
        self.assertEqual(media_type, "text/csv")
        self.assertIn(b"question_type", content)
        self.assertIn(b"option_A", content)

    def test_final_dataset_requires_all_three_accept_labels(self):
        accepted = SimpleNamespace(main_label=1, blind_label=1, reviewer_label=1)
        rejected = SimpleNamespace(main_label=1, blind_label=1, reviewer_label=0)
        pending = SimpleNamespace(main_label=1, blind_label=None, reviewer_label=None)
        self.assertEqual(final_dataset_records([accepted, rejected, pending]), [accepted])

    def test_empty_final_csv_keeps_full_schema_and_stable_name(self):
        content, media_type = serialize_records([], "CSV")
        header = content.decode("utf-8-sig").splitlines()[0].split(",")
        self.assertEqual(media_type, "text/csv")
        self.assertTrue({
            "task_id", "question_type", "category", "option_A", "option_D",
            "main_annotator", "blind_annotator", "reviewer", "reject_reason",
        }.issubset(header))
        self.assertEqual(filename("Task 01", "CSV"), "Task_01_final.csv")


if __name__ == "__main__":
    unittest.main()
