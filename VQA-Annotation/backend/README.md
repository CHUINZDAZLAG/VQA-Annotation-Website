# Backend

FastAPI backend for the VQA Dataset Annotation Platform.

## Authentication

`POST /api/auth/google` accepts a Google ID token, verifies its signature, audience,
issuer, and expiration, then returns application-issued access and refresh tokens.
Set `GOOGLE_CLIENT_ID`, `SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES`, and
`REFRESH_TOKEN_EXPIRE_DAYS` in `.env`. No Google client secret or callback URI is used.

## Gemini annotation generation

Copy `.env.example` to `.env` and set the backend-only Gemini variables:

```dotenv
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-1.5-flash
```

The key is read by FastAPI from `backend/.env` and is never sent to the React app.
After changing `.env`, restart Uvicorn. Main Annotators can then use **Generate with
Gemini** or **Regenerate with Gemini** for an individual slide. If the key is empty,
the endpoint returns a configuration error instead of silently generating an answer.

## Final dataset export

Admin JSON and CSV exports contain only pages where Main Annotator, Blind Annotator,
and Reviewer all have decision `1`. Pending, rejected, or incomplete pages remain
available in the Admin results and statistics views but are excluded from the final dataset.

## Start

```bash
uvicorn app.main:app --reload
```
