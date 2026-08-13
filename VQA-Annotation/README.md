# VQA Annotation Website

VQA dataset annotation platform with role-based authentication and document annotation workflows.

## Features

- Google authentication for annotators.
- Admin dashboard for users, tasks, assignments, progress, results, agreement statistics, and exports.
- Annotator portal template for Main Annotator, Blind Annotator, and Reviewer roles.
- Google Drive PDF selection, page rendering, generated image metadata, and backend-only Drive integration.
- Optional backend-only Gemini question and answer generation with custom prompts.
- Blind comparison, reviewer decisions, rejection reasons, and final dataset filtering.
- Final JSON and CSV exports include only pages accepted by Main, Blind, and Reviewer (`1/1/1`).

## Structure

- `backend/` FastAPI application
- `frontend/` React + Vite application
- `docs/` project documentation

## Development

Backend configuration belongs in `backend/.env`. Copy `backend/.env.example` and set the required database, authentication, Google, Drive, and optional Gemini values. Never commit `.env` files or service credentials.

### Google Drive setup

1. Enable Google Drive API for the service account's Google Cloud project.
2. Store the service-account JSON outside source control.
3. Set `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` in `backend/.env` to that JSON file's absolute path.
4. Share source PDFs/folders with the service-account email as Viewer.
5. Share destination folders with the service-account email as Editor.
6. Restart the backend after changing `backend/.env`.

The source PDF and destination folder are independent. Local PDF uploads also require a writable destination because generated page PNG files are uploaded to Drive immediately.

Start the backend from `backend/`:

```powershell
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend from `frontend/`:

```powershell
npm run dev
```
