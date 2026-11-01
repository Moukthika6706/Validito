# Deploying Validito on Render (API + Postgres) and Vercel (frontend)

Both services have a free tier, so this costs nothing. Trade-offs of the free tier:

- The API runs the **lite image** (`backend/Dockerfile.lite`): no PyTorch/EasyOCR, so scanned
  images are rejected with a clear message. Text PDFs and DOCX work end to end.
- No Celery worker or Redis: tasks run inline inside the request (`CELERY_TASK_ALWAYS_EAGER=true`).
  Uploads take a few seconds to return instead of being queued.
- Render's disk is wiped on every restart, so uploads are kept in Postgres (`STORAGE_BACKEND=db`).
- A free Render service **sleeps after 15 minutes idle**; the first request afterwards takes
  ~50 seconds while it wakes. Open the API link once before a demo.
- Free Postgres expires after 90 days unless upgraded (Render emails you first).

## 1. Render: API + database (about 15 minutes, mostly build time)

1. Sign up at https://render.com with GitHub and allow access to the `Validito` repository.
2. Dashboard → **New** → **Blueprint** → select `Moukthika6706/Validito`. Render reads
   `render.yaml` and shows one web service (`validito-api`) and one database (`validito-db`).
3. Click **Apply**. The database is created first, then the Docker image builds (~8–10 minutes:
   spaCy model, scikit-learn, PyMuPDF).
4. Open the `validito-api` service → **Logs**. You are done when you see the seed lines
   (`isda_irs_clean.pdf -> auto_approved` …) followed by `Application startup complete`.
5. Copy the service URL from the top of the page, e.g. `https://validito-api.onrender.com`.
   Check `https://validito-api.onrender.com/health` returns `{"status":"ok","database":true,...}`
   and `/docs` shows the OpenAPI page.

## 2. Vercel: frontend (about 5 minutes)

1. Sign up at https://vercel.com with GitHub → **Add New** → **Project** → import `Validito`.
2. Settings on the import screen:
   - **Root Directory**: `frontend` (click *Edit* next to the root directory)
   - Framework preset: Vite (auto-detected from `frontend/vercel.json`)
   - **Environment Variables**: `VITE_API_URL` = your Render URL **without a trailing slash**,
     e.g. `https://validito-api.onrender.com`
3. **Deploy**. Copy the production URL, e.g. `https://validito.vercel.app`.

## 3. Connect them (CORS)

Back in Render → `validito-api` → **Environment**:

- `CORS_ORIGINS` = `https://validito.vercel.app` (your Vercel URL; add a second origin with a comma if Vercel gives you a preview domain you also use)
- `FRONTEND_BASE_URL` = the same URL

**Save changes** → Render redeploys (~1 minute, no rebuild). Open the Vercel URL and log in
with a demo account (`admin@validito.demo` / `Validito123!`; others in the README).

## 4. Updating

Push to `main`. Render rebuilds the API and Vercel rebuilds the frontend automatically.
Migrations run on API start (`alembic upgrade head` in the entrypoint).

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Login page shows "Failed to fetch" | `VITE_API_URL` missing or has a trailing slash → fix in Vercel → *Redeploy* (env vars are baked in at build time). Or CORS: browser console says "blocked by CORS policy" → set `CORS_ORIGINS` on Render. |
| First request takes a minute | Free service waking up. Normal. |
| Build fails with "Killed" / out of memory | Make sure the Blueprint used `Dockerfile.lite`, not `Dockerfile`. |
| `/health` says `"database": false` | DB still provisioning; wait a minute. Render logs show the error. |
| Scanned PNG upload fails | Expected on the lite image (no OCR). Use the PDF/DOCX samples. |

## Local test of the same configuration

```bash
cd backend
DATABASE_URL=sqlite:///./dev.db STORAGE_BACKEND=db CELERY_TASK_ALWAYS_EAGER=true uvicorn app.main:app --reload
```
