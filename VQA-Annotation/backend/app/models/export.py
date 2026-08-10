from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base


class TaskExport(Base):
    __tablename__ = "task_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    drive_folder_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drive_file_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    format: Mapped[str] = mapped_column(String(16), nullable=False)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)