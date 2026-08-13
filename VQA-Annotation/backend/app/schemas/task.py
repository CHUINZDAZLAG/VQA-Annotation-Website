from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.task import OutputType, TaskStatus, TaskType


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    output_type: OutputType
    main_annotator_id: int | None = Field(default=None, gt=0)
    blind_annotator_id: int | None = Field(default=None, gt=0)
    reviewer_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Task name is required.")
        return value.strip()

    @field_validator("blind_annotator_id")
    @classmethod
    def blind_must_be_distinct(cls, value: int | None, info):
        if value is not None and value in {info.data.get("main_annotator_id"), info.data.get("reviewer_id")}:
            raise ValueError("Main Annotator, Blind Annotator, and Reviewer must be different users.")
        return value

    @field_validator("reviewer_id")
    @classmethod
    def reviewer_must_be_distinct(cls, value: int | None, info):
        if value is not None and value in {info.data.get("main_annotator_id"), info.data.get("blind_annotator_id")}:
            raise ValueError("Main Annotator, Blind Annotator, and Reviewer must be different users.")
        return value


class TaskUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    output_type: OutputType | None = None
    main_annotator_id: int | None = Field(default=None, gt=0)
    blind_annotator_id: int | None = Field(default=None, gt=0)
    reviewer_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def update_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("Task name is required.")
        return value.strip()

    @field_validator("blind_annotator_id")
    @classmethod
    def blind_must_be_distinct(cls, value: int | None, info):
        if value is not None and value in {info.data.get("main_annotator_id"), info.data.get("reviewer_id")}:
            raise ValueError("Main Annotator, Blind Annotator, and Reviewer must be different users.")
        return value

    @field_validator("reviewer_id")
    @classmethod
    def reviewer_must_be_distinct(cls, value: int | None, info):
        if value is not None and value in {info.data.get("main_annotator_id"), info.data.get("blind_annotator_id")}:
            raise ValueError("Main Annotator, Blind Annotator, and Reviewer must be different users.")
        return value


class TaskResponse(BaseModel):
    id: int
    name: str
    description: str | None
    output_type: OutputType
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    drive_folder_id: str | None = None
    drive_folder_url: str | None = None
    admin_drive_folder_id: str | None = None
    annotator_drive_folder_id: str | None = None
    current_slide_id: int | None = None
    drive_link: str | None = None
    result_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    result_fleiss_kappa: float | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskAssignmentCreate(BaseModel):
    user_id: int
    task_type: TaskType


class TaskAssignmentResponse(BaseModel):
    id: int
    task_id: int
    user_id: int
    task_type: TaskType
    assigned_by: int
    assigned_at: datetime
    status: str
    user_name: str | None = None
    user_email: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdminTaskResponse(TaskResponse):
    assignments: list[TaskAssignmentResponse]


class UserTaskResponse(TaskResponse):
    assignments: list[TaskType]
    document_page_count: int = 0
    completed_slides: int = 0