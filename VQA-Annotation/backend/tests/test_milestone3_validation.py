import asyncio
import base64
import json
import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pymupdf
from fastapi import HTTPException
from oauthlib.oauth2 import OAuth2Error
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.annotation import AnnotationRecord
from app.models.document import DocumentSlide, SlideStatus, TaskDocument
from app.models.task import OutputType, TaskStatus
from app.routers.auth import google_drive_callback
from app.routers.document import PAGE_RENDER_DPI, SLIDE_NAME_PATTERN, backup_replaced_images, delete_draft_annotation, generated_image_id, get_slides, recover_failed_reprocessing, render_and_upload_pages, replace_stored_document, save_annotation, upload_document, validate_question
from app.routers.results import google_drive_health
from app.schemas.document import DriveDocumentSelection, DriveLinkInput, SlideAnnotationBatchInput, SlideAnnotationInput
from app.services.result_service import DatasetItem, build_dataset_package, document_split, filename, final_dataset_records, flatten_record, fleiss_agreement_stats, serialize_records
from app.services.gemini_service import generate_annotation, generate_annotations
from app.services.drive_service import _credentials, service_account_file
from app.services.google_drive_oauth_service import (
    DRIVE_SCOPES,
    authorization_url,
    decrypt_refresh_token,
    encrypt_refresh_token,
)
from app.services.storage_service import SupabaseImageStorage
from app.main import storage_health_check


class Milestone3ValidationTests(unittest.TestCase):
    def test_pdf_render_dpi_fits_constrained_production_memory(self):
        self.assertEqual(PAGE_RENDER_DPI, 150)

    @patch("app.services.storage_service.requests.get")
    def test_supabase_storage_readiness_checks_private_bucket(self, requests_get):
        response = MagicMock(status_code=200)
        response.ok = True
        response.json.return_value = {"id": "slide-images", "public": False}
        requests_get.return_value = response
        storage_service = SupabaseImageStorage()
        storage_service.base_url = "https://project.supabase.co"
        storage_service.service_role_key = "sb_secret_backend"
        storage_service.bucket = "slide-images"
        storage_service.check_bucket()
        self.assertEqual(
            requests_get.call_args.args[0],
            "https://project.supabase.co/storage/v1/bucket/slide-images",
        )
        self.assertEqual(requests_get.call_args.kwargs["headers"]["apikey"], "sb_secret_backend")
        self.assertNotIn("Authorization", requests_get.call_args.kwargs["headers"])

    @patch("app.services.storage_service.requests.get")
    def test_supabase_storage_readiness_rejects_public_bucket(self, requests_get):
        response = MagicMock(status_code=200, ok=True)
        response.json.return_value = {"id": "slide-images", "public": True}
        requests_get.return_value = response
        storage_service = SupabaseImageStorage()
        storage_service.base_url = "https://project.supabase.co"
        storage_service.service_role_key = "sb_secret_backend"
        storage_service.bucket = "slide-images"

        with self.assertRaisesRegex(RuntimeError, "must be private"):
            storage_service.check_bucket()

    @patch("app.main.supabase_storage.check_bucket", side_effect=RuntimeError("bucket must be private"))
    def test_storage_health_reports_private_bucket_requirement(self, _check_bucket):
        self.assertEqual(storage_health_check(), {
            "status": "unavailable",
            "detail": "The configured Supabase Storage bucket must be private.",
        })

    def test_supabase_storage_rejects_publishable_key(self):
        storage_service = SupabaseImageStorage()
        storage_service.base_url = "https://project.supabase.co"
        storage_service.service_role_key = "sb_publishable_browser"
        storage_service.bucket = "slide-images"
        with self.assertRaisesRegex(RuntimeError, "contains a publishable key"):
            storage_service.require_configuration()

    def test_supabase_storage_uses_bearer_only_for_service_role_jwt(self):
        payload = base64.urlsafe_b64encode(json.dumps({"role": "service_role"}).encode()).decode().rstrip("=")
        storage_service = SupabaseImageStorage()
        storage_service.base_url = "https://project.supabase.co"
        storage_service.service_role_key = f"eyJ.{payload}.signature"
        storage_service.bucket = "slide-images"
        storage_service.require_configuration()
        headers = storage_service._headers()
        self.assertEqual(headers["Authorization"], f"Bearer {storage_service.service_role_key}")

    def test_dataset_package_deduplicates_images_and_keeps_document_split(self):
        document = TaskDocument(
            id=8, task_id=7, original_filename="deck.pdf", slide_name="deck",
            storage_reference="upload:deck.pdf", page_count=2,
        )
        slides = [
            DocumentSlide(id=10, document_id=8, page_number=1, image_id="deck_Page01",
                          slide_name="deck", image_reference="supabase:7/deck_Page01.png",
                          storage_path="7/deck_Page01.png"),
            DocumentSlide(id=11, document_id=8, page_number=2, image_id="deck_Page02",
                          slide_name="deck", image_reference="supabase:7/deck_Page02.png",
                          storage_path="7/deck_Page02.png"),
        ]
        records = []
        for record_id, slide in ((20, slides[0]), (21, slides[0]), (22, slides[1])):
            records.append(AnnotationRecord(
                id=record_id, task_id=7, output_type="SHORT_ANSWER", image_id=slide.image_id,
                generated_image_id=slide.image_id, slide_name="deck", question={"question_text": "What?"},
                answer="Answer", annotation_status="SUBMITTED", page_number=slide.page_number,
            ))
        loader = MagicMock(return_value=b"\x89PNG\r\n\x1a\nimage")
        content, summary = build_dataset_package([
            DatasetItem(records[0], slides[0], document),
            DatasetItem(records[1], slides[0], document),
            DatasetItem(records[2], slides[1], document),
        ], loader)
        self.assertEqual(loader.call_count, 2)
        self.assertEqual(summary["image_count"], 2)
        self.assertEqual(summary["document_count"], 1)
        split = document_split(7, 8)
        self.assertEqual(summary["splits"][split], 3)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
        self.assertIn("dataset-v1.0/images/deck_Page01.png", names)
        self.assertIn("dataset-v1.0/metadata.json", names)

    def test_dataset_package_rejects_image_identity_mismatch(self):
        document = TaskDocument(
            id=8, task_id=7, original_filename="deck.pdf", slide_name="deck",
            storage_reference="upload:deck.pdf", page_count=1,
        )
        slide = DocumentSlide(
            id=10, document_id=8, page_number=1, image_id="deck_Page01", slide_name="deck",
            image_reference="supabase:7/deck_Page01.png", storage_path="7/deck_Page01.png",
        )
        record = AnnotationRecord(
            id=20, task_id=7, output_type="SHORT_ANSWER", image_id="other_Page01",
            generated_image_id="other_Page01", question={"question_text": "What?"}, answer="Answer",
        )
        with self.assertRaisesRegex(ValueError, "image identity"):
            build_dataset_package([DatasetItem(record, slide, document)], MagicMock())

    def test_drive_oauth_requests_profile_scope_returned_by_google(self):
        self.assertIn("https://www.googleapis.com/auth/userinfo.profile", DRIVE_SCOPES)

    @patch("app.routers.auth.frontend_redirect", return_value="https://frontend.test/annotator?drive=error")
    @patch("app.routers.auth.complete_authorization", side_effect=OAuth2Error(description="invalid_client"))
    def test_drive_oauth_callback_redirects_token_exchange_errors(self, _, frontend_redirect):
        database_session = MagicMock()

        response = google_drive_callback(
            state="oauth-state",
            code="authorization-code",
            error=None,
            database_session=database_session,
        )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "https://frontend.test/annotator?drive=error")
        database_session.rollback.assert_called_once_with()
        frontend_redirect.assert_called_once()

    @patch("app.services.google_drive_oauth_service._flow")
    @patch("app.services.google_drive_oauth_service.secrets.token_urlsafe", return_value="oauth-state")
    def test_drive_oauth_start_requests_offline_consent(self, _, flow_factory):
        flow = MagicMock()
        flow.authorization_url.return_value = ("https://accounts.google.test/authorize", "oauth-state")
        flow_factory.return_value = flow
        database_session = MagicMock()

        result = authorization_url(database_session, 17, "/tasks/9/annotate")

        self.assertEqual(result, "https://accounts.google.test/authorize")
        flow_factory.assert_called_once_with("oauth-state")
        flow.authorization_url.assert_called_once_with(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        state_record = database_session.add.call_args.args[0]
        self.assertEqual(state_record.user_id, 17)
        self.assertEqual(state_record.return_path, "/tasks/9/annotate")
        database_session.commit.assert_called_once()

    @patch("app.services.google_drive_oauth_service.settings.secret_key", "test-secret-key-with-at-least-32-bytes")
    def test_drive_refresh_token_is_encrypted_at_rest(self):
        encrypted = encrypt_refresh_token("google-refresh-token")

        self.assertNotIn("google-refresh-token", encrypted)
        self.assertEqual(decrypt_refresh_token(encrypted), "google-refresh-token")

    @patch("app.services.drive_service.authentication_info")
    @patch("app.services.drive_service.verify_writable_folder")
    def test_drive_health_verifies_task_folder_without_upload(self, verify_writable_folder, authentication_info):
        verify_writable_folder.return_value = "folder-id"
        authentication_info.return_value = {
            "method": "oauth_refresh_token",
            "account_email": "backend@example.test",
        }
        database_session = MagicMock()
        database_session.get.return_value = SimpleNamespace(
            drive_folder_id="folder-id",
            annotator_drive_folder_id=None,
            admin_drive_folder_id=None,
        )

        result = google_drive_health(7, None, database_session)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["account_email"], "backend@example.test")
        verify_writable_folder.assert_called_once_with("folder-id")

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.services.drive_service.settings.google_drive_service_account_file", "")
    def test_drive_credentials_report_missing_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE"):
            service_account_file()

    @patch.dict("os.environ", {}, clear=True)
    @patch("app.services.drive_service.settings.google_drive_service_account_file", "C:/missing/drive-key.json")
    def test_drive_credentials_report_missing_file(self):
        with self.assertRaisesRegex(RuntimeError, "was not found"):
            service_account_file()

    def test_drive_credentials_reject_non_service_account_json(self):
        with TemporaryDirectory() as directory:
            credentials_file = Path(directory) / "credentials.json"
            credentials_file.write_text('{"type":"authorized_user"}', encoding="utf-8")
            with patch("app.services.drive_service.settings.google_drive_service_account_file", str(credentials_file)):
                with self.assertRaisesRegex(RuntimeError, "must be a service-account JSON key"):
                    service_account_file()

    @patch("google.auth.default")
    @patch("app.services.drive_service.settings.google_drive_service_account_file", "")
    def test_drive_credentials_support_application_default_credentials(self, google_auth_default):
        credentials = MagicMock()
        google_auth_default.return_value = (credentials, "vqa-annotation")

        self.assertIs(_credentials(["drive-scope"]), credentials)
        google_auth_default.assert_called_once_with(scopes=["drive-scope"])

    @patch("google.oauth2.credentials.Credentials")
    @patch("app.services.drive_service.settings.google_drive_oauth_refresh_token", "refresh-token")
    @patch("app.services.drive_service.settings.google_drive_oauth_client_secret", "client-secret")
    @patch("app.services.drive_service.settings.google_client_id", "client-id")
    @patch("app.services.drive_service.settings.google_drive_service_account_file", "")
    def test_drive_credentials_support_render_oauth_refresh_token(self, credentials_class):
        credentials = MagicMock()
        credentials_class.return_value = credentials

        self.assertIs(_credentials(["drive-scope"]), credentials)
        credentials_class.assert_called_once_with(
            token=None,
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="client-id",
            client_secret="client-secret",
            scopes=["drive-scope"],
        )

    @patch("app.services.drive_service.settings.google_drive_oauth_refresh_token", "")
    @patch("app.services.drive_service.settings.google_drive_oauth_client_secret", "client-secret")
    @patch("app.services.drive_service.settings.google_client_id", "client-id")
    @patch("app.services.drive_service.settings.google_drive_service_account_file", "")
    def test_drive_credentials_reject_incomplete_oauth_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "OAuth configuration is incomplete"):
            _credentials(["drive-scope"])

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
        self.assertEqual(generated_image_id("cake", 1), "cake_Page01")
        self.assertEqual(generated_image_id("cake", 10), "cake_Page10")
        self.assertEqual(generated_image_id("cake", 100), "cake_Page100")

    @patch("app.routers.document.supabase_storage.upload_image")
    def test_pdf_pipeline_uploads_every_page_incrementally(self, upload_image):
        upload_image.side_effect = [
            "42/deck_Page01.png",
            "42/deck_Page02.png",
        ]
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "two-pages.pdf"
            pdf = pymupdf.open()
            pdf.new_page()
            pdf.new_page()
            pdf.save(pdf_path)
            pdf.close()
            pages = render_and_upload_pages(pdf_path, "deck", 42)
        self.assertEqual([page[1] for page in pages], ["deck_Page01", "deck_Page02"])
        self.assertEqual(
            [call.args[:2] for call in upload_image.call_args_list],
            [(42, "deck_Page01"), (42, "deck_Page02")],
        )
        self.assertEqual([page[2]["storage_path"] for page in pages], [
            "42/deck_Page01.png", "42/deck_Page02.png",
        ])

    @patch("app.routers.document.supabase_storage.upload_image")
    def test_twenty_page_pdf_uploads_twenty_unique_images(self, upload_image):
        upload_image.side_effect = [
            f"12/cake_Page{page_number:02d}.png"
            for page_number in range(1, 21)
        ]
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "twenty-pages.pdf"
            pdf = pymupdf.open()
            for _ in range(20):
                pdf.new_page()
            pdf.save(pdf_path)
            pdf.close()

            pages = render_and_upload_pages(pdf_path, "cake", 12)

        image_ids = [page[1] for page in pages]
        storage_paths = [page[2]["storage_path"] for page in pages]
        self.assertEqual(len(pages), 20)
        self.assertEqual(image_ids, [f"cake_Page{page_number:02d}" for page_number in range(1, 21)])
        self.assertEqual(storage_paths, [f"12/cake_Page{page_number:02d}.png" for page_number in range(1, 21)])
        self.assertEqual(upload_image.call_count, 20)

    def test_twenty_pages_create_twenty_document_slide_records(self):
        database_session = MagicMock()
        stored_document = TaskDocument(
            id=8,
            task_id=12,
            original_filename="cake.pdf",
            slide_name="cake",
            storage_reference="upload:cake.pdf",
            page_count=20,
        )
        pages = [
            (
                page_number,
                f"cake_Page{page_number:02d}",
                {
                    "storage_path": f"12/cake_Page{page_number:02d}.png",
                    "width": 1240,
                    "height": 1754,
                    "file_size": 1000 + page_number,
                    "mime_type": "image/png",
                },
            )
            for page_number in range(1, 21)
        ]

        stale_paths = replace_stored_document(database_session, 12, None, stored_document, pages)

        slides = [
            call.args[0]
            for call in database_session.add.call_args_list
            if isinstance(call.args[0], DocumentSlide)
        ]
        self.assertEqual(stale_paths, [])
        self.assertEqual(len(slides), 20)
        self.assertEqual([slide.page_number for slide in slides], list(range(1, 21)))
        self.assertEqual([slide.image_id for slide in slides], [
            f"cake_Page{page_number:02d}" for page_number in range(1, 21)
        ])
        self.assertEqual([slide.storage_path for slide in slides], [
            f"12/cake_Page{page_number:02d}.png" for page_number in range(1, 21)
        ])

    def test_twenty_document_slides_commit_and_query_through_sqlalchemy(self):
        engine = create_engine("sqlite:///:memory:")
        TaskDocument.__table__.create(engine)
        DocumentSlide.__table__.create(engine)
        pages = [
            (
                page_number,
                f"cake_Page{page_number:02d}",
                {
                    "storage_path": f"12/cake_Page{page_number:02d}.png",
                    "width": 1240,
                    "height": 1754,
                    "file_size": 1000 + page_number,
                    "mime_type": "image/png",
                },
            )
            for page_number in range(1, 21)
        ]
        document = TaskDocument(
            task_id=12,
            original_filename="cake.pdf",
            slide_name="cake",
            storage_reference="upload:cake.pdf",
            page_count=20,
        )

        with Session(engine) as database_session:
            replace_stored_document(database_session, 12, None, document, pages)
            database_session.commit()
            persisted = list(database_session.scalars(
                select(DocumentSlide).order_by(DocumentSlide.page_number)
            ))

        self.assertEqual(len(persisted), 20)
        self.assertEqual([slide.image_id for slide in persisted], [
            f"cake_Page{page_number:02d}" for page_number in range(1, 21)
        ])
        self.assertEqual([slide.storage_path for slide in persisted], [
            f"12/cake_Page{page_number:02d}.png" for page_number in range(1, 21)
        ])

    def test_slides_api_serializes_all_twenty_pages_in_order(self):
        database_session = MagicMock()
        database_session.scalar.return_value = SimpleNamespace(id=8, task_id=12)
        slides = [
            DocumentSlide(
                id=page_number,
                document_id=8,
                page_number=page_number,
                image_id=f"cake_Page{page_number:02d}",
                slide_name="cake",
                image_reference=f"supabase:12/cake_Page{page_number:02d}.png",
                storage_path=f"12/cake_Page{page_number:02d}.png",
                status=SlideStatus.NOT_STARTED,
            )
            for page_number in range(1, 21)
        ]
        database_session.scalars.side_effect = [slides, []]

        response = get_slides(12, SimpleNamespace(id=23), database_session)

        self.assertEqual(len(response), 20)
        self.assertEqual([slide.page_number for slide in response], list(range(1, 21)))
        self.assertEqual([slide.image_id for slide in response], [
            f"cake_Page{page_number:02d}" for page_number in range(1, 21)
        ])
        self.assertEqual(response[-1].image_url, "/api/tasks/12/images/cake_Page20")

    @patch("app.routers.document.supabase_storage.upload_image")
    @patch("app.routers.document.supabase_storage.delete_images")
    def test_failed_reprocessing_restores_old_images_and_removes_new_paths(self, delete_images, upload_image):
        upload_image.return_value = "12/cake_Page01.png"
        with TemporaryDirectory() as directory:
            backup_path = Path(directory) / "1.png"
            backup_path.write_bytes(b"old-page-one")

            recover_failed_reprocessing(
                12,
                ["12/cake_Page01.png", "12/cake_Page02.png"],
                [("12/cake_Page01.png", "cake_Page01", backup_path)],
            )

        delete_images.assert_called_once_with(["12/cake_Page02.png"])
        upload_image.assert_called_once_with(12, "cake_Page01", b"old-page-one")

    @patch("app.routers.document.supabase_storage.download_image", return_value=b"old-page-one")
    def test_reprocessing_backs_up_paths_that_will_be_upserted(self, download_image):
        database_session = MagicMock()
        existing = SimpleNamespace(id=8)
        database_session.scalars.return_value = [SimpleNamespace(
            id=1,
            page_number=1,
            storage_path="12/cake_Page01.png",
        )]
        with TemporaryDirectory() as directory:
            backups = backup_replaced_images(
                database_session,
                existing,
                12,
                "cake",
                Path(directory),
            )

            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0][:2], ("12/cake_Page01.png", "cake_Page01"))
            self.assertEqual(backups[0][2].read_bytes(), b"old-page-one")
        download_image.assert_called_once_with("12/cake_Page01.png")

    def test_renamed_reprocessing_marks_old_storage_paths_stale(self):
        database_session = MagicMock()
        existing = TaskDocument(
            id=8,
            task_id=12,
            original_filename="old.pdf",
            slide_name="old",
            storage_reference="upload:old.pdf",
            page_count=1,
        )
        old_slide = DocumentSlide(
            id=1,
            document_id=8,
            page_number=1,
            image_id="old_Page01",
            slide_name="old",
            image_reference="supabase:12/old_Page01.png",
            storage_path="12/old_Page01.png",
        )
        database_session.scalars.return_value = [old_slide]
        replacement = TaskDocument(
            task_id=12,
            original_filename="new.pdf",
            slide_name="new",
            storage_reference="upload:new.pdf",
            page_count=1,
        )
        pages = [(1, "new_Page01", {
            "storage_path": "12/new_Page01.png",
            "width": 1240,
            "height": 1754,
            "file_size": 1001,
            "mime_type": "image/png",
        })]

        stale_paths = replace_stored_document(database_session, 12, existing, replacement, pages)

        self.assertEqual(stale_paths, ["12/old_Page01.png"])
        self.assertEqual(old_slide.image_id, "new_Page01")
        self.assertEqual(old_slide.storage_path, "12/new_Page01.png")

    @patch("app.routers.document.supabase_storage.delete_images")
    @patch("app.routers.document.supabase_storage.upload_image")
    def test_pdf_pipeline_cleans_only_new_files_after_partial_failure(self, upload_image, delete_images):
        upload_image.side_effect = [
            "42/deck_Page01.png",
            RuntimeError("upload failed"),
        ]
        with TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "two-pages.pdf"
            pdf = pymupdf.open()
            pdf.new_page()
            pdf.new_page()
            pdf.save(pdf_path)
            pdf.close()
            with self.assertRaisesRegex(RuntimeError, "Page 2"):
                render_and_upload_pages(pdf_path, "deck", 42)
        delete_images.assert_called_once_with(["42/deck_Page01.png"])

    @patch("app.routers.document.DocumentResponse.model_validate", return_value={"id": 7})
    @patch("app.routers.document.get_slides", return_value=[{"image_id": "deck_Page01"}])
    @patch("app.routers.document.replace_stored_document", return_value=[])
    @patch("app.routers.document.render_and_upload_pages", return_value=[
        (1, "deck_Page01", {"storage_path": "12/deck_Page01.png"}),
    ])
    @patch("app.routers.document.require_reprocessable_document")
    @patch("app.routers.document.require_document_task")
    def test_upload_document_returns_slides_with_authenticated_user(
        self,
        require_document_task,
        _require_reprocessable_document,
        _render_and_upload_pages,
        _replace_stored_document,
        get_slides,
        _model_validate,
    ):
        task = SimpleNamespace(status=TaskStatus.WAITING_FOR_DOCUMENT)
        require_document_task.return_value = task
        database_session = MagicMock()
        database_session.scalar.return_value = None
        current_user = SimpleNamespace(id=23)

        class UploadedPdf:
            filename = "deck.pdf"
            content_type = "application/pdf"

            def __init__(self):
                self.chunks = [b"%PDF-1.7\n", b""]

            async def read(self, _size):
                return self.chunks.pop(0)

        result = asyncio.run(upload_document(
            task_id=12,
            current_user=current_user,
            database_session=database_session,
            document=UploadedPdf(),
            slide_name="deck",
            destination_drive_folder_id=None,
        ))

        self.assertEqual(result["slides"], [{"image_id": "deck_Page01"}])
        get_slides.assert_called_once_with(12, current_user, database_session)

    @patch("app.routers.document.DocumentResponse.model_validate", return_value={"id": 7})
    @patch("app.routers.document.get_slides", return_value=[{"image_id": "deck_Page01"}])
    @patch("app.routers.document.replace_stored_document", return_value=[])
    @patch("app.routers.document.render_and_upload_pages", return_value=[
        (1, "deck_Page01", {"storage_path": "12/deck_Page01.png"}),
    ])
    @patch("app.routers.document.backup_replaced_images", return_value=[])
    @patch("app.routers.document.require_reprocessable_document")
    @patch("app.routers.document.require_document_task")
    def test_reprocessing_refreshes_existing_document(
        self,
        require_document_task,
        _require_reprocessable_document,
        _backup_replaced_images,
        _render_and_upload_pages,
        _replace_stored_document,
        _get_slides,
        _model_validate,
    ):
        require_document_task.return_value = SimpleNamespace(status=TaskStatus.IN_PROGRESS)
        existing = TaskDocument(
            id=7,
            task_id=12,
            original_filename="old.pdf",
            slide_name="deck",
            storage_reference="upload:old.pdf",
            page_count=1,
        )
        database_session = MagicMock()
        database_session.scalar.return_value = existing

        class UploadedPdf:
            filename = "new.pdf"
            content_type = "application/pdf"

            def __init__(self):
                self.chunks = [b"%PDF-1.7\n", b""]

            async def read(self, _size):
                return self.chunks.pop(0)

        asyncio.run(upload_document(
            task_id=12,
            current_user=SimpleNamespace(id=23),
            database_session=database_session,
            document=UploadedPdf(),
            slide_name="deck",
            destination_drive_folder_id=None,
        ))

        database_session.refresh.assert_called_once_with(existing)

    @patch("app.routers.document.recover_failed_reprocessing")
    @patch("app.routers.document.replace_stored_document", return_value=[])
    @patch("app.routers.document.render_and_upload_pages", return_value=[
        (1, "deck_Page01", {"storage_path": "12/deck_Page01.png"}),
    ])
    @patch("app.routers.document.backup_replaced_images", return_value=[
        ("12/deck_Page01.png", "deck_Page01", Path("backup.png")),
    ])
    @patch("app.routers.document.require_reprocessable_document")
    @patch("app.routers.document.require_document_task")
    def test_database_failure_triggers_storage_recovery(
        self,
        require_document_task,
        _require_reprocessable_document,
        backup_replaced_images,
        _render_and_upload_pages,
        _replace_stored_document,
        recover_failed_reprocessing,
    ):
        require_document_task.return_value = SimpleNamespace(status=TaskStatus.IN_PROGRESS)
        existing = TaskDocument(
            id=7,
            task_id=12,
            original_filename="old.pdf",
            slide_name="deck",
            storage_reference="upload:old.pdf",
            page_count=1,
        )
        database_session = MagicMock()
        database_session.scalar.return_value = existing
        database_session.commit.side_effect = RuntimeError("database unavailable")

        class UploadedPdf:
            filename = "new.pdf"
            content_type = "application/pdf"

            def __init__(self):
                self.chunks = [b"%PDF-1.7\n", b""]

            async def read(self, _size):
                return self.chunks.pop(0)

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(upload_document(
                task_id=12,
                current_user=SimpleNamespace(id=23),
                database_session=database_session,
                document=UploadedPdf(),
                slide_name="deck",
                destination_drive_folder_id=None,
            ))

        self.assertEqual(raised.exception.status_code, 422)
        recover_failed_reprocessing.assert_called_once_with(
            12,
            ["12/deck_Page01.png"],
            backup_replaced_images.return_value,
        )

    def test_slide_name_rejects_paths_and_invalid_characters(self):
        self.assertIsNotNone(SLIDE_NAME_PATTERN.fullmatch("Training01"))
        self.assertIsNone(SLIDE_NAME_PATTERN.fullmatch("../secret"))
        self.assertIsNone(SLIDE_NAME_PATTERN.fullmatch("slides/name"))
        self.assertIsNone(SLIDE_NAME_PATTERN.fullmatch(""))

    def test_annotation_schema_enforces_metadata_bounds(self):
        with self.assertRaises(ValidationError):
            SlideAnnotationInput(image_id="deck_Page01", categories=5, slide_type=1, language=1, question={}, answer="A")
        with self.assertRaises(ValidationError):
            SlideAnnotationInput(image_id="deck_Page01", categories=1, slide_type=4, language=1, question={}, answer="A")
        with self.assertRaises(ValidationError):
            SlideAnnotationInput(image_id="deck_Page01", categories=1, slide_type=1, language=3, question={}, answer="A")

    @patch("app.routers.document.get_task")
    def test_save_rejects_image_id_mismatch_before_writing(self, get_task):
        get_task.return_value = SimpleNamespace(
            status=TaskStatus.IN_PROGRESS,
            output_type=OutputType.SHORT_ANSWER,
        )
        slide = SimpleNamespace(id=3, document_id=8, image_id="deck_Page01")
        document = SimpleNamespace(id=8, task_id=7)
        database_session = MagicMock()
        database_session.get.side_effect = lambda model, identifier: slide if identifier == 3 else document
        payload = SlideAnnotationInput(
            image_id="other_Page01", categories=1, slide_type=1, language=1,
            question={"question_text": "What is shown?"}, answer="A chart",
        )
        with self.assertRaisesRegex(HTTPException, "image_id does not match"):
            save_annotation(7, 3, payload, SimpleNamespace(id=5), database_session)
        database_session.add.assert_not_called()
        database_session.flush.assert_not_called()
        database_session.commit.assert_not_called()

    def test_manual_json_batch_requires_exactly_ten_labels(self):
        annotation = SlideAnnotationInput(
            image_id="deck_Page01",
            categories=0,
            slide_type=1,
            language=1,
            question={"question_text": "Question"},
            answer="A",
        )
        with self.assertRaises(ValidationError):
            SlideAnnotationBatchInput(annotations=[annotation] * 9)
        batch = SlideAnnotationBatchInput(annotations=[annotation] * 10)
        self.assertEqual(len(batch.annotations), 10)

    def test_multiple_choice_requires_all_options_and_valid_answer(self):
        task = SimpleNamespace(output_type=OutputType.MULTIPLE_CHOICE)
        payload = SlideAnnotationInput(
            image_id="deck_Page01",
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
        payload = SlideAnnotationInput(image_id="deck_Page01", categories=1, slide_type=1, language=2, question={"question_text": "Revenue"}, answer="$2.5m")
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
        instruction = request_kwargs["json"]["contents"][0]["parts"][0]["text"]
        self.assertIn("Choose the most relevant category independently", instruction)
        self.assertIn("Category 0 (CHART_ONLY) is only a preference", instruction)
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
