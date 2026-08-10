from pathlib import Path

from app.config.settings import settings


class LocalStorage:
    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.storage_root).resolve()

    def task_root(self, task_id: int) -> Path:
        return self.root / "tasks" / str(task_id)

    def save_document(self, task_id: int, filename: str, content: bytes) -> Path:
        destination = self.task_root(task_id) / "documents" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    def slide_path(self, task_id: int, slide_name: str, page_number: int) -> Path:
        return self.task_root(task_id) / "slides" / f"{slide_name}_page_{page_number:02d}.png"

    def remove_task_files(self, task_id: int) -> None:
        task_root = self.task_root(task_id)
        if task_root.exists():
            for path in sorted(task_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            task_root.rmdir()

    def remove_stale_slide_files(self, task_id: int, valid_paths: set[Path]) -> None:
        slides_root = self.task_root(task_id) / "slides"
        if not slides_root.exists():
            return
        resolved_valid = {path.resolve() for path in valid_paths}
        for path in slides_root.glob("*.png"):
            if path.resolve() not in resolved_valid:
                path.unlink()


storage = LocalStorage()
