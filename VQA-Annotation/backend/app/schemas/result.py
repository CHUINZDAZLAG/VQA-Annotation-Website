from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import OutputType


class AnnotationRecordCreate(BaseModel):
    image_id: str | None = Field(default=None, max_length=255)
    generated_image_id: str | None = Field(default=None, max_length=255)
    slide_name: str | None = Field(default=None, max_length=255)
    categories: int | None = None
    slide_type: int | None = None
    language: int | None = None
    question: dict[str, Any] | None = None
    answer: str | None = None
    decision: int | None = Field(default=None, ge=0, le=1)
    reject_reason: str | None = None
    reject_note: str | None = None
    page_number: int | None = Field(default=None, ge=1)


class AnnotationRecordResponse(BaseModel):
    id: int
    task_id: int
    created_by: int | None
    output_type: OutputType
    image_id: str | None
    generated_image_id: str | None
    slide_name: str | None
    categories: int | None
    slide_type: int | None
    language: int | None
    drive_link: str | None
    main_label: int | None
    blind_label: int | None
    reviewer_label: int | None
    main_annotator_user_id: int | None
    blind_annotator_user_id: int | None
    reviewer_user_id: int | None
    blind_question: dict[str, Any] | None
    blind_answer: str | None
    similarity_score: float | None
    reject_reason: str | None
    final_status: str
    question: dict[str, Any] | None
    answer: str | None
    main_annotator: dict[str, Any] | None
    blind_annotator: dict[str, Any] | None
    reviewer: dict[str, Any] | None
    annotation_status: str
    page_number: int | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GlobalAnnotationRecordResponse(AnnotationRecordResponse):
    task_name: str


class AgreementStats(BaseModel):
    total_annotations: int
    unanimous_agreement: int
    disagreement: int
    accept: int
    reject: int
    fleiss_kappa: float | None


class LabelCounts(BaseModel):
    label_0: int
    label_1: int


class FleissAgreementStats(BaseModel):
    total_records: int
    observations: int
    total_ratings: int
    annotators: dict[str, LabelCounts]
    p_observed: float | None
    p_expected: float | None
    fleiss_kappa: float | None


class TypeStats(AgreementStats):
    total: int


class TaskStatisticsResponse(BaseModel):
    task_id: int
    total_rows: int
    multiple_choice: TypeStats
    short_answer: TypeStats
    combined: TypeStats


class TaskResultsResponse(BaseModel):
    task_id: int
    statistics: TaskStatisticsResponse
    rows: list[AnnotationRecordResponse]


class GlobalDashboardResponse(BaseModel):
    task_count: int
    selected_task_id: int | None
    page: int
    page_size: int
    total_records: int
    total_approved: int
    total_rejected: int
    statistics: AgreementStats
    all: FleissAgreementStats
    multiple_choice: FleissAgreementStats
    short_answer: FleissAgreementStats
    multiple_choice_total: int
    short_answer_total: int
    tasks: list[dict[str, Any]]
    rows: list[GlobalAnnotationRecordResponse]


class TaskExportResponse(BaseModel):
    id: int
    task_id: int
    drive_folder_id: str | None
    drive_file_id: str | None
    drive_file_url: str | None
    file_name: str
    format: str
    status: str
    exported_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriveFolderUpdate(BaseModel):
    drive_folder_id: str = Field(min_length=1, max_length=255)
    drive_folder_url: str | None = Field(default=None, max_length=2048)


class ExportRequest(BaseModel):
    format: str = "JSON"
