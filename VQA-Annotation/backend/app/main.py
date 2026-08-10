from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.database import Base, engine, migrate_main_annotator_fields, migrate_task_management, migrate_user_system_role
from app.config.settings import settings
from app.models import AnnotationRecord, DocumentSlide, SlideAnnotation, Task, TaskAssignment, TaskDocument, TaskExport, User
from app.routers import admin, auth, document, results, tasks, user

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.on_event("startup")
def create_database_tables() -> None:
    Base.metadata.create_all(bind=engine)
    migrate_user_system_role()
    migrate_task_management()
    migrate_main_annotator_fields()


app.include_router(auth.router)
app.include_router(auth.admin_auth_router)
app.include_router(user.router)
app.include_router(admin.router)
app.include_router(tasks.router)
app.include_router(results.router)
app.include_router(document.router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}
