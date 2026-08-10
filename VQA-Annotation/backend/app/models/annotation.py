from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class AnnotationRecord(Base):
    """One generated dataset row, preserving user and system-owned values."""

    __tablename__ = "annotation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    output_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    image_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    generated_image_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slide_name: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    categories: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    slide_type: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    language: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    drive_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    main_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    blind_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_annotator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    blind_annotator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    blind_question: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    blind_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    final_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    question: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_answer: Mapped[bool] = mapped_column(default=True, nullable=False)
    main_annotator: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    blind_annotator: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    annotation_status: Mapped[str] = mapped_column(String(32), default="SUBMITTED", nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )