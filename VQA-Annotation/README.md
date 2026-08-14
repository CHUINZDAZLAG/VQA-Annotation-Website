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

The existing Drive service supports three credential sources, in this order:

1. `GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE` for local development where service-account keys are permitted.
2. OAuth offline credentials (existing `GOOGLE_CLIENT_ID`, plus `GOOGLE_DRIVE_OAUTH_CLIENT_SECRET` and `GOOGLE_DRIVE_OAUTH_REFRESH_TOKEN`) for Render.
3. Google Application Default Credentials for runtimes that provide workload identity.

For Render, create or reuse a Google OAuth client in project `vqa-annotation`, authorize a dedicated backend Google account for the Drive scope with offline access, and store the resulting client ID, client secret, and refresh token only in Render Environment Variables. Set `GOOGLE_DRIVE_ACCOUNT_EMAIL` to that account's email for health diagnostics. Do not put these values in Vercel or GitHub.

Share source PDFs/folders with the configured backend account as Viewer and each destination Task folder as Editor. The Render production identity is the Google account represented by `GOOGLE_DRIVE_OAUTH_REFRESH_TOKEN`, not the service account. `iam.disableServiceAccountKeyCreation` remains enabled.

The source PDF and destination folder are independent. Local PDF uploads also require a writable destination because generated page PNG files are uploaded to Drive immediately.

Start the backend from `backend/`:

```powershell
..\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend from `frontend/`:

```powershell
npm run dev
```

## Production deployment

### Render backend

Create the service from `render.yaml`, or configure a Python Web Service with root directory `backend`, build command `pip install -r requirements.txt`, start command `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and health path `/health`. The Blueprint explicitly selects Render's free plan in Singapore; upgrade the instance in Render if 300 DPI processing exceeds the free instance's memory or request limits.

Set all `sync: false` values from `render.yaml` in Render. Use the Supabase PostgreSQL connection URI for `DATABASE_URL`. Set `FRONTEND_URL` to the exact Vercel production origin, without a trailing slash. Multiple explicit origins may be comma-separated. Render disk is used only for temporary PDF processing; generated PNGs and exports are uploaded directly to Drive.

### Vercel frontend

Import the repository with root directory `frontend`. Vercel uses `npm run build`, output directory `dist`, and `frontend/vercel.json` for React Router fallback. Configure `VITE_API_URL` as the Render service origin and `VITE_GOOGLE_CLIENT_ID` as the existing Google Sign-In client ID. Add the Vercel production origin to that OAuth client's authorized JavaScript origins.

After configuring a Task folder, an admin can call `GET /api/admin/tasks/{task_id}/google-drive/health`. It authenticates and verifies Editor access without uploading a file.
