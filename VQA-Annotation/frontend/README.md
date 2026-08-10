# Frontend

React + Vite frontend for the VQA Dataset Annotation Platform.

Set `VITE_GOOGLE_CLIENT_ID` and `VITE_API_URL` in `.env`. Google Sign-In supplies an
ID token only to `POST /api/auth/google`; all protected API calls use the returned
application access token.

## Start

```bash
npm install
npm run dev
```
