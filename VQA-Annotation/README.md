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

Each user connects their own Drive account from the annotation workspace. The backend requests
offline access and explicit consent, then encrypts and stores a refresh token associated with
that application user. Configure these backend-only Render variables:

```dotenv
GOOGLE_DRIVE_OAUTH_CLIENT_ID=your_google_web_client_id
GOOGLE_DRIVE_OAUTH_CLIENT_SECRET=your_google_web_client_secret
GOOGLE_DRIVE_OAUTH_REDIRECT_URI=https://vqa-annotation-api.onrender.com/api/auth/google/callback
```

Add the exact callback URI to the OAuth Web Application's Authorized redirect URIs. Do not put
the client secret or refresh tokens in Vercel or GitHub. The legacy service-account and shared
refresh-token modes remain available only for migration and local compatibility; user-facing
Drive operations use the authenticated user's stored connection.

Source PDFs/folders must be readable and destination Task folders writable by the Google account
that the current user connected.

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
