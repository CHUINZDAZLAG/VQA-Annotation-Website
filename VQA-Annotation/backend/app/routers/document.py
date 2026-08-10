import re
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Annotated

import fitz
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.settings import settings
from app.middleware.auth import require_task_assignment
from app.models.annotation import AnnotationRecord
from app.models.document import DocumentSlide, ProcessingStatus, SlideStatus, TaskDocument
from app.models.slide_annotation import SlideAnnotation
from app.models.task import OutputType, Task, TaskStatus, TaskType
from app.models.user import User
from app.schemas.document import BlindAnnotationInput, DecisionInput, DocumentResponse, DriveDocumentSelection, DriveLinkInput, GenerateAnnotationInput, SlideAnnotationInput, SlideAnnotationResponse, SlideResponse, SubmitResponse
from app.services import drive_service
from app.services.gemini_service import generate_annotation
from app.services.storage_service import storage

router = APIRouter(prefix="/api/tasks", tags=["main-annotator-document"])
MainAnnotator = Annotated[User, Depends(require_task_assignment(TaskType.MAIN_ANNOTATOR))]
BlindAnnotator = Annotated[User, Depends(require_task_assignment(TaskType.BLIND_ANNOTATOR))]
Reviewer = Annotated[User, Depends(require_task_assignment(TaskType.REVIEWER))]
SLIDE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,254}$")


def generated_image_id(slide_name: str, page_number: int) -> str:
    return f"{slide_name}_page_{page_number:02d}"


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


def validate_question(task: Task, payload: SlideAnnotationInput) -> None:
    question = payload.question
    if not str(question.get("question_text", "")).strip():
        raise HTTPException(status_code=422, detail="question.question_text is required.")
    if task.output_type == OutputType.MULTIPLE_CHOICE:
        missing = [key for key in ("option_a", "option_b", "option_c", "option_d")
               if not str(question.get(key, question.get(f"option_{key[-1].upper()}", ""))).strip()]
        if missing:
            raise HTTPException(status_code=422, detail=f"Missing multiple-choice options: {', '.join(missing)}.")
        if payload.answer not in {"A", "B", "C", "D"}:
            raise HTTPException(status_code=422, detail="Multiple-choice answer must be A, B, C, or D.")
    elif not str(question.get("question_text", "")).strip().endswith("."):
        raise HTTPException(status_code=422, detail="Short-answer question must end with a period.")


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


def slide_response(task_id: int, slide: DocumentSlide, annotation: SlideAnnotation | None) -> SlideResponse:
    return SlideResponse(
        id=slide.id,
        document_id=slide.document_id,
        page_number=slide.page_number,
        image_id=slide.image_id,
        drive_file_id=slide.drive_file_id,
        drive_file_url=slide.drive_file_url,
        slide_name=slide.slide_name,
        image_reference=slide.image_reference,
        image_url=f"/api/tasks/{task_id}/slides/{slide.id}/image",
        status=slide.status,
        annotation=annotation_response(annotation),
    )


@router.post("/{task_id}/document", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_document(
    task_id: int,
    _: MainAnnotator,
    database_session: Session = Depends(get_db),
    document: UploadFile = File(...),
    slide_name: str = Form(...),
):
    task = require_document_task(task_id, database_session)
    existing = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))

    normalized_name = slide_name.strip()
    if not normalized_name or not SLIDE_NAME_PATTERN.fullmatch(normalized_name) or ".." in normalized_name:
        raise HTTPException(status_code=422, detail="slide_name contains invalid characters.")
    filename = Path(document.filename or "").name
    if not filename.lower().endswith(".pdf") or document.content_type not in {"application/pdf", "application/octet-stream", None}:
        raise HTTPException(status_code=415, detail="Only PDF files are accepted.")
    content = await document.read()
    if not content:
        raise HTTPException(status_code=422, detail="The PDF is empty.")
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="The uploaded file is not a valid PDF.")

    try:
        pdf = fitz.open(stream=content, filetype="pdf")
        if pdf.page_count == 0:
            raise HTTPException(status_code=422, detail="The PDF contains no pages.")
        document_path = storage.save_document(task_id, filename, content)
        slide_paths: list[tuple[int, str, Path]] = []
        for page_number, page in enumerate(pdf, start=1):
            image_id = generated_image_id(normalized_name, page_number)
            image_path = storage.slide_path(task_id, normalized_name, page_number)
            image_path.parent.mkdir(parents=True, exist_ok=True)
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).save(str(image_path))
            slide_paths.append((page_number, image_id, image_path))
        pdf.close()
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=422, detail="The PDF could not be processed.") from error

    if existing:
        old_slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == existing.id)))
        old_image_ids = {slide.image_id for slide in old_slides}
        database_session.query(AnnotationRecord).filter(
            AnnotationRecord.task_id == task_id,
            AnnotationRecord.image_id.in_(old_image_ids),
        ).delete(synchronize_session=False) if old_image_ids else None
        database_session.query(SlideAnnotation).filter(SlideAnnotation.slide_id.in_([slide.id for slide in old_slides])).delete(
            synchronize_session=False
        ) if old_slides else None
        database_session.query(DocumentSlide).filter(DocumentSlide.document_id == existing.id).delete(synchronize_session=False)
        database_session.delete(existing)
        database_session.flush()
    stored_document = TaskDocument(
        task_id=task_id,
        original_filename=filename,
        slide_name=normalized_name,
        storage_reference=str(document_path),
        processing_status=ProcessingStatus.PROCESSED,
        page_count=len(slide_paths),
    )
    database_session.add(stored_document)
    database_session.flush()
    for page_number, image_id, image_path in slide_paths:
        database_session.add(DocumentSlide(
            document_id=stored_document.id,
            page_number=page_number,
            image_id=image_id,
            slide_name=normalized_name,
            image_reference=str(image_path),
        ))
    storage.remove_stale_slide_files(task_id, {path for _, _, path in slide_paths})
    task.status = TaskStatus.IN_PROGRESS
    database_session.commit()
    database_session.refresh(stored_document)
    return {"document": DocumentResponse.model_validate(stored_document), "slides": get_slides(task_id, _, database_session)}


@router.get("/{task_id}/document/drive-files", response_model=list[dict])
def list_drive_documents(task_id: int, folder_id: str, _: MainAnnotator,
                         database_session: Session = Depends(get_db)) -> list[dict]:
    get_task(task_id, database_session)
    try:
        return drive_service.list_pdf_files(folder_id)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{task_id}/document/select", response_model=dict, status_code=status.HTTP_201_CREATED)
def select_drive_document(task_id: int, payload: DriveDocumentSelection, _: MainAnnotator,
                          database_session: Session = Depends(get_db)) -> dict:
    task = require_document_task(task_id, database_session)
    normalized_name = payload.slide_name.strip()
    if not SLIDE_NAME_PATTERN.fullmatch(normalized_name) or ".." in normalized_name:
        raise HTTPException(status_code=422, detail="slide_name contains invalid characters.")
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            temp_path = Path(handle.name)
        metadata = drive_service.download_pdf(payload.pdf_file_id, temp_path)
        parents = metadata.get("parents") or []
        if payload.folder_id not in parents:
            raise HTTPException(status_code=403, detail="The selected PDF is not inside the selected Drive folder.")
        pdf = fitz.open(temp_path)
        if pdf.page_count == 0:
            raise HTTPException(status_code=422, detail="The PDF contains no pages.")
        old_document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
        if old_document:
            old_slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == old_document.id)))
            old_image_ids = {slide.image_id for slide in old_slides}
            if old_image_ids:
                database_session.query(AnnotationRecord).filter(AnnotationRecord.task_id == task_id, AnnotationRecord.image_id.in_(old_image_ids)).delete(synchronize_session=False)
            if old_slides:
                database_session.query(SlideAnnotation).filter(SlideAnnotation.slide_id.in_([slide.id for slide in old_slides])).delete(synchronize_session=False)
            database_session.delete(old_document)
            database_session.flush()
        drive_service.delete_generated_pages(payload.folder_id, f"{normalized_name}_page_")
        slides: list[tuple[int, str, dict]] = []
        for page_number in range(1, pdf.page_count + 1):
            image_id = f"{normalized_name}_page_{page_number:02d}"
            image_bytes = pdf.load_page(page_number - 1).get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
            uploaded = drive_service.upload_page(payload.folder_id, f"{image_id}.png", image_bytes)
            slides.append((page_number, image_id, uploaded))
        pdf.close()
        stored_document = TaskDocument(
            task_id=task_id, original_filename=metadata["name"], slide_name=normalized_name,
            drive_folder_id=payload.folder_id, source_pdf_file_id=metadata["id"], source_pdf_url=metadata.get("webViewLink"),
            storage_reference=f"drive:{metadata['id']}", processing_status=ProcessingStatus.PROCESSED,
            page_count=len(slides),
        )
        database_session.add(stored_document)
        database_session.flush()
        for page_number, image_id, uploaded in slides:
            database_session.add(DocumentSlide(
                document_id=stored_document.id, page_number=page_number, image_id=image_id,
                drive_file_id=uploaded["id"], drive_file_url=uploaded["webViewLink"], slide_name=normalized_name,
                image_reference=uploaded["webViewLink"],
            ))
        task.status = TaskStatus.IN_PROGRESS
        database_session.commit()
        database_session.refresh(stored_document)
        return {"document": DocumentResponse.model_validate(stored_document), "slides": get_slides(task_id, _, database_session)}
    except HTTPException:
        database_session.rollback()
        raise
    except Exception as error:
        database_session.rollback()
        raise HTTPException(status_code=422, detail=f"Google Drive PDF processing failed: {error}") from error
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


@router.patch("/{task_id}/document/drive-link", response_model=dict)
def save_drive_link(task_id: int, payload: DriveLinkInput, current_user: MainAnnotator,
                    database_session: Session = Depends(get_db)) -> dict:
    task = get_task(task_id, database_session)
    task.drive_folder_url = payload.drive_link
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
    annotations = {annotation.slide_id: annotation for annotation in database_session.scalars(select(SlideAnnotation).where(SlideAnnotation.slide_id.in_([slide.id for slide in slides])))} if slides else {}
    return [slide_response(task_id, slide, annotations.get(slide.id)) for slide in slides]


@router.get("/{task_id}/slides", response_model=list[SlideResponse])
def list_slides(task_id: int, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> list[SlideResponse]:
    return get_slides(task_id, current_user, database_session)


@router.get("/{task_id}/slides/{slide_id}", response_model=SlideResponse)
def get_slide(task_id: int, slide_id: int, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideResponse:
    slides = get_slides(task_id, current_user, database_session)
    for slide in slides:
        if slide.id == slide_id:
            return slide
    raise HTTPException(status_code=404, detail="Slide not found.")


@router.get("/{task_id}/slides/{slide_id}/image")
def get_slide_image(task_id: int, slide_id: int, _: MainAnnotator, database_session: Session = Depends(get_db)) -> FileResponse:
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    image_path = Path(slide.image_reference).resolve()
    if slide.drive_file_id:
        try:
            content, media_type = drive_service.download_file_bytes(slide.drive_file_id)
            return Response(content=content, media_type=media_type)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=404, detail="Drive slide image is unavailable.") from error
    if not image_path.is_relative_to(storage.task_root(task_id).resolve()) or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Slide image is not available.")
    return FileResponse(image_path, media_type="image/png")


@router.get("/{task_id}/slides/{slide_id}/annotation", response_model=SlideAnnotationResponse | None)
def get_annotation(task_id: int, slide_id: int, _: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation | None:
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    return database_session.scalar(select(SlideAnnotation).where(SlideAnnotation.slide_id == slide_id))


def save_annotation(task_id: int, slide_id: int, payload: SlideAnnotationInput, current_user: User, database_session: Session) -> SlideAnnotation:
    task = get_task(task_id, database_session)
    if task.status not in {TaskStatus.IN_PROGRESS, TaskStatus.WAITING_FOR_DOCUMENT}:
        raise HTTPException(status_code=409, detail="This task is not accepting main annotations.")
    validate_question(task, payload)
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    annotation = database_session.scalar(select(SlideAnnotation).where(SlideAnnotation.slide_id == slide_id))
    if annotation is None:
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
    annotation.main_label = 1
    annotation.blind_label = None
    annotation.reviewer_label = None
    slide.status = SlideStatus.COMPLETED
    database_session.commit()
    database_session.refresh(annotation)
    record = database_session.scalar(select(AnnotationRecord).where(
        AnnotationRecord.task_id == task_id,
        AnnotationRecord.image_id == slide.image_id,
    ))
    if record is None:
        record = AnnotationRecord(task_id=task_id, created_by=current_user.id, image_id=slide.image_id)
        database_session.add(record)
    record.created_by = current_user.id
    record.output_type = task.output_type.value
    record.generated_image_id = slide.image_id
    record.slide_name = slide.slide_name
    record.categories = annotation.categories
    record.slide_type = annotation.slide_type
    record.language = annotation.language
    record.drive_link = task.drive_folder_url
    record.main_label = 1
    record.main_annotator_user_id = current_user.id
    record.blind_label = None
    record.reviewer_label = None
    record.question = annotation.question
    record.answer = annotation.answer
    record.main_annotator = {"decision": 1}
    record.blind_annotator = None
    record.reviewer = None
    record.annotation_status = "SUBMITTED"
    record.page_number = slide.page_number
    database_session.commit()
    database_session.refresh(annotation)
    return annotation


@router.post("/{task_id}/slides/{slide_id}/generate", response_model=SlideAnnotationResponse)
def generate_slide_annotation(task_id: int, slide_id: int, payload: GenerateAnnotationInput,
                              current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation:
    task, slide, existing = get_owned_slide(task_id, slide_id, database_session) if database_session.scalar(
        select(SlideAnnotation).where(SlideAnnotation.slide_id == slide_id)
    ) else (get_task(task_id, database_session), database_session.get(DocumentSlide, slide_id), None)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    try:
        image_bytes, _ = drive_service.download_file_bytes(slide.drive_file_id) if slide.drive_file_id else (
            Path(slide.image_reference).read_bytes(), "image/png"
        )
        generated = generate_annotation(image_bytes, task.output_type.value, payload.language, payload.prompt)
        question = generated["question"]
        answer = str(generated["answer"]).strip()
        annotation_payload = SlideAnnotationInput(
            categories=existing.categories if existing else 1,
            slide_type=existing.slide_type if existing else 1,
            language=payload.language,
            question=question,
            answer=answer,
            insight=existing.insight if existing else None,
            prompt=payload.prompt,
            edit_answer=payload.edit_answer,
        )
        validate_question(task, annotation_payload)
        annotation = save_annotation(task_id, slide_id, annotation_payload, current_user, database_session)
        return annotation
    except HTTPException:
        raise
    except Exception as error:
        database_session.rollback()
        raise HTTPException(status_code=422, detail=f"Gemini annotation generation failed: {error}") from error


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


@router.get("/{task_id}/blind/slides", response_model=list[dict])
def list_blind_slides(task_id: int, _: BlindAnnotator, database_session: Session = Depends(get_db)) -> list[dict]:
    task = get_task(task_id, database_session)
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        raise HTTPException(status_code=404, detail="No document has been processed for this task.")
    slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == document.id).order_by(DocumentSlide.page_number)))
    annotations = {annotation.slide_id: annotation for annotation in database_session.scalars(
        select(SlideAnnotation).where(SlideAnnotation.slide_id.in_([slide.id for slide in slides]))
    )} if slides else {}
    return [{"id": slide.id, "page_number": slide.page_number, "image_id": slide.image_id, "slide_name": slide.slide_name,
             "output_type": task.output_type.value, "blind_question": annotations.get(slide.id).blind_question if annotations.get(slide.id) else None,
             "blind_answer": annotations.get(slide.id).blind_answer if annotations.get(slide.id) else None,
             "blind_label": annotations.get(slide.id).blind_label if annotations.get(slide.id) else None,
             "similarity_score": annotations.get(slide.id).similarity_score if annotations.get(slide.id) else None,
             "reject_reason": annotations.get(slide.id).reject_reason if annotations.get(slide.id) else None,
             "image_url": f"/api/tasks/{task_id}/blind/slides/{slide.id}/image", "status": slide.status.value} for slide in slides]


@router.get("/{task_id}/blind/slides/{slide_id}/image")
def get_blind_slide_image(task_id: int, slide_id: int, _: BlindAnnotator,
                          database_session: Session = Depends(get_db)) -> Response:
    return get_slide_image_for_role(task_id, slide_id, database_session)


@router.get("/{task_id}/review/slides", response_model=list[SlideResponse])
def list_review_slides(task_id: int, current_user: Reviewer, database_session: Session = Depends(get_db)) -> list[SlideResponse]:
    return get_slides_for_role(task_id, current_user, database_session)


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
    task, slide, annotation = get_owned_slide(task_id, slide_id, database_session)
    annotation.blind_question = normalized_question(payload.question)
    annotation.blind_answer = payload.answer
    annotation.blind_annotator_user_id = current_user.id
    record = database_session.scalar(select(AnnotationRecord).where(AnnotationRecord.task_id == task_id, AnnotationRecord.image_id == slide.image_id))
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
    _, slide, annotation = get_owned_slide(task_id, slide_id, database_session)
    if annotation.blind_question is None or not annotation.blind_answer:
        raise HTTPException(status_code=409, detail="Submit the blind annotation before deciding.")
    annotation.blind_label = payload.decision
    annotation.reject_reason = payload.reject_reason
    annotation.blind_annotator_user_id = current_user.id
    record = database_session.scalar(select(AnnotationRecord).where(
        AnnotationRecord.task_id == task_id, AnnotationRecord.image_id == slide.image_id
    ))
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
    _, slide, annotation = get_owned_slide(task_id, slide_id, database_session)
    annotation.main_label = payload.decision
    annotation.reject_reason = payload.reject_reason
    record = database_session.scalar(select(AnnotationRecord).where(AnnotationRecord.task_id == task_id, AnnotationRecord.image_id == slide.image_id))
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
    _, slide, annotation = get_owned_slide(task_id, slide_id, database_session)
    annotation.reviewer_label = payload.decision
    annotation.reviewer_user_id = current_user.id
    annotation.reject_reason = payload.reject_reason
    record = database_session.scalar(select(AnnotationRecord).where(AnnotationRecord.task_id == task_id, AnnotationRecord.image_id == slide.image_id))
    if record:
        record.reviewer_label = payload.decision
        record.reviewer_user_id = current_user.id
        record.reviewer = {"decision": payload.decision, "reject_reason": payload.reject_reason}
        record.reject_reason = payload.reject_reason
        record.final_status = "KEEP" if record.main_label == record.blind_label == record.reviewer_label == 1 else "REJECTED" if payload.decision == 0 else "PENDING"
    database_session.commit()
    database_session.refresh(annotation)
    return annotation


@router.get("/{task_id}/review/slides/{slide_id}/image")
def get_review_slide_image(task_id: int, slide_id: int, _: Reviewer,
                           database_session: Session = Depends(get_db)) -> Response:
    return get_slide_image_for_role(task_id, slide_id, database_session)


def get_slide_image_for_role(task_id: int, slide_id: int, database_session: Session) -> Response:
    slide = database_session.get(DocumentSlide, slide_id)
    if slide is None:
        raise HTTPException(status_code=404, detail="Slide not found.")
    document = database_session.get(TaskDocument, slide.document_id)
    if document is None or document.task_id != task_id:
        raise HTTPException(status_code=404, detail="Slide not found.")
    if slide.drive_file_id:
        try:
            content, media_type = drive_service.download_file_bytes(slide.drive_file_id)
            return Response(content=content, media_type=media_type)
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=404, detail="Drive slide image is unavailable.") from error
    image_path = Path(slide.image_reference).resolve()
    if not image_path.is_relative_to(storage.task_root(task_id).resolve()) or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Slide image is not available.")
    return Response(content=image_path.read_bytes(), media_type="image/png")


@router.post("/{task_id}/slides/{slide_id}/annotation", response_model=SlideAnnotationResponse)
def create_or_update_annotation(task_id: int, slide_id: int, payload: SlideAnnotationInput, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation:
    return save_annotation(task_id, slide_id, payload, current_user, database_session)


@router.patch("/{task_id}/slides/{slide_id}/annotation", response_model=SlideAnnotationResponse)
def update_annotation(task_id: int, slide_id: int, payload: SlideAnnotationInput, current_user: MainAnnotator, database_session: Session = Depends(get_db)) -> SlideAnnotation:
    return save_annotation(task_id, slide_id, payload, current_user, database_session)


@router.post("/{task_id}/submit", response_model=SubmitResponse)
def submit_task(task_id: int, _: MainAnnotator, database_session: Session = Depends(get_db)) -> SubmitResponse:
    task = get_task(task_id, database_session)
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None or document.processing_status != ProcessingStatus.PROCESSED:
        raise HTTPException(status_code=409, detail="Process a document before submitting.")
    slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == document.id)))
    completed = sum(slide.status == SlideStatus.COMPLETED for slide in slides)
    if not slides or completed != len(slides):
        raise HTTPException(status_code=409, detail=f"Complete all slides before submitting ({completed} of {len(slides)} completed).")
    task.status = TaskStatus.SUBMITTED
    database_session.commit()
    return SubmitResponse(task_id=task_id, status=task.status.value, completed_slides=completed, total_slides=len(slides))
