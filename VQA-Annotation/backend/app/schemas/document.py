from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models.document import ProcessingStatus, SlideStatus


class DocumentResponse(BaseModel):
    id: int
    task_id: int
    original_filename: str
    slide_name: str
    drive_folder_id: str | None = None
    source_pdf_file_id: str | None = None
    source_pdf_url: str | None = None
    storage_reference: str
    processing_status: ProcessingStatus
    page_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DriveLinkInput(BaseModel):
    drive_link: str = Field(min_length=1, max_length=2048)

    @field_validator("drive_link")
    @classmethod
    def validate_drive_link(cls, value: str) -> str:
        normalized = str(HttpUrl(value))
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("drive_link must be an HTTP or HTTPS URL.")
        return normalized


class DriveDocumentSelection(BaseModel):
    folder_id: str = Field(min_length=1, max_length=255)
    pdf_file_id: str = Field(min_length=1, max_length=255)
    slide_name: str = Field(min_length=1, max_length=255)


class SlideResponse(BaseModel):
    id: int
    document_id: int
    page_number: int
    image_id: str
    drive_file_id: str | None = None
    drive_file_url: str | None = None
    slide_name: str
    image_reference: str
    image_url: str
    status: SlideStatus
    annotation: "SlideAnnotationResponse | None" = None

    model_config = ConfigDict(from_attributes=True)


class SlideAnnotationResponse(BaseModel):
    id: int
    slide_id: int
    categories: int
    slide_type: int
    language: int
    main_label: int | None = 1
    blind_label: int | None = None
    reviewer_label: int | None = None
    main_annotator_user_id: int | None = None
    blind_annotator_user_id: int | None = None
    reviewer_user_id: int | None = None
    blind_question: dict | None = None
    blind_answer: str | None = None
    similarity_score: float | None = None
    reject_reason: str | None = None
    final_status: str = "PENDING"
    question_type: str
    question: dict
    answer: str
    insight: str | None = None
    prompt: str | None = None
    edit_answer: bool = True
    status: SlideStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SlideAnnotationInput(BaseModel):
    categories: int = Field(ge=1, le=4)
    slide_type: int = Field(ge=1, le=3)
    language: int = Field(ge=1, le=2)
    question: dict
    answer: str = Field(min_length=1, max_length=10000)
    insight: str | None = Field(default=None, max_length=10000)
    prompt: str | None = Field(default=None, max_length=10000)
    edit_answer: bool = True

    @field_validator("question")
    @classmethod
    def question_must_be_object(cls, value: dict) -> dict:
        if not isinstance(value, dict):
            raise ValueError("Question must be an object.")
        return value

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer is required.")
        return value.strip()


class BlindAnnotationInput(BaseModel):
    question: dict
    answer: str = Field(min_length=1, max_length=10000)

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Answer is required.")
        return value.strip()


class GenerateAnnotationInput(BaseModel):
    prompt: str | None = Field(default=None, max_length=10000)
    language: int = Field(ge=1, le=2)
    edit_answer: bool = True


class DecisionInput(BaseModel):
    decision: int = Field(ge=0, le=1)
    reject_reason: str | None = Field(default=None, max_length=64)

    @field_validator("reject_reason")
    @classmethod
    def reject_reason_required_for_rejection(cls, value: str | None, info) -> str | None:
        if info.data.get("decision") == 0 and not value:
            raise ValueError("Reject reason is required when decision is 0.")
        if value and value not in {"CONTENT_MISMATCH", "SPELLING_ERROR", "FORMAT_ERROR", "OTHER"}:
            raise ValueError("Invalid reject reason.")
        return value


class SubmitResponse(BaseModel):
    task_id: int
    status: str
    completed_slides: int
    total_slides: int
