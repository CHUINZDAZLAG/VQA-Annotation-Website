import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class ProcessingStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class SlideStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class TaskDocument(Base):
    __tablename__ = "task_documents"
    __table_args__ = (UniqueConstraint("task_id", name="uq_task_document_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    slide_name: Mapped[str] = mapped_column(String(255), nullable=False)
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_pdf_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_pdf_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    storage_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus, name="document_processing_status"),
        default=ProcessingStatus.UPLOADED,
        nullable=False,
    )
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class DocumentSlide(Base):
    __tablename__ = "document_slides"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_document_slide_page"),
        UniqueConstraint("document_id", "image_id", name="uq_document_slide_image"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("task_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    image_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    drive_file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    slide_name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[SlideStatus] = mapped_column(
        Enum(SlideStatus, name="slide_status"), default=SlideStatus.NOT_STARTED, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
