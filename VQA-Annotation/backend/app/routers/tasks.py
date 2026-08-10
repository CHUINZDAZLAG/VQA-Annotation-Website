from typing import Annotated

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.config.database import get_db
from app.middleware.auth import require_admin, require_user
from app.models.annotation import AnnotationRecord
from app.models.document import DocumentSlide, TaskDocument, SlideStatus
from app.models.export import TaskExport
from app.models.task import Task, TaskAssignment, TaskStatus, TaskType
from app.models.user import SystemRole, User
from app.schemas.task import (
    AdminTaskResponse,
    TaskAssignmentResponse,
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    UserTaskResponse,
)
from app.services.result_service import agreement_stats

router = APIRouter(prefix="/api", tags=["tasks"])
AdminUser = Annotated[User, Depends(require_admin)]
NormalUser = Annotated[User, Depends(require_user)]


def _document_progress(database_session, task_id: int) -> tuple[int, int]:
    document = database_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task_id))
    if document is None:
        return 0, 0
    slides = list(database_session.scalars(select(DocumentSlide).where(DocumentSlide.document_id == document.id)))
    return len(slides), sum(slide.status == SlideStatus.COMPLETED for slide in slides)


def _assignment_response(assignment: TaskAssignment, user: User | None) -> TaskAssignmentResponse:
    return TaskAssignmentResponse(
        id=assignment.id,
        task_id=assignment.task_id,
        user_id=assignment.user_id,
        task_type=assignment.task_type,
        assigned_by=assignment.assigned_by,
        assigned_at=assignment.assigned_at,
        status=assignment.status,
        user_name=user.name if user else None,
        user_email=user.email if user else None,
    )


def _admin_task_response(database_session, task: Task) -> AdminTaskResponse:
    records = list(database_session.scalars(select(AnnotationRecord).where(AnnotationRecord.task_id == task.id)))
    result_stats = agreement_stats(records)
    assignments = list(database_session.scalars(
        select(TaskAssignment).where(TaskAssignment.task_id == task.id).order_by(TaskAssignment.task_type)
    ))
    users = {
        user.id: user
        for user in database_session.scalars(
            select(User).where(User.id.in_([assignment.user_id for assignment in assignments]))
        )
    } if assignments else {}
    return AdminTaskResponse(
        id=task.id,
        name=task.name,
        description=task.description,
        output_type=task.output_type,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        drive_folder_id=task.drive_folder_id,
        drive_folder_url=task.drive_folder_url,
        result_count=len(records),
        approved_count=sum((record.reviewer or {}).get("decision") == 1 for record in records),
        rejected_count=sum((record.reviewer or {}).get("decision") == 0 for record in records),
        result_fleiss_kappa=result_stats["fleiss_kappa"],
        assignments=[_assignment_response(assignment, users.get(assignment.user_id)) for assignment in assignments],
    )


def _validate_assignment_users(database_session, payload: TaskCreate | TaskUpdate) -> dict[TaskType, User]:
    requested = {
        TaskType.MAIN_ANNOTATOR: payload.main_annotator_id,
        TaskType.BLIND_ANNOTATOR: payload.blind_annotator_id,
        TaskType.REVIEWER: payload.reviewer_id,
    }
    users: dict[TaskType, User] = {}
    for task_type, user_id in requested.items():
        if user_id is None:
            continue
        user = database_session.get(User, user_id)
        if user is None or user.system_role != SystemRole.USER or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{task_type.value} must reference an active USER account.",
            )
        users[task_type] = user
    return users


def _replace_assignments(database_session, task: Task, admin_user: User, users: dict[TaskType, User]) -> None:
    existing = {
        assignment.task_type: assignment
        for assignment in database_session.scalars(select(TaskAssignment).where(TaskAssignment.task_id == task.id))
    }
    for task_type, assignment in existing.items():
        if task_type not in users:
            assignment.status = "INACTIVE"
    for task_type, user in users.items():
        assignment = existing.get(task_type)
        if assignment is None:
            database_session.add(TaskAssignment(
                task_id=task.id,
                user_id=user.id,
                task_type=task_type,
                assigned_by=admin_user.id,
            ))
        else:
            assignment.user_id = user.id
            assignment.assigned_by = admin_user.id
            assignment.status = "ACTIVE"
    task.status = TaskStatus.WAITING_FOR_DOCUMENT if len(users) == 3 else TaskStatus.DRAFT


@router.get("/admin/tasks", response_model=list[AdminTaskResponse])
def list_admin_tasks(_: AdminUser, database_session=Depends(get_db)) -> list[AdminTaskResponse]:
    return [_admin_task_response(database_session, task) for task in database_session.scalars(
        select(Task).order_by(Task.created_at.desc())
    )]


@router.post("/admin/tasks", response_model=AdminTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, admin_user: AdminUser, database_session=Depends(get_db)) -> AdminTaskResponse:
    users = _validate_assignment_users(database_session, payload)
    task = Task(name=payload.name, description=payload.description, output_type=payload.output_type)
    database_session.add(task)
    database_session.flush()
    _replace_assignments(database_session, task, admin_user, users)
    database_session.commit()
    database_session.refresh(task)
    return _admin_task_response(database_session, task)


@router.delete("/admin/tasks/{task_id}", response_model=AdminTaskResponse)
def archive_task(task_id: int, _: AdminUser, database_session=Depends(get_db)) -> AdminTaskResponse:
    task = database_session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    task.status = TaskStatus.ARCHIVED
    task.archived_at = datetime.now(timezone.utc)
    database_session.commit()
    database_session.refresh(task)
    return _admin_task_response(database_session, task)


@router.delete("/admin/tasks/{task_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
def delete_task_permanently(task_id: int, _: AdminUser, database_session=Depends(get_db)) -> None:
    task = database_session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    database_session.query(AnnotationRecord).filter(AnnotationRecord.task_id == task_id).delete(synchronize_session=False)
    database_session.query(TaskExport).filter(TaskExport.task_id == task_id).delete(synchronize_session=False)
    database_session.query(TaskAssignment).filter(TaskAssignment.task_id == task_id).delete(synchronize_session=False)
    database_session.delete(task)
    database_session.commit()


@router.get("/admin/tasks/{task_id}", response_model=AdminTaskResponse)
def get_admin_task(task_id: int, _: AdminUser, database_session=Depends(get_db)) -> AdminTaskResponse:
    task = database_session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return _admin_task_response(database_session, task)


@router.patch("/admin/tasks/{task_id}", response_model=AdminTaskResponse)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    admin_user: AdminUser,
    database_session=Depends(get_db),
) -> AdminTaskResponse:
    task = database_session.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    if payload.name is not None:
        task.name = payload.name
    if "description" in payload.model_fields_set:
        task.description = payload.description
    if payload.output_type is not None:
        task.output_type = payload.output_type
    assignment_fields = {"main_annotator_id", "blind_annotator_id", "reviewer_id"}
    if payload.model_fields_set & assignment_fields:
        users = _validate_assignment_users(database_session, payload)
        _replace_assignments(database_session, task, admin_user, users)
    database_session.commit()
    database_session.refresh(task)
    return _admin_task_response(database_session, task)


@router.get("/admin/tasks/{task_id}/assignments", response_model=list[TaskAssignmentResponse])
def list_assignments(task_id: int, _: AdminUser, database_session=Depends(get_db)) -> list[TaskAssignmentResponse]:
    assignments = list(database_session.scalars(select(TaskAssignment).where(TaskAssignment.task_id == task_id)))
    users = {user.id: user for user in database_session.scalars(select(User).where(
        User.id.in_([assignment.user_id for assignment in assignments])
    ))} if assignments else {}
    return [_assignment_response(assignment, users.get(assignment.user_id)) for assignment in assignments]


@router.get("/tasks", response_model=list[UserTaskResponse])
def list_user_tasks(current_user: NormalUser, database_session=Depends(get_db)) -> list[UserTaskResponse]:
    rows = database_session.execute(
        select(Task, TaskAssignment.task_type)
        .join(TaskAssignment, TaskAssignment.task_id == Task.id)
        .where(TaskAssignment.user_id == current_user.id, TaskAssignment.status == "ACTIVE")
    ).all()
    grouped: dict[int, UserTaskResponse] = {}
    for task, task_type in rows:
        if task.id not in grouped:
            page_count, completed_slides = _document_progress(database_session, task.id)
            grouped[task.id] = UserTaskResponse(
                id=task.id,
                name=task.name,
                description=task.description,
                output_type=task.output_type,
                status=task.status,
                created_at=task.created_at,
                updated_at=task.updated_at,
                assignments=[],
                document_page_count=page_count,
                completed_slides=completed_slides,
            )
        grouped[task.id].assignments.append(task_type)
    return list(grouped.values())


@router.get("/tasks/{task_id}", response_model=UserTaskResponse)
def get_user_task(task_id: int, current_user: NormalUser, database_session=Depends(get_db)) -> UserTaskResponse:
    task = database_session.get(Task, task_id)
    assignments = list(database_session.scalars(select(TaskAssignment).where(
        TaskAssignment.task_id == task_id,
        TaskAssignment.user_id == current_user.id,
        TaskAssignment.status == "ACTIVE",
    )))
    if task is None or not assignments:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned task not found.")
    page_count, completed_slides = _document_progress(database_session, task_id)
    return UserTaskResponse(
        id=task.id,
        name=task.name,
        description=task.description,
        output_type=task.output_type,
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        assignments=[assignment.task_type for assignment in assignments],
        document_page_count=page_count,
        completed_slides=completed_slides,
    )
