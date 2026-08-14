from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config.settings import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def migrate_user_system_role() -> None:
    """Add the new system role column without dropping or rewriting user data."""
    with engine.begin() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("users")}
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS system_role VARCHAR(16)"))
        if "role" in columns:
            connection.execute(
                text("UPDATE users SET system_role = CASE WHEN role = 'ADMIN' THEN 'ADMIN' ELSE 'USER' END "
                     "WHERE system_role IS NULL")
            )
        else:
            connection.execute(text("UPDATE users SET system_role = 'USER' WHERE system_role IS NULL"))
        if "role" in columns:
            connection.execute(text("ALTER TABLE users ALTER COLUMN role DROP NOT NULL"))


def migrate_task_management() -> None:
    """Add Milestone 2 task fields and enum values without resetting task data."""
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for value in (
            "DRAFT", "ASSIGNED", "WAITING_FOR_DOCUMENT", "SUBMITTED", "UNDER_REVIEW", "ARCHIVED"
        ):
            connection.execute(text(
                f"DO $$ BEGIN ALTER TYPE task_status ADD VALUE IF NOT EXISTS '{value}'; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            ))

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS description VARCHAR(4000)"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS output_type VARCHAR(32)"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS drive_folder_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS drive_folder_url VARCHAR(2048)"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS admin_drive_folder_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS annotator_drive_folder_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS current_slide_id INTEGER"))
        connection.execute(text(
            "UPDATE tasks SET admin_drive_folder_id = drive_folder_id "
            "WHERE admin_drive_folder_id IS NULL AND drive_folder_id IS NOT NULL"
        ))
        connection.execute(text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ"))
        connection.execute(text("UPDATE tasks SET output_type = 'MULTIPLE_CHOICE' WHERE output_type IS NULL"))
        connection.execute(text("ALTER TABLE tasks ALTER COLUMN output_type SET DEFAULT 'MULTIPLE_CHOICE'"))
        connection.execute(text("ALTER TABLE tasks ALTER COLUMN output_type SET NOT NULL"))
        connection.execute(text("UPDATE tasks SET status = 'DRAFT' WHERE status = 'OPEN'"))
        connection.execute(text("ALTER TABLE tasks ALTER COLUMN status SET DEFAULT 'DRAFT'"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN system_role SET DEFAULT 'USER'"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN system_role SET NOT NULL"))


def migrate_main_annotator_fields() -> None:
    """Add Main Annotator output and deferred agreement fields without rewriting data."""
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS drive_link VARCHAR(2048)"))
        connection.execute(text("ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS main_label INTEGER"))
        connection.execute(text("ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS blind_label INTEGER"))
        connection.execute(text("ALTER TABLE annotation_records ADD COLUMN IF NOT EXISTS reviewer_label INTEGER"))
        connection.execute(text("ALTER TABLE slide_annotations ADD COLUMN IF NOT EXISTS main_label INTEGER DEFAULT 1"))
        connection.execute(text("ALTER TABLE slide_annotations ADD COLUMN IF NOT EXISTS blind_label INTEGER"))
        connection.execute(text("ALTER TABLE slide_annotations ADD COLUMN IF NOT EXISTS reviewer_label INTEGER"))
        connection.execute(text("ALTER TABLE task_documents ADD COLUMN IF NOT EXISTS drive_folder_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE task_documents ADD COLUMN IF NOT EXISTS source_pdf_file_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE task_documents ADD COLUMN IF NOT EXISTS source_pdf_url VARCHAR(2048)"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS drive_file_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS drive_file_url VARCHAR(2048)"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS drive_folder_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS storage_path VARCHAR(1024)"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS width INTEGER"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS height INTEGER"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS file_size INTEGER"))
        connection.execute(text("ALTER TABLE document_slides ADD COLUMN IF NOT EXISTS mime_type VARCHAR(100)"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_document_slides_image_id ON document_slides (image_id)"
        ))
        connection.execute(text("ALTER TABLE slide_annotations DROP CONSTRAINT IF EXISTS uq_slide_annotation_slide"))
        connection.execute(text("ALTER TABLE slide_annotations ADD COLUMN IF NOT EXISTS annotation_record_id INTEGER"))
        connection.execute(text("ALTER TABLE slide_annotations ADD COLUMN IF NOT EXISTS publication_status VARCHAR(16) DEFAULT 'PUBLISHED'"))
        connection.execute(text("UPDATE slide_annotations SET publication_status = 'PUBLISHED' WHERE publication_status IS NULL"))
        connection.execute(text("UPDATE slide_annotations SET publication_status = 'SAVED' WHERE publication_status = 'DRAFT'"))
        connection.execute(text("ALTER TABLE slide_annotations ALTER COLUMN publication_status SET DEFAULT 'SAVED'"))
        connection.execute(text("ALTER TABLE slide_annotations ALTER COLUMN publication_status SET NOT NULL"))
        connection.execute(text("ALTER TABLE slide_annotations ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE"))
        connection.execute(text("UPDATE slide_annotations SET is_deleted = FALSE WHERE is_deleted IS NULL"))
        connection.execute(text("ALTER TABLE slide_annotations ALTER COLUMN is_deleted SET NOT NULL"))
        connection.execute(text("ALTER TABLE task_exports ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'EXPORTED'"))
        connection.execute(text("UPDATE task_exports SET status = 'EXPORTED' WHERE status IS NULL"))
        connection.execute(text("ALTER TABLE task_exports ALTER COLUMN status SET NOT NULL"))
        connection.execute(text(
            "DELETE FROM task_exports older USING task_exports newer "
            "WHERE older.task_id = newer.task_id AND older.format = newer.format "
            "AND (older.exported_at < newer.exported_at "
            "OR (older.exported_at = newer.exported_at AND older.id < newer.id))"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_exports_task_format "
            "ON task_exports (task_id, format)"
        ))
        for table in ("slide_annotations", "annotation_records"):
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS edit_answer BOOLEAN DEFAULT TRUE"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS main_annotator_user_id INTEGER"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS blind_annotator_user_id INTEGER"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS reviewer_user_id INTEGER"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS blind_question JSON"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS blind_answer TEXT"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS similarity_score DOUBLE PRECISION"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS reject_reason VARCHAR(64)"))
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS final_status VARCHAR(32) DEFAULT 'PENDING'"))


def get_db() -> Generator[Session, None, None]:
    database_session = SessionLocal()
    try:
        yield database_session
    finally:
        database_session.close()
