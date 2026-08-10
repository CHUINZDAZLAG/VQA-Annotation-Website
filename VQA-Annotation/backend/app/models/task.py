import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class TaskType(str, enum.Enum):
    MAIN_ANNOTATOR = "MAIN_ANNOTATOR"
    BLIND_ANNOTATOR = "BLIND_ANNOTATOR"
    REVIEWER = "REVIEWER"


class TaskStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ASSIGNED = "ASSIGNED"
    WAITING_FOR_DOCUMENT = "WAITING_FOR_DOCUMENT"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class OutputType(str, enum.Enum):
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    SHORT_ANSWER = "SHORT_ANSWER"


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    output_type: Mapped[OutputType] = mapped_column(
        Enum(OutputType, name="task_output_type"),
        default=OutputType.MULTIPLE_CHOICE,
        nullable=False,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"),
        default=TaskStatus.DRAFT,
        nullable=False,
    )
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_folder_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def drive_link(self) -> str | None:
        return self.drive_folder_url


class TaskAssignment(Base):
    __tablename__ = "task_assignments"
    __table_args__ = (
        UniqueConstraint("task_id", "task_type", name="uq_task_assignment_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType, name="task_type"), nullable=False)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)