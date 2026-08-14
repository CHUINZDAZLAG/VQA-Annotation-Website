from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.middleware.auth import require_admin, require_user
from app.models.annotation import AnnotationRecord
from app.models.document import DocumentSlide, TaskDocument
from app.models.export import TaskExport
from app.models.slide_annotation import SlideAnnotation
from app.models.task import Task, TaskAssignment, TaskStatus, TaskType
from app.models.user import User
from app.schemas.result import (
    AnnotationRecordCreate,
    AnnotationRecordResponse,
    AgreementStats,
    DriveFolderUpdate,
    ExportRequest,
    GlobalAnnotationRecordResponse,
    GlobalDashboardResponse,
    TaskExportResponse,
    TaskResultsResponse,
    TaskStatisticsResponse,
    TypeStats,
)
from app.services.result_service import DatasetItem, agreement_stats, build_dataset_package, filename, final_dataset_records, fleiss_agreement_stats, serialize_records
from app.services.storage_service import supabase_storage

router = APIRouter(prefix="/api", tags=["task-results"])
AdminUser = Annotated[User, Depends(require_admin)]
NormalUser = Annotated[User, Depends(require_user)]


def _task_or_404(database_session: Session, task_id: int) -> Task:
    task = database_session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return task


def _records(database_session: Session, task_id: int, output_type: str | None = None,
             categories: int | None = None, slide_type: int | None = None,
             language: int | None = None, annotation_status: str | None = None,
             main_decision: int | None = Query(default=None, alias="main_annotator_decision"),
             blind_decision: int | None = Query(default=None, alias="blind_annotator_decision"),
             reviewer_decision: int | None = Query(default=None, alias="reviewer_decision"),
             search: str | None = None) -> list[AnnotationRecord]:
    query = select(AnnotationRecord).where(AnnotationRecord.task_id == task_id).order_by(AnnotationRecord.id)
    if output_type:
        query = query.where(AnnotationRecord.output_type == output_type.upper())
    if categories is not None:
        query = query.where(AnnotationRecord.categories == categories)
    if slide_type is not None:
        query = query.where(AnnotationRecord.slide_type == slide_type)
    if language is not None:
        query = query.where(AnnotationRecord.language == language)
    if annotation_status:
        query = query.where(AnnotationRecord.annotation_status == annotation_status)
    if search:
        pattern = search.lower()
    records = list(database_session.scalars(query))
    if main_decision is not None:
        records = [record for record in records if (record.main_annotator or {}).get("decision") == main_decision]
    if blind_decision is not None:
        records = [record for record in records if (record.blind_annotator or {}).get("decision") == blind_decision]
    if reviewer_decision is not None:
        records = [record for record in records if (record.reviewer or {}).get("decision") == reviewer_decision]
    if search:
        records = [
            record for record in records
            if pattern in ((record.question or {}).get("question_text") or "").lower()
            or pattern in (record.image_id or "").lower()
            or pattern in (record.slide_name or "").lower()
        ]
    return records


def _type_stats(records: list[AnnotationRecord]) -> TypeStats:
    agreement = agreement_stats(records)
    return TypeStats(total=len(records), **agreement)


def _statistics(task_id: int, records: list[AnnotationRecord]) -> TaskStatisticsResponse:
    multiple_choice = [record for record in records if record.output_type == "MULTIPLE_CHOICE"]
    short_answer = [record for record in records if record.output_type == "SHORT_ANSWER"]
    return TaskStatisticsResponse(
        task_id=task_id,
        total_rows=len(records),
        multiple_choice=_type_stats(multiple_choice),
        short_answer=_type_stats(short_answer),
        combined=_type_stats(records),
    )


def _dataset_items(database_session: Session, records: list[AnnotationRecord]) -> list[DatasetItem]:
    if not records:
        return []
    record_ids = [record.id for record in records]
    rows = database_session.execute(
        select(SlideAnnotation, DocumentSlide, TaskDocument)
        .join(DocumentSlide, DocumentSlide.id == SlideAnnotation.slide_id)
        .join(TaskDocument, TaskDocument.id == DocumentSlide.document_id)
        .where(SlideAnnotation.annotation_record_id.in_(record_ids))
    ).all()
    mappings: dict[int, list[tuple[DocumentSlide, TaskDocument]]] = {}
    for annotation, slide, document in rows:
        mappings.setdefault(annotation.annotation_record_id, []).append((slide, document))
    items: list[DatasetItem] = []
    for record in records:
        record_mappings = mappings.get(record.id, [])
        if len(record_mappings) != 1:
            reason = "orphaned" if not record_mappings else "duplicated"
            raise HTTPException(
                status_code=409,
                detail=f"Annotation {record.id} has an {reason} slide mapping.",
            )
        slide, document = record_mappings[0]
        items.append(DatasetItem(record=record, slide=slide, document=document))
    return items


def _dataset_zip(database_session: Session, records: list[AnnotationRecord]) -> bytes:
    try:
        content, _ = build_dataset_package(
            _dataset_items(database_session, records),
            supabase_storage.download_image,
        )
        return content
    except HTTPException:
        raise
    except (RuntimeError, ValueError) as error:
        raise HTTPException(status_code=409, detail=f"Dataset export validation failed: {error}") from error


def _global_rows(database_session: Session, task_id: int | None = None,
                 output_type: str | None = None, categories: int | None = None,
                 slide_type: int | None = None, language: int | None = None,
                 annotation_status: str | None = None, search: str | None = None,
                 main_decision: int | None = None, blind_decision: int | None = None,
                 reviewer_decision: int | None = None) -> list[tuple[AnnotationRecord, Task]]:
    query = select(AnnotationRecord, Task).join(Task, Task.id == AnnotationRecord.task_id)
    if task_id is not None:
        query = query.where(AnnotationRecord.task_id == task_id)
    if output_type:
        query = query.where(AnnotationRecord.output_type == output_type.upper())
    if categories is not None:
        query = query.where(AnnotationRecord.categories == categories)
    if slide_type is not None:
        query = query.where(AnnotationRecord.slide_type == slide_type)
    if language is not None:
        query = query.where(AnnotationRecord.language == language)
    if annotation_status:
        query = query.where(AnnotationRecord.annotation_status == annotation_status)
    rows = list(database_session.execute(query.order_by(AnnotationRecord.id)).all())
    if main_decision is not None:
        rows = [row for row in rows if (row[0].main_annotator or {}).get("decision") == main_decision]
    if blind_decision is not None:
        rows = [row for row in rows if (row[0].blind_annotator or {}).get("decision") == blind_decision]
    if reviewer_decision is not None:
        rows = [row for row in rows if (row[0].reviewer or {}).get("decision") == reviewer_decision]
    if search:
        pattern = search.lower()
        rows = [
            row for row in rows
            if pattern in row[1].name.lower()
            or pattern in (row[0].image_id or "").lower()
            or pattern in (row[0].slide_name or "").lower()
            or pattern in ((row[0].question or {}).get("question_text") or "").lower()
        ]
    return rows


@router.get("/admin/dashboard", response_model=GlobalDashboardResponse)
def get_global_dashboard(
    _: AdminUser,
    database_session: Session = Depends(get_db),
    task_id: int | None = None,
    output_type: str | None = None,
    categories: int | None = None,
    slide_type: int | None = None,
    language: int | None = None,
    annotation_status: str | None = None,
    main_annotator_decision: int | None = Query(default=None, ge=0, le=1),
    blind_annotator_decision: int | None = Query(default=None, ge=0, le=1),
    reviewer_decision: int | None = Query(default=None, ge=0, le=1),
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> GlobalDashboardResponse:
    rows_with_tasks = _global_rows(
        database_session, task_id, output_type, categories, slide_type, language,
        annotation_status, search, main_annotator_decision,
        blind_annotator_decision, reviewer_decision,
    )
    records = [record for record, _ in rows_with_tasks]
    statistics = agreement_stats(records)
    all_agreement = fleiss_agreement_stats(records)
    multiple_choice_agreement = fleiss_agreement_stats(
        [record for record in records if record.output_type == "MULTIPLE_CHOICE"]
    )
    short_answer_agreement = fleiss_agreement_stats(
        [record for record in records if record.output_type == "SHORT_ANSWER"]
    )
    approved = sum((record.reviewer or {}).get("decision") == 1 for record in records)
    rejected = sum((record.reviewer or {}).get("decision") == 0 for record in records)
    task_query = select(Task).order_by(Task.created_at.desc())
    available_tasks = list(database_session.scalars(task_query))
    selected_tasks = [task for task in available_tasks if task_id is None or task.id == task_id]
    start = (page - 1) * page_size
    paged_rows = rows_with_tasks[start:start + page_size]
    response_rows = []
    for record, task in paged_rows:
        values = AnnotationRecordResponse.model_validate(record).model_dump()
        values["task_name"] = task.name
        response_rows.append(GlobalAnnotationRecordResponse.model_validate(values))
    return GlobalDashboardResponse(
        task_count=len(selected_tasks),
        selected_task_id=task_id,
        page=page,
        page_size=page_size,
        total_records=len(records),
        total_approved=approved,
        total_rejected=rejected,
        statistics=AgreementStats(**statistics),
        all=all_agreement,
        multiple_choice=multiple_choice_agreement,
        short_answer=short_answer_agreement,
        multiple_choice_total=sum(record.output_type == "MULTIPLE_CHOICE" for record in records),
        short_answer_total=sum(record.output_type == "SHORT_ANSWER" for record in records),
        tasks=[{"id": task.id, "name": task.name, "status": task.status.value} for task in available_tasks],
        rows=response_rows,
    )


@router.get("/admin/tasks/{task_id}/results", response_model=TaskResultsResponse)
def get_results(
    task_id: int,
    _: AdminUser,
    database_session: Session = Depends(get_db),
    output_type: str | None = None,
    categories: int | None = None,
    slide_type: int | None = None,
    language: int | None = None,
    annotation_status: str | None = None,
    main_annotator_decision: int | None = Query(default=None, ge=0, le=1),
    blind_annotator_decision: int | None = Query(default=None, ge=0, le=1),
    reviewer_decision: int | None = Query(default=None, ge=0, le=1),
    search: str | None = None,
) -> TaskResultsResponse:
    _task_or_404(database_session, task_id)
    records = _records(database_session, task_id, output_type, categories, slide_type, language,
                       annotation_status, main_annotator_decision, blind_annotator_decision,
                       reviewer_decision, search)
    return TaskResultsResponse(task_id=task_id, statistics=_statistics(task_id, records), rows=records)


@router.get("/admin/tasks/{task_id}/statistics", response_model=TaskStatisticsResponse)
def get_statistics(task_id: int, _: AdminUser, database_session: Session = Depends(get_db)) -> TaskStatisticsResponse:
    _task_or_404(database_session, task_id)
    records = _records(database_session, task_id)
    return _statistics(task_id, records)


@router.patch("/admin/tasks/{task_id}/drive-folder", response_model=dict)
def set_drive_folder(task_id: int, payload: DriveFolderUpdate, current_user: AdminUser,
                     database_session: Session = Depends(get_db)) -> dict:
    task = _task_or_404(database_session, task_id)
    try:
        from app.services import drive_service
        folder_id = drive_service.verify_writable_folder(
            payload.drive_folder_id, user_id=getattr(current_user, "id", None),
        )
    except Exception as error:
        status_code = getattr(getattr(error, "resp", None), "status", None)
        detail = (
            "Google Drive permission denied. Please share the destination folder with the configured "
            "Drive account with Editor access."
            if status_code in {401, 403} or isinstance(error, PermissionError)
            else str(error)
        )
        raise HTTPException(status_code=422, detail=detail) from error
    task.admin_drive_folder_id = folder_id
    if not task.annotator_drive_folder_id:
        task.drive_folder_id = folder_id
        task.drive_folder_url = drive_service.folder_url(folder_id)
    database_session.commit()
    return {
        "task_id": task.id,
        "admin_drive_folder_id": task.admin_drive_folder_id,
        "drive_folder_id": task.drive_folder_id,
        "drive_folder_url": task.drive_folder_url,
    }


@router.get("/admin/tasks/{task_id}/google-drive/health", response_model=dict)
def google_drive_health(task_id: int, current_user: AdminUser, database_session: Session = Depends(get_db)) -> dict:
    task = _task_or_404(database_session, task_id)
    folder_id = task.drive_folder_id or task.annotator_drive_folder_id or task.admin_drive_folder_id
    if not folder_id:
        raise HTTPException(status_code=422, detail="This task does not have a Google Drive folder configured.")
    try:
        from app.services import drive_service
        user_id = getattr(current_user, "id", None)
        if user_id is None:
            verified_folder_id = drive_service.verify_writable_folder(folder_id)
            authentication = drive_service.authentication_info()
        else:
            verified_folder_id = drive_service.verify_writable_folder(folder_id, user_id=user_id)
            authentication = drive_service.authentication_info(user_id=user_id)
    except Exception as error:
        status_code = getattr(getattr(error, "resp", None), "status", None)
        detail = (
            "Google Drive authentication or folder permission failed. Share the task folder with the "
            "configured backend account with Editor access."
            if status_code in {401, 403} or isinstance(error, PermissionError)
            else str(error)
        )
        raise HTTPException(status_code=503, detail=detail) from error
    return {
        "status": "ok",
        "folder_id": verified_folder_id,
        "authentication_method": authentication["method"],
        "account_email": authentication["account_email"],
    }


@router.get("/admin/tasks/{task_id}/exports", response_model=list[TaskExportResponse])
def list_exports(task_id: int, _: AdminUser, database_session: Session = Depends(get_db)) -> list[TaskExport]:
    _task_or_404(database_session, task_id)
    return list(database_session.scalars(select(TaskExport).where(TaskExport.task_id == task_id).order_by(TaskExport.exported_at.desc())))


@router.post("/admin/tasks/{task_id}/export", response_model=TaskExportResponse, status_code=status.HTTP_201_CREATED)
def export_task(task_id: int, payload: ExportRequest, current_user: AdminUser,
                database_session: Session = Depends(get_db)) -> TaskExport:
    task = _task_or_404(database_session, task_id)
    output_format = payload.format.upper()
    if output_format not in {"JSON", "CSV", "ZIP"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Export format must be JSON, CSV, or ZIP.")
    records = final_dataset_records(_records(database_session, task_id))
    content = _dataset_zip(database_session, records) if output_format == "ZIP" else serialize_records(records, output_format)[0]
    export = database_session.scalar(select(TaskExport).where(
        TaskExport.task_id == task.id,
        TaskExport.format == output_format,
    ))
    if export is None:
        export = TaskExport(task_id=task.id, format=output_format)
        database_session.add(export)
    export.drive_folder_id = task.drive_folder_id
    export.file_name = (
        f"{'_'.join(task.name.strip().split()) or 'task'}_dataset-v1.0.zip"
        if output_format == "ZIP"
        else filename(task.name, output_format)
    )
    export.status = "EXPORTED"
    # Drive upload is intentionally backend-only; metadata remains usable when Drive is not configured.
    try:
        export.drive_file_id, export.drive_file_url = _upload_to_drive(
            task, export.file_name, content, output_format, current_user.id,
        )
    except Exception as error:
        database_session.rollback()
        raise HTTPException(
            status_code=502,
            detail="Google Drive export failed. Check backend authentication and Task folder permissions.",
        ) from error
    database_session.commit()
    database_session.refresh(export)
    return export


@router.get("/admin/tasks/{task_id}/exports/{export_id}/download")
def download_export(task_id: int, export_id: int, _: AdminUser,
                    database_session: Session = Depends(get_db)) -> Response:
    task = _task_or_404(database_session, task_id)
    export = database_session.get(TaskExport, export_id)
    if export is None or export.task_id != task.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export not found.")
    records = final_dataset_records(_records(database_session, task_id))
    if export.format == "ZIP":
        content, media_type = _dataset_zip(database_session, records), "application/zip"
    else:
        content, media_type = serialize_records(records, export.format)
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{export.file_name}"'})


def _upload_to_drive(
    task: Task,
    file_name: str,
    content: bytes,
    output_format: str,
    user_id: int,
) -> tuple[str | None, str | None]:
    if not task.drive_folder_id:
        return None, None
    from app.services.drive_service import upload_file
    return upload_file(task.drive_folder_id, file_name, content, output_format, user_id=user_id)


@router.post("/tasks/{task_id}/annotations", response_model=AnnotationRecordResponse, status_code=status.HTTP_201_CREATED)
def save_annotation(task_id: int, payload: AnnotationRecordCreate, current_user: NormalUser,
                    database_session: Session = Depends(get_db)) -> AnnotationRecord:
    task = _task_or_404(database_session, task_id)
    assignment = database_session.scalar(select(TaskAssignment).where(
        TaskAssignment.task_id == task_id,
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status == "ACTIVE",
    ))
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not assigned to this task.")
    record = database_session.scalar(select(AnnotationRecord).where(
        AnnotationRecord.task_id == task_id,
        AnnotationRecord.image_id == payload.image_id,
    )) if payload.image_id else None
    if record is None:
        record = AnnotationRecord(task_id=task.id, created_by=current_user.id, output_type=task.output_type.value)
        database_session.add(record)
    for field in ("image_id", "generated_image_id", "slide_name", "categories", "slide_type", "language", "question", "answer", "page_number"):
        value = getattr(payload, field)
        if value is not None:
            setattr(record, field, value)
    role = {TaskType.MAIN_ANNOTATOR: "main_annotator", TaskType.BLIND_ANNOTATOR: "blind_annotator", TaskType.REVIEWER: "reviewer"}[assignment.task_type]
    if payload.decision is not None or payload.reject_reason is not None or payload.reject_note is not None:
        setattr(record, role, {"decision": payload.decision, "reject_reason": payload.reject_reason, "reject_note": payload.reject_note})
    database_session.commit()
    database_session.refresh(record)
    return record
