from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base
from app.models.document import SlideStatus


class SlideAnnotation(Base):
    __tablename__ = "slide_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slide_id: Mapped[int] = mapped_column(ForeignKey("document_slides.id", ondelete="CASCADE"), nullable=False, index=True)
    annotation_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("annotation_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    publication_status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    categories: Mapped[int] = mapped_column(Integer, nullable=False)
    slide_type: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[int] = mapped_column(Integer, nullable=False)
    main_label: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
    blind_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewer_label: Mapped[int | None] = mapped_column(Integer, nullable=True)
    main_annotator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    blind_annotator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    blind_question: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    blind_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[dict] = mapped_column(JSON, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    insight: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_answer: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[SlideStatus] = mapped_column(
        Enum(SlideStatus, name="slide_annotation_status"), default=SlideStatus.COMPLETED, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
