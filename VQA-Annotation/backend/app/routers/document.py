import logging
import re
import shutil
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import pymupdf
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import settings
from app.middleware.auth import require_task_assignment
from app.models.annotation import AnnotationRecord
from app.models.document import DocumentSlide, ProcessingStatus, SlideStatus, TaskDocument
from app.models.export import TaskExport
from app.models.slide_annotation import SlideAnnotation
from app.models.task import OutputType, Task, TaskStatus, TaskType
from app.models.user import User
from app.schemas.document import BlindAnnotationInput, DecisionInput, DocumentResponse, DraftPositionInput, DriveDocumentSelection, DriveLinkInput, GenerateAnnotationInput, SlideAnnotationBatchInput, SlideAnnotationInput, SlideAnnotationPreview, SlideAnnotationResponse, SlideResponse, SubmitResponse
from app.services import drive_service
from app.services.gemini_service import generate_annotations
from app.services.result_service import filename, final_dataset_records, serialize_records
from app.services.storage_service import supabase_storage

router = APIRouter(prefix="/api/tasks", tags=["main-annotator-document"])
logger = logging.getLogger(__name__)
MainAnnotator = Annotated[User, Depends(require_task_assignment(TaskType.MAIN_ANNOTATOR))]
BlindAnnotator = Annotated[User, Depends(require_task_assignment(TaskType.BLIND_ANNOTATOR))]
Reviewer = Annotated[User, Depends(require_task_assignment(TaskType.REVIEWER))]
SLIDE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,254}$")
PAGE_RENDER_DPI = 150


def generated_image_id(slide_name: str, page_number: int) -> str:
    return f"{slide_name}_Page{page_number:02d}"


def get_task(task_id: int, database_session: Session) -> Task:
    task = database_session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


def require_document_task(task_id: int, database_session: Session) -> Task:
    task = get_task(task_id, database_session)
    if task.status not in {TaskStatus.WAITING_FOR_DOCUMENT, TaskStatus.IN_PROGRESS}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This task is not ready for document processing.",
        )
    return task


def drive_error_detail(error: Exception) -> str:
    status_code = getattr(getattr(error, "resp", None), "status", None)
    if status_code in {401, 403} or isinstance(error, PermissionError):
        return (
            "Google Drive permission denied. Please share the source file/folder and destination "
            "folder with the configured Drive account; the destination requires Editor access."
        )
    if status_code == 404:
        return "Google Drive file or folder was not found or is not shared with the configured Drive account."
    return str(error)


def effective_destination(task: Task, requested_folder: str | None, user_id: int) -> str:
    candidate = (
        requested_folder
        or task.annotator_drive_folder_id
        or task.admin_drive_folder_id
        or task.drive_folder_id
    )
    if not candidate:
        raise HTTPException(status_code=422, detail="A destination Google Drive folder is required.")
    try:
        folder_id = drive_service.verify_writable_folder(candidate, user_id=user_id)
    except Exception as error:
        raise HTTPException(status_code=422, detail=drive_error_detail(error)) from error
    if requested_folder:
        task.annotator_drive_folder_id = folder_id
    task.drive_folder_id = folder_id
    task.drive_folder_url = drive_service.folder_url(folder_id)
    return folder_id


def render_and_upload_pages(
    pdf_path: Path,
    slide_name: str,
    task_id: int,
) -> list[tuple[int, str, dict]]:
    uploaded_pages: list[tuple[int, str, dict]] = []
    uploaded_paths: list[str] = []
    try:
        with pymupdf.open(pdf_path) as pdf:
            if pdf.page_count == 0:
                raise HTTPException(status_code=422, detail="The PDF contains no pages.")
            for page_number in range(1, pdf.page_count + 1):
                image_id = generated_image_id(slide_name, page_number)
                file_name = f"{image_id}.png"
                try:
                    pixmap = pdf.load_page(page_number - 1).get_pixmap(
                        matrix=pymupdf.Matrix(PAGE_RENDER_DPI / 72, PAGE_RENDER_DPI / 72), alpha=False,
                    )
                    image_bytes = pixmap.tobytes("png")
                    storage_path = supabase_storage.upload_image(task_id, image_id, image_bytes)
                    uploaded = {
                        "storage_path": storage_path,
                        "width": pixmap.width,
                        "height": pixmap.height,
                        "file_size": len(image_bytes),
                        "mime_type": "image/png",
                    }
                except Exception as error:
                    raise RuntimeError(
                        f"Page {page_number} ({file_name}) failed: {error}"
                    ) from error
                uploaded_paths.append(storage_path)
                uploaded_pages.append((page_number, image_id, uploaded))
    except Exception:
        try:
            supabase_storage.delete_images(uploaded_paths)
        except Exception:
            pass
        raise
    return uploaded_pages


def backup_replaced_images(
    database_session: Session,
    existing: TaskDocument | None,
    task_id: int,
    slide_name: str,
    backup_root: Path,
) -> list[tuple[str, str, Path]]:
    if existing is None:
        return []
    backups: list[tuple[str, str, Path]] = []
    slides = database_session.scalars(
        select(DocumentSlide).where(DocumentSlide.document_id == existing.id)
    )
    for slide in slides:
        image_id = generated_image_id(slide_name, slide.page_number)
        expected_path = supabase_storage.image_path(task_id, image_id)
        if slide.storage_path != expected_path:
            continue
        backup_path = backup_root / f"{slide.id}.png"
        backup_path.write_bytes(supabase_storage.download_image(expected_path))
        backups.append((expected_path, image_id, backup_path))
    return backups


def recover_failed_reprocessing(
    task_id: int,
    uploaded_paths: list[str],
    backups: list[tuple[str, str, Path]],
) -> None:
    backup_paths = {storage_path for storage_path, _, _ in backups}
    new_paths = [storage_path for storage_path in uploaded_paths if storage_path not in backup_paths]
    try:
        supabase_storage.delete_images(new_paths)
        for expected_path, image_id, backup_path in backups:
            restored_path = supabase_storage.upload_image(task_id, image_id, backup_path.read_bytes())
            if restored_path != expected_path:
                raise RuntimeError(f"Restored image path mismatch: {expected_path}")
    except Exception as error:
        logger.error("Storage recovery failed for task %s: %s", task_id, error)


def replace_stored_document(
    database_session: Session,
    task_id: int,
    existing: TaskDocument | None,
    stored_document: TaskDocument,
    pages: list[tuple[int, str, dict]],
) -> list[str]:
    stale_storage_paths: list[str] = []
    if existing:
        target_document = existing
        target_document.original_filename = stored_document.original_filename
        target_document.slide_name = stored_document.slide_name
        target_document.drive_folder_id = stored_document.drive_folder_id
        target_document.source_pdf_file_id = stored_document.source_pdf_file_id
        target_document.source_pdf_url = stored_document.source_pdf_url
        target_document.storage_reference = stored_document.storage_reference
        target_document.processing_status = stored_document.processing_status
        target_document.page_count = stored_document.page_count
        old_slides = {
            slide.image_id: slide
            for slide in database_session.scalars(
                select(DocumentSlide).where(DocumentSlide.document_id == existing.id)
            )
        }
        old_slides_by_page = {slide.page_number: slide for slide in old_slides.values()}
    else:
        target_document = stored_document
        old_slides = {}
        old_slides_by_page = {}
        database_session.add(target_document)
    database_session.flush()
    current_image_ids: set[str] = set()
    for page_number, image_id, uploaded in pages:
        current_image_ids.add(image_id)
        slide = old_slides.get(image_id) or old_slides_by_page.get(page_number)
        if slide is None:
            slide = DocumentSlide(document_id=target_document.id, image_id=image_id)
            database_session.add(slide)
        else:
            if slide.storage_path and slide.storage_path != uploaded["storage_path"]:
                stale_storage_paths.append(slide.storage_path)
            current_image_ids.add(slide.image_id)
            slide.image_id = image_id
        slide.page_number = page_number
        slide.slide_name = target_document.slide_name
        slide.drive_folder_id = None
        slide.drive_file_id = None
        slide.drive_file_url = None
        slide.storage_path = uploaded["storage_path"]
        slide.image_reference = f"supabase:{uploaded['storage_path']}"
        slide.width = uploaded["width"]
        slide.height = uploaded["height"]
        slide.file_size = uploaded["file_size"]
        slide.mime_type = uploaded["mime_type"]
    current_slide_ids = {slide.id for slide in old_slides.values() if slide.image_id in current_image_ids}
    for slide in old_slides.values():
        if slide.id not in current_slide_ids:
            if slide.storage_path:
                stale_storage_paths.append(slide.storage_path)
            database_session.delete(slide)
    return list(dict.fromkeys(stale_storage_paths))


def require_reprocessable_document(database_session: Session, existing: TaskDocument | None) -> None:
    if existing is None:
        return
    slide_ids = list(database_session.scalars(
        select(DocumentSlide.id).where(DocumentSlide.document_id == existing.id)
    ))
    if slide_ids and database_session.scalar(
        select(func.count()).select_from(SlideAnnotation).where(
            SlideAnnotation.slide_id.in_(slide_ids),
            SlideAnnotation.is_deleted.is_(False),
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="This document already has saved annotations and cannot be replaced.",
        )


def validate_question(task: Task, payload: SlideAnnotationInput) -> None:
    question = payload.question
    if not str(question.get("question_text", "")).strip():
        raise HTTPException(status_code=422, detail="question.question_text is required.")
    if not payload.answer.strip():
        raise HTTPException(status_code=422, detail="Answer is required.")
    if task.output_type == OutputType.MULTIPLE_CHOICE:
        missing = [key for key in ("option_a", "option_b", "option_c", "option_d")
               if not str(question.get(key, question.get(f"option_{key[-1].upper()}", ""))).strip()]
        if missing:
            raise HTTPException(status_code=422, detail=f"Missing multiple-choice options: {', '.join(missing)}.")
        if payload.answer not in {"A", "B", "C", "D"}:
            raise HTTPException(status_code=422, detail="Multiple-choice answer must be A, B, C, or D.")
    elif not str(question.get("question_text", "")).strip().endswith((".", "?")):
        raise HTTPException(status_code=422, detail="Short-answer question must end with a period or question mark.")


def text_similarity(left: str, right: str) -> float:
    return round(SequenceMatcher(None, left.strip().lower(), right.strip().lower()).ratio(), 4)


def annotation_response(annotation: SlideAnnotation | None) -> SlideAnnotationResponse | None:
    return SlideAnnotationResponse.model_validate(annotation) if annotation else None


def normalized_question(question: dict) -> dict:
    normalized = dict(question)
    for letter in "abcd":
        upper = f"option_{letter.upper()}"
        lower = f"option_{letter}"
        if lower not in normalized and upper in normalized:
            normalized[lower] = normalized[upper]
        normalized.pop(upper, None)
    return normalized


def slide_response(
    task_id: int,
    slide: DocumentSlide,
    annotations: list[SlideAnnotation] | None = None,
) -> SlideResponse:
    visible_annotations = [annotation for annotation in (annotations or []) if not annotation.is_deleted]
    legacy_annotation = visible_annotations[0] if visible_annotations else None
    return SlideResponse(
        id=slide.id,
        annotation_id=legacy_annotation.id if legacy_annotation else None,
        document_id=slide.document_id,
        page_number=slide.page_number,
        image_id=slide.image_id,
        drive_folder_id=slide.drive_folder_id,
        drive_file_id=slide.drive_file_id,
        drive_file_url=slide.drive_file_url,
        slide_name=slide.slide_name,
        image_reference=slide.image_reference,
        storage_path=slide.storage_path,
        width=slide.width,
        height=slide.height,
        file_size=slide.file_size,
        mime_type=slide.mime_type,
        image_url=f"/api/tasks/{task_id}/images/{quote(slide.image_id, safe='')}",
        status=slide.status,
        annotation=annotation_response(legacy_annotation),
        annotations=[annotation_response(annotation) for annotation in visible_annotations],
    )


@router.post("/{task_id}/document", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_document(
    task_id: int,
    current_user: MainAnnotator,
    database_session: Session = Depends(get_db),
    document: UploadFile = File(...),
    slide_name: str = Form(...),
    destination_drive_folder_id: str | None = Form(default=None),
):
    task = require_document_task(task_id, database_session)
    existing = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    normalized_name = slide_name.strip()
    if not normalized_name or not SLIDE_NAME_PATTERN.fullmatch(normalized_name) or ".." in normalized_name:
        raise HTTPException(status_code=422, detail="slide_name contains invalid characters.")
    filename = Path(document.filename or "").name
    if not filename.lower().endswith(".pdf") or document.content_type not in {"application/pdf", "application/octet-stream", None}:
        raise HTTPException(status_code=415, detail="Only PDF files are accepted.")
    temp_path: Path | None = None
    backup_root = Path(tempfile.mkdtemp(prefix="vqa-storage-backup-"))
    backups: list[tuple[str, str, Path]] = []
    uploaded_paths: list[str] = []
    committed = False
    try:
        require_reprocessable_document(database_session, existing)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            temp_path = Path(handle.name)
            first_chunk = await document.read(1024 * 1024)
            if not first_chunk:
                raise HTTPException(status_code=422, detail="The PDF is empty.")
            if not first_chunk.startswith(b"%PDF"):
                raise HTTPException(status_code=415, detail="The uploaded file is not a valid PDF.")
            handle.write(first_chunk)
            total_size = len(first_chunk)
            while chunk := await document.read(1024 * 1024):
                total_size += len(chunk)
                if settings.max_pdf_size_mb and total_size > settings.max_pdf_size_mb * 1024 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail=f"The PDF exceeds the {settings.max_pdf_size_mb} MB size limit.",
                    )
                handle.write(chunk)
        backups = backup_replaced_images(database_session, existing, task_id, normalized_name, backup_root)
        pages = render_and_upload_pages(temp_path, normalized_name, task_id)
        uploaded_paths = [page[2]["storage_path"] for page in pages]
        stored_document = TaskDocument(
            task_id=task_id,
            original_filename=filename,
            slide_name=normalized_name,
            drive_folder_id=None,
            storage_reference=f"upload:{filename}",
            processing_status=ProcessingStatus.PROCESSED,
            page_count=len(pages),
        )
        stale_storage_paths = replace_stored_document(database_session, task_id, existing, stored_document, pages)
        persisted_document = existing or stored_document
        task.status = TaskStatus.IN_PROGRESS
        database_session.commit()
        committed = True
        try:
            supabase_storage.delete_images(stale_storage_paths)
        except Exception as error:
            logger.warning("Stale image cleanup failed for task %s: %s", task_id, error)
        database_session.refresh(persisted_document)
        return {
            "document": DocumentResponse.model_validate(persisted_document),
            "slides": get_slides(task_id, current_user, database_session),
        }
    except HTTPException:
        database_session.rollback()
        if not committed:
            recover_failed_reprocessing(task_id, uploaded_paths, backups)
        raise
    except Exception as error:
        database_session.rollback()
        if not committed:
            recover_failed_reprocessing(task_id, uploaded_paths, backups)
        error_detail = drive_error_detail(error)
        logger.warning("PDF processing failed for task %s: %s", task_id, error_detail)
        raise HTTPException(status_code=422, detail=f"PDF processing failed: {error_detail}") from error
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        shutil.rmtree(backup_root, ignore_errors=True)


@router.get("/{task_id}/document/drive-files", response_model=list[dict])
def list_drive_documents(task_id: int, folder_id: str, current_user: MainAnnotator,
                         database_session: Session = Depends(get_db)) -> list[dict]:
    get_task(task_id, database_session)
    try:
        return drive_service.list_pdf_files(folder_id, user_id=current_user.id)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{task_id}/document/select", response_model=dict, status_code=status.HTTP_201_CREATED)
def select_drive_document(task_id: int, payload: DriveDocumentSelection, current_user: MainAnnotator,
                          database_session: Session = Depends(get_db)) -> dict:
    task = require_document_task(task_id, database_session)
    normalized_name = payload.slide_name.strip()
    if not SLIDE_NAME_PATTERN.fullmatch(normalized_name) or ".." in normalized_name:
        raise HTTPException(status_code=422, detail="slide_name contains invalid characters.")
    temp_path: Path | None = None
    backup_root = Path(tempfile.mkdtemp(prefix="vqa-storage-backup-"))
    backups: list[tuple[str, str, Path]] = []
    uploaded_paths: list[str] = []
    committed = False
    try:
        old_document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
        require_reprocessable_document(database_session, old_document)
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            temp_path = Path(handle.name)
        metadata = drive_service.download_pdf(payload.pdf_file_id, temp_path, user_id=current_user.id)
        backups = backup_replaced_images(database_session, old_document, task_id, normalized_name, backup_root)
        pages = render_and_upload_pages(temp_path, normalized_name, task_id)
        uploaded_paths = [page[2]["storage_path"] for page in pages]
        stored_document = TaskDocument(
            task_id=task_id, original_filename=metadata["name"], slide_name=normalized_name,
            drive_folder_id=None, source_pdf_file_id=metadata["id"], source_pdf_url=metadata.get("webViewLink"),
            storage_reference=f"drive:{metadata['id']}", processing_status=ProcessingStatus.PROCESSED,
            page_count=len(pages),
        )
        stale_storage_paths = replace_stored_document(database_session, task_id, old_document, stored_document, pages)
        persisted_document = old_document or stored_document
        task.status = TaskStatus.IN_PROGRESS
        database_session.commit()
        committed = True
        try:
            supabase_storage.delete_images(stale_storage_paths)
        except Exception as error:
            logger.warning("Stale image cleanup failed for task %s: %s", task_id, error)
        database_session.refresh(persisted_document)
        return {
            "document": DocumentResponse.model_validate(persisted_document),
            "slides": get_slides(task_id, current_user, database_session),
        }
    except HTTPException:
        database_session.rollback()
        if not committed:
            recover_failed_reprocessing(task_id, uploaded_paths, backups)
        raise
    except Exception as error:
        database_session.rollback()
        if not committed:
            recover_failed_reprocessing(task_id, uploaded_paths, backups)
        raise HTTPException(status_code=422, detail=f"Google Drive PDF processing failed: {drive_error_detail(error)}") from error
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        shutil.rmtree(backup_root, ignore_errors=True)


@router.patch("/{task_id}/document/drive-link", response_model=dict)
def save_drive_link(task_id: int, payload: DriveLinkInput, current_user: MainAnnotator,
                    database_session: Session = Depends(get_db)) -> dict:
    task = get_task(task_id, database_session)
    try:
        folder_id = drive_service.verify_writable_folder(payload.drive_link, user_id=current_user.id)
    except Exception as error:
        raise HTTPException(status_code=422, detail=drive_error_detail(error)) from error
    task.annotator_drive_folder_id = folder_id
    task.drive_folder_id = folder_id
    task.drive_folder_url = drive_service.folder_url(folder_id)
    database_session.commit()
    return {"task_id": task.id, "drive_link": task.drive_folder_url}


@router.get("/{task_id}/document", response_model=DocumentResponse)
def get_document(task_id: int, _: MainAnnotator, database_session: Session = Depends(get_db)) -> TaskDocument:
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        raise HTTPException(status_code=404, detail="No document has been processed for this task.")
    return document


def get_slides(task_id: int, _: User, database_session: Session) -> list[SlideResponse]:
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        raise HTTPException(status_code=404, detail="No document has been processed for this task.")
    slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == document.id).order_by(DocumentSlide.page_number)))
    annotations: dict[int, list[SlideAnnotation]] = {slide.id: [] for slide in slides}
    if slides:
        for annotation in database_session.scalars(
            select(SlideAnnotation)
            .where(SlideAnnotation.slide_id.in_([slide.id for slide in slides]))
            .order_by(SlideAnnotation.id)
        ):
            annotations[annotation.slide_id].append(annotation)
    return [slide_response(task_id, slide, annotations.get(slide.id)) for slide in slides]


@router.get("/{task_id}/slides", response_model=list[SlideResponse])
def list_slides(task_id: int, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> list[SlideResponse]:
    return get_slides(task_id, current_user, database_session)


@router.patch("/{task_id}/draft-position", response_model=dict)
def save_draft_position(
    task_id: int,
    payload: DraftPositionInput,
    _: MainAnnotator,
    database_session: Session = Depends(get_db),
) -> dict:
    task = get_task(task_id, database_session)
    slide = database_session.get(DocumentSlide, payload.slide_id)
    document = database_session.get(TaskDocument, slide.document_id) if slide else None
    if slide is None or document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found for this task.")
    task.current_slide_id = slide.id
    database_session.commit()
    return {
        "current_slide_id": slide.id,
        "current_image_id": slide.image_id,
        "current_page_number": slide.page_number,
        "current_image_url": f"/api/tasks/{task_id}/slides/{slide.id}/image",
        "drive_file_id": slide.drive_file_id,
    }


@router.get("/{task_id}/slides/{slide_id}", response_model=SlideResponse)
def get_slide(task_id: int, slide_id: int, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideResponse:
    slides = get_slides(task_id, current_user, database_session)
    for slide in slides:
        if slide.id == slide_id:
            return slide
    raise HTTPException(status_code=404, detail="Slide not found.")


@router.get("/{task_id}/slides/{slide_id}/image")
def get_slide_image(task_id: int, slide_id: int, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> Response:
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    return image_response(slide, task_id, current_user.id)


@router.get("/{task_id}/images/{image_id}")
def get_task_image(task_id: int, image_id: str, current_user: MainAnnotator,
                   database_session: Session = Depends(get_db)) -> Response:
    slide = database_session.scalar(
        select(DocumentSlide)
        .join(TaskDocument, TaskDocument.id == DocumentSlide.document_id)
        .where(TaskDocument.task_id == task_id, DocumentSlide.image_id == image_id)
    )
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide image does not belong to this task.")
    return image_response(slide, task_id, current_user.id)


def read_image_bytes(slide: DocumentSlide, task_id: int, user_id: int | None = None) -> tuple[bytes, str]:
    if slide.storage_path:
        try:
            return supabase_storage.download_image(slide.storage_path), slide.mime_type or "image/png"
        except Exception as error:
            print(
                f"Slide image unavailable task_id={task_id} image_id={slide.image_id} "
                f"path={slide.storage_path}: {error}"
            )
            raise HTTPException(status_code=404, detail="Slide image is not available.") from error
    if slide.drive_file_id:
        try:
            return drive_service.download_file_bytes(slide.drive_file_id, user_id=user_id)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=404, detail="Drive slide image is unavailable.") from error
    raise HTTPException(status_code=404, detail="Slide image is not available.")


def image_response(slide: DocumentSlide, task_id: int, user_id: int | None = None) -> Response:
    content, media_type = read_image_bytes(slide, task_id, user_id)
    return Response(content=content, media_type=media_type)


@router.get("/{task_id}/slides/{slide_id}/annotation", response_model=SlideAnnotationResponse | None)
def get_annotation(task_id: int, slide_id: int, _: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation | None:
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    return database_session.scalar(
        select(SlideAnnotation)
        .where(SlideAnnotation.slide_id == slide_id, SlideAnnotation.is_deleted.is_(False))
        .order_by(SlideAnnotation.id)
        .limit(1)
    )


def save_annotation(
    task_id: int,
    slide_id: int,
    payload: SlideAnnotationInput,
    current_user: User,
    database_session: Session,
    commit: bool = True,
) -> SlideAnnotation:
    task = get_task(task_id, database_session)
    if task.status not in {TaskStatus.IN_PROGRESS, TaskStatus.WAITING_FOR_DOCUMENT}:
        raise HTTPException(status_code=409, detail="This task is not accepting main annotations.")
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    if payload.image_id != slide.image_id:
        raise HTTPException(
            status_code=409,
            detail="Annotation image_id does not match the selected slide image.",
        )
    validate_question(task, payload)
    annotation = None
    if payload.annotation_id is not None:
        annotation = database_session.get(SlideAnnotation, payload.annotation_id)
        if annotation is None or annotation.slide_id != slide_id or annotation.is_deleted:
            raise HTTPException(status_code=404, detail="Draft annotation not found for this slide.")
    if annotation is None:
        annotation_count = database_session.scalar(select(func.count()).select_from(SlideAnnotation).where(
            SlideAnnotation.slide_id == slide_id,
            SlideAnnotation.is_deleted.is_(False),
        ))
        if annotation_count >= 10:
            raise HTTPException(status_code=409, detail="Each slide is limited to 10 annotations.")
        annotation = SlideAnnotation(slide_id=slide_id, created_by=current_user.id, question_type=task.output_type.value)
        database_session.add(annotation)
    annotation.categories = payload.categories
    annotation.slide_type = payload.slide_type
    annotation.language = payload.language
    annotation.question_type = task.output_type.value
    annotation.main_annotator_user_id = current_user.id
    annotation.question = normalized_question(payload.question)
    if annotation.id and not annotation.edit_answer and payload.answer != annotation.answer:
        raise HTTPException(status_code=409, detail="Answer editing is disabled for this annotation.")
    annotation.answer = payload.answer
    annotation.insight = payload.insight
    annotation.prompt = payload.prompt
    annotation.edit_answer = payload.edit_answer
    annotation.status = SlideStatus.COMPLETED
    annotation.publication_status = "SAVED"
    annotation.is_deleted = False
    annotation.main_label = 1
    annotation.blind_label = None
    annotation.reviewer_label = None
    database_session.flush()
    active_annotations = list(database_session.scalars(select(SlideAnnotation).where(
        SlideAnnotation.slide_id == slide_id,
        SlideAnnotation.is_deleted.is_(False),
    )))
    slide.status = (
        SlideStatus.COMPLETED
        if len(active_annotations) == 10 and all(item.status == SlideStatus.COMPLETED for item in active_annotations)
        else SlideStatus.IN_PROGRESS
    )
    if commit:
        database_session.commit()
    database_session.refresh(annotation)
    return annotation


@router.post("/{task_id}/slides/{slide_id}/annotations/import", response_model=list[SlideAnnotationPreview])
def import_slide_annotations(
    task_id: int,
    slide_id: int,
    payload: SlideAnnotationBatchInput,
    current_user: MainAnnotator,
    database_session: Session = Depends(get_db),
) -> list[SlideAnnotationPreview]:
    task = get_task(task_id, database_session)
    slide = database_session.get(DocumentSlide, slide_id)
    document = database_session.get(TaskDocument, slide.document_id) if slide else None
    if slide is None or document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    previews: list[SlideAnnotationPreview] = []
    for imported in payload.annotations:
        if imported.image_id != slide.image_id:
            raise HTTPException(
                status_code=409,
                detail="Annotation image_id does not match the selected slide image.",
            )
        normalized = imported.model_copy(update={"question": normalized_question(imported.question)})
        validate_question(task, normalized)
        previews.append(SlideAnnotationPreview(**normalized.model_dump(exclude={"annotation_id", "image_id"})))
    return previews


@router.post("/{task_id}/slides/{slide_id}/generate", response_model=list[SlideAnnotationPreview])
def generate_slide_annotation(task_id: int, slide_id: int, payload: GenerateAnnotationInput,
                              current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> list[SlideAnnotationPreview]:
    task = get_task(task_id, database_session)
    if task.status not in {TaskStatus.IN_PROGRESS, TaskStatus.WAITING_FOR_DOCUMENT}:
        raise HTTPException(status_code=409, detail="This task is not accepting main annotations.")
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    try:
        image_bytes, _ = read_image_bytes(slide, task_id, current_user.id)
        generated_items = generate_annotations(
            image_bytes,
            task.output_type.value,
            payload.language,
            prompt=payload.prompt,
            category=payload.category,
            count=10,
        )
        previews: list[SlideAnnotationPreview] = []
        for generated in generated_items:
            annotation_payload = SlideAnnotationInput(
                image_id=slide.image_id,
                categories=generated.get("category", payload.category),
                slide_type=1,
                language=payload.language,
                question=normalized_question(generated.get("question") or {}),
                answer=str(generated.get("answer") or "").strip(),
                prompt=payload.prompt,
                edit_answer=payload.edit_answer,
            )
            validate_question(task, annotation_payload)
            previews.append(SlideAnnotationPreview(**annotation_payload.model_dump(exclude={"annotation_id", "image_id"})))
        return previews
    except HTTPException:
        raise
    except Exception as error:
        database_session.rollback()
        raise HTTPException(status_code=422, detail=f"Gemini annotation generation failed: {error}") from error


@router.delete("/{task_id}/slides/{slide_id}/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft_annotation(
    task_id: int,
    slide_id: int,
    annotation_id: int,
    _: MainAnnotator,
    database_session: Session = Depends(get_db),
) -> Response:
    task = get_task(task_id, database_session)
    if task.status not in {TaskStatus.IN_PROGRESS, TaskStatus.WAITING_FOR_DOCUMENT}:
        raise HTTPException(status_code=409, detail="This task is not accepting annotation changes.")
    annotation = database_session.get(SlideAnnotation, annotation_id)
    slide = database_session.get(DocumentSlide, slide_id)
    document = database_session.get(TaskDocument, slide.document_id) if slide else None
    if annotation is None or annotation.slide_id != slide_id or document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Saved annotation not found for this slide.")
    if annotation.publication_status != "SAVED":
        raise HTTPException(status_code=409, detail="Published annotations cannot be deleted.")
    annotation.is_deleted = True
    annotation.publication_status = "SAVED"
    remaining = database_session.scalar(select(func.count()).select_from(SlideAnnotation).where(
        SlideAnnotation.slide_id == slide_id,
        SlideAnnotation.id != annotation_id,
        SlideAnnotation.is_deleted.is_(False),
    ))
    slide.status = SlideStatus.NOT_STARTED if not remaining else SlideStatus.IN_PROGRESS
    database_session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def get_owned_slide(task_id: int, slide_id: int, database_session: Session) -> tuple[Task, DocumentSlide, SlideAnnotation]:
    task = get_task(task_id, database_session)
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    annotation = database_session.scalar(select(SlideAnnotation).where(SlideAnnotation.slide_id == slide_id))
    if document is None or document.task_id != task_id or annotation is None:
        raise HTTPException(status_code=404, detail="Annotation not found.")
    return task, slide, annotation


def get_owned_annotation(
    task_id: int,
    annotation_id: int,
    database_session: Session,
    published_only: bool = False,
) -> tuple[Task, DocumentSlide, SlideAnnotation]:
    task = get_task(task_id, database_session)
    annotation = database_session.get(SlideAnnotation, annotation_id)
    slide = database_session.get(DocumentSlide, annotation.slide_id) if annotation else None
    document = database_session.get(TaskDocument, slide.document_id) if slide else None
    if (
        annotation is None
        or annotation.is_deleted
        or slide is None
        or document is None
        or document.task_id != task_id
        or (published_only and annotation.publication_status != "PUBLISHED")
    ):
        raise HTTPException(status_code=404, detail="Published annotation not found.")
    return task, slide, annotation


def copy_draft_to_record(
    task: Task,
    slide: DocumentSlide,
    annotation: SlideAnnotation,
    record: AnnotationRecord,
) -> None:
    record.created_by = annotation.main_annotator_user_id or annotation.created_by
    record.output_type = task.output_type.value
    record.image_id = slide.image_id
    record.generated_image_id = slide.image_id
    record.slide_name = slide.slide_name
    record.categories = annotation.categories
    record.slide_type = annotation.slide_type
    record.language = annotation.language
    record.drive_link = task.drive_folder_url
    record.main_label = 1
    record.main_annotator_user_id = annotation.main_annotator_user_id
    record.blind_label = None
    record.reviewer_label = None
    record.question = annotation.question
    record.answer = annotation.answer
    record.main_annotator = {"decision": 1}
    record.blind_annotator = None
    record.reviewer = None
    record.blind_question = None
    record.blind_answer = None
    record.similarity_score = None
    record.reject_reason = None
    record.final_status = "PENDING"
    record.annotation_status = "PUBLISHED"
    record.page_number = slide.page_number


@router.get("/{task_id}/blind/slides", response_model=list[dict])
def list_blind_slides(task_id: int, _: BlindAnnotator, database_session: Session = Depends(get_db)) -> list[dict]:
    task = get_task(task_id, database_session)
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        raise HTTPException(status_code=404, detail="No document has been processed for this task.")
    slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == document.id).order_by(DocumentSlide.page_number)))
    slide_map = {slide.id: slide for slide in slides}
    annotations = list(database_session.scalars(
        select(SlideAnnotation).where(
            SlideAnnotation.slide_id.in_(slide_map),
            SlideAnnotation.publication_status == "PUBLISHED",
            SlideAnnotation.is_deleted.is_(False),
        ).order_by(SlideAnnotation.slide_id, SlideAnnotation.id)
    )) if slides else []
    return [{"id": annotation.id, "annotation_id": annotation.id, "slide_id": annotation.slide_id,
             "page_number": slide_map[annotation.slide_id].page_number,
             "image_id": slide_map[annotation.slide_id].image_id,
             "slide_name": slide_map[annotation.slide_id].slide_name, "output_type": task.output_type.value,
             "blind_question": annotation.blind_question, "blind_answer": annotation.blind_answer,
             "blind_label": annotation.blind_label, "similarity_score": annotation.similarity_score,
             "reject_reason": annotation.reject_reason,
             "image_url": f"/api/tasks/{task_id}/blind/slides/{annotation.slide_id}/image",
             "status": slide_map[annotation.slide_id].status.value} for annotation in annotations]


@router.get("/{task_id}/blind/slides/{slide_id}/image")
def get_blind_slide_image(task_id: int, slide_id: int, current_user: BlindAnnotator,
                          database_session: Session = Depends(get_db)) -> Response:
    return get_slide_image_for_role(task_id, slide_id, database_session, current_user.id)


@router.get("/{task_id}/review/slides", response_model=list[SlideResponse])
def list_review_slides(task_id: int, current_user: Reviewer, database_session: Session = Depends(get_db)) -> list[SlideResponse]:
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        raise HTTPException(status_code=404, detail="No document has been processed for this task.")
    slides = list(database_session.scalars(
        select(DocumentSlide).where(DocumentSlide.document_id == document.id).order_by(DocumentSlide.page_number)
    ))
    slide_map = {slide.id: slide for slide in slides}
    annotations = list(database_session.scalars(select(SlideAnnotation).where(
        SlideAnnotation.slide_id.in_(slide_map),
        SlideAnnotation.publication_status == "PUBLISHED",
        SlideAnnotation.is_deleted.is_(False),
    ).order_by(SlideAnnotation.slide_id, SlideAnnotation.id))) if slides else []
    return [slide_response(task_id, slide_map[annotation.slide_id], [annotation]) for annotation in annotations]


def get_slides_for_role(task_id: int, current_user: User, database_session: Session) -> list[SlideResponse]:
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        raise HTTPException(status_code=404, detail="No document has been processed for this task.")
    slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == document.id).order_by(DocumentSlide.page_number)))
    annotations = {annotation.slide_id: annotation for annotation in database_session.scalars(
        select(SlideAnnotation).where(SlideAnnotation.slide_id.in_([slide.id for slide in slides]))
    )} if slides else {}
    return [slide_response(task_id, slide, annotations.get(slide.id)) for slide in slides]


@router.post("/{task_id}/slides/{slide_id}/blind", response_model=SlideAnnotationResponse)
def save_blind_annotation(task_id: int, slide_id: int, payload: BlindAnnotationInput, current_user: BlindAnnotator,
                          database_session: Session = Depends(get_db)) -> SlideAnnotation:
    task, slide, annotation = get_owned_annotation(task_id, slide_id, database_session, published_only=True)
    annotation.blind_question = normalized_question(payload.question)
    annotation.blind_answer = payload.answer
    annotation.blind_annotator_user_id = current_user.id
    record = database_session.get(AnnotationRecord, annotation.annotation_record_id) if annotation.annotation_record_id else None
    if record:
        record.blind_question = annotation.blind_question
        record.blind_answer = payload.answer
        record.blind_annotator_user_id = current_user.id
        record.similarity_score = text_similarity(
            str((annotation.question or {}).get("question_text", "")),
            str((annotation.blind_question or {}).get("question_text", "")),
        )
        if record.similarity_score >= 0.8:
            record.annotation_status = "COMPARISON_READY"
        else:
            record.annotation_status = "REQUIRES_RESOLUTION"
        annotation.similarity_score = record.similarity_score
    database_session.commit()
    database_session.refresh(annotation)
    return annotation


@router.post("/{task_id}/slides/{slide_id}/blind-decision", response_model=SlideAnnotationResponse)
def save_blind_decision(task_id: int, slide_id: int, payload: DecisionInput, current_user: BlindAnnotator,
                        database_session: Session = Depends(get_db)) -> SlideAnnotation:
    _, slide, annotation = get_owned_annotation(task_id, slide_id, database_session, published_only=True)
    if annotation.blind_question is None or not annotation.blind_answer:
        raise HTTPException(status_code=409, detail="Submit the blind annotation before deciding.")
    annotation.blind_label = payload.decision
    annotation.reject_reason = payload.reject_reason
    annotation.blind_annotator_user_id = current_user.id
    record = database_session.get(AnnotationRecord, annotation.annotation_record_id) if annotation.annotation_record_id else None
    if record:
        record.blind_label = payload.decision
        record.blind_annotator_user_id = current_user.id
        record.blind_annotator = {"decision": payload.decision, "reject_reason": payload.reject_reason}
        record.reject_reason = payload.reject_reason if payload.decision == 0 else record.reject_reason
        record.final_status = "KEEP" if record.main_label == record.blind_label == record.reviewer_label == 1 else "REJECTED" if payload.decision == 0 else "PENDING"
    database_session.commit()
    database_session.refresh(annotation)
    return annotation


@router.post("/{task_id}/slides/{slide_id}/main-decision", response_model=SlideAnnotationResponse)
def save_main_decision(task_id: int, slide_id: int, payload: DecisionInput, current_user: MainAnnotator,
                       database_session: Session = Depends(get_db)) -> SlideAnnotation:
    _, slide, annotation = get_owned_annotation(task_id, slide_id, database_session, published_only=True)
    annotation.main_label = payload.decision
    annotation.reject_reason = payload.reject_reason
    record = database_session.get(AnnotationRecord, annotation.annotation_record_id) if annotation.annotation_record_id else None
    if record:
        record.main_label = payload.decision
        record.main_annotator = {"decision": payload.decision, "reject_reason": payload.reject_reason}
        record.final_status = "KEEP" if record.main_label == record.blind_label == record.reviewer_label == 1 else "PENDING"
    database_session.commit()
    database_session.refresh(annotation)
    return annotation


@router.post("/{task_id}/slides/{slide_id}/review", response_model=SlideAnnotationResponse)
def save_reviewer_decision(task_id: int, slide_id: int, payload: DecisionInput, current_user: Reviewer,
                           database_session: Session = Depends(get_db)) -> SlideAnnotation:
    _, slide, annotation = get_owned_annotation(task_id, slide_id, database_session, published_only=True)
    if payload.decision == 1 and (annotation.main_label != 1 or annotation.blind_label != 1):
        raise HTTPException(status_code=409, detail="Main and Blind must accept before Reviewer can accept.")
    if payload.decision == 0 and not payload.reject_reason:
        raise HTTPException(status_code=422, detail="A reject reason is required when Reviewer rejects.")
    annotation.reviewer_label = payload.decision
    annotation.reviewer_user_id = current_user.id
    annotation.reject_reason = payload.reject_reason
    record = database_session.get(AnnotationRecord, annotation.annotation_record_id) if annotation.annotation_record_id else None
    if record:
        record.reviewer_label = payload.decision
        record.reviewer_user_id = current_user.id
        record.reviewer = {"decision": payload.decision, "reject_reason": payload.reject_reason}
        record.reject_reason = payload.reject_reason
        record.final_status = "KEEP" if record.main_label == record.blind_label == record.reviewer_label == 1 else "REJECTED" if payload.decision == 0 else "PENDING"
    database_session.commit()
    if payload.decision == 1 and record and record.main_label == record.blind_label == record.reviewer_label == 1:
        _export_final_dataset(database_session, task_id, current_user.id)
    database_session.refresh(annotation)
    return annotation


def _export_final_dataset(database_session: Session, task_id: int, user_id: int) -> TaskExport:
    task = get_task(task_id, database_session)
    if not task.drive_folder_id:
        raise HTTPException(status_code=422, detail="A Google Drive output folder is required before final acceptance.")
    records = list(database_session.scalars(select(AnnotationRecord).where(AnnotationRecord.task_id == task_id)))
    accepted = final_dataset_records(records)
    content, _ = serialize_records(accepted, "CSV")
    output_format = "CSV"
    file_name = filename(task.name, output_format)
    from app.services.drive_service import upload_file
    try:
        drive_file_id, drive_file_url = upload_file(
            task.drive_folder_id, file_name, content, output_format, user_id=user_id,
        )
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"Final Google Drive export failed: {error}") from error
    export = database_session.scalar(select(TaskExport).where(
        TaskExport.task_id == task_id, TaskExport.format == output_format,
    ))
    if export is None:
        export = TaskExport(task_id=task_id, format=output_format)
        database_session.add(export)
    export.drive_folder_id = task.drive_folder_id
    export.drive_file_id = drive_file_id
    export.drive_file_url = drive_file_url
    export.file_name = file_name
    export.status = "EXPORTED"
    database_session.commit()
    database_session.refresh(export)
    return export


@router.get("/{task_id}/review/slides/{slide_id}/image")
def get_review_slide_image(task_id: int, slide_id: int, current_user: Reviewer,
                           database_session: Session = Depends(get_db)) -> Response:
    return get_slide_image_for_role(task_id, slide_id, database_session, current_user.id)


def get_slide_image_for_role(
    task_id: int,
    slide_id: int,
    database_session: Session,
    user_id: int,
) -> Response:
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    return image_response(slide, task_id, user_id)


@router.post("/{task_id}/slides/{slide_id}/annotation", response_model=SlideAnnotationResponse)
def create_or_update_annotation(task_id: int, slide_id: int, payload: SlideAnnotationInput, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation:
    return save_annotation(task_id, slide_id, payload, current_user, database_session)


@router.patch("/{task_id}/slides/{slide_id}/annotation", response_model=SlideAnnotationResponse)
def update_annotation(task_id: int, slide_id: int, payload: SlideAnnotationInput, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation:
    return save_annotation(task_id, slide_id, payload, current_user, database_session)


@router.post("/{task_id}/submit", response_model=SubmitResponse)
def submit_task(task_id: int, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SubmitResponse:
    task = get_task(task_id, database_session)
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None or document.processing_status != ProcessingStatus.PROCESSED:
        raise HTTPException(status_code=409, detail="Process a document before submitting.")
    slides = list(database_session.scalars(
        select(DocumentSlide).where(DocumentSlide.document_id == document.id).order_by(DocumentSlide.page_number)
    ))
    annotations = list(database_session.scalars(select(SlideAnnotation).where(
        SlideAnnotation.slide_id.in_([slide.id for slide in slides])
    ).order_by(SlideAnnotation.id))) if slides else []
    active_by_slide = {
        slide.id: [annotation for annotation in annotations if annotation.slide_id == slide.id and not annotation.is_deleted]
        for slide in slides
    }
    completed = sum(
        len(active_by_slide[slide.id]) == 10
        and all(annotation.status == SlideStatus.COMPLETED for annotation in active_by_slide[slide.id])
        for slide in slides
    )
    if not slides or completed != len(slides):
        raise HTTPException(
            status_code=409,
            detail=(
                "Each slide needs exactly 10 complete draft labels and every draft row must be valid "
                f"before publishing ({completed} of {len(slides)} slides ready)."
            ),
        )

    for annotation in [item for item in annotations if item.is_deleted]:
        if annotation.annotation_record_id:
            record = database_session.get(AnnotationRecord, annotation.annotation_record_id)
            if record:
                database_session.delete(record)
        database_session.delete(annotation)

    claimed_record_ids = {
        annotation.annotation_record_id for annotation in annotations if annotation.annotation_record_id
    }
    slide_map = {slide.id: slide for slide in slides}
    for annotation in [item for item in annotations if not item.is_deleted]:
        slide = slide_map[annotation.slide_id]
        record = database_session.get(AnnotationRecord, annotation.annotation_record_id) if annotation.annotation_record_id else None
        if record is None:
            candidate_query = select(AnnotationRecord).where(
                AnnotationRecord.task_id == task_id,
                AnnotationRecord.image_id == slide.image_id,
            ).order_by(AnnotationRecord.id)
            if claimed_record_ids:
                candidate_query = candidate_query.where(AnnotationRecord.id.not_in(claimed_record_ids))
            record = database_session.scalar(candidate_query.limit(1))
        if record is None:
            record = AnnotationRecord(
                task_id=task_id,
                created_by=current_user.id,
                output_type=task.output_type.value,
                image_id=slide.image_id,
            )
            database_session.add(record)
            database_session.flush()
        copy_draft_to_record(task, slide, annotation, record)
        annotation.annotation_record_id = record.id
        annotation.publication_status = "PUBLISHED"
        annotation.main_label = 1
        annotation.blind_label = None
        annotation.reviewer_label = None
        claimed_record_ids.add(record.id)

    task.status = TaskStatus.SUBMITTED
    database_session.commit()
    return SubmitResponse(task_id=task_id, status=task.status.value, completed_slides=completed, total_slides=len(slides))
