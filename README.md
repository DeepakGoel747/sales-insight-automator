# 🐇 Sales Insight Automator
### Rabbitt AI · CloudDevOps Sprint · Engineer's Log

> Upload a quarterly sales CSV/Excel → AI generates an executive brief → Delivered to inbox.

---

## Live Deployment

| Service       | URL                                                      |
|---------------|----------------------------------------------------------|
| **Frontend**  | `https://sales-insight-automator.vercel.app`             |
| **Backend API** | `https://sales-insight-api.onrender.com`               |
| **Swagger UI**| `https://sales-insight-api.onrender.com/docs`           |
| **ReDoc**     | `https://sales-insight-api.onrender.com/redoc`          |

> _Update these URLs after deploying. Render free tier may have a 30-second cold start._

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│  User Browser                                             │
│  ┌──────────────────────────────────────────────────┐    │
│  │  SPA (index.html — nginx)                         │    │
│  │  • Drag-and-drop file upload                      │    │
│  │  • Email input + API key                         │    │
│  │  • Real-time loading / success / error states    │    │
│  └───────────────┬──────────────────────────────────┘    │
└──────────────────│───────────────────────────────────────┘
                   │  POST /api/v1/analyze
                   │  X-API-Key header
                   ▼
┌──────────────────────────────────────────────────────────┐
│  FastAPI Backend (uvicorn, 2 workers)                     │
│                                                           │
│  ① Rate Limiter (slowapi)  — 10 req/min per IP           │
│  ② API Key Middleware       — X-API-Key validation        │
│  ③ File Validator           — ext, MIME, size, row count  │
│  ④ pandas                   — CSV/XLSX → DataFrame        │
│  ⑤ Data Profiler            — statistical snapshot        │
│  ⑥ Google Gemini 1.5-Flash  — narrative AI summary        │
│  ⑦ smtplib                  — HTML email dispatch         │
│                                                           │
│  GET /health   — Docker healthcheck                       │
│  GET /docs     — Swagger UI                               │
└──────────────────────────────────────────────────────────┘
                   │
                   ▼
            Gmail / SendGrid SMTP
```

---

## Quick Start — docker-compose

### Prerequisites
- Docker ≥ 24 and Docker Compose V2
- A Google Gemini API key (free at [aistudio.google.com](https://aistudio.google.com/app/apikey))
- Gmail account with an **App Password** enabled (for email delivery)

### 1. Clone & configure

```bash
git clone https://github.com/rabbitt-ai/sales-insight-automator.git
cd sales-insight-automator

# Create your local config
cp .env.example .env
# Edit .env and fill in your API keys
```

### 2. Spin up the stack

```bash
docker compose up --build
```

This starts:
- **Frontend** → [http://localhost](http://localhost)
- **Backend API** → [http://localhost:8000](http://localhost:8000)
- **Swagger UI** → [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Test the flow

Use the included sample file:

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "X-API-Key: rabbitt-dev-key-change-in-prod" \
  -F "file=@sales_q1_2026.csv" \
  -F "recipient_email=your@email.com" \
  -F "report_title=Q1 2026 Sales Brief"
```

### 4. Tear down

```bash
docker compose down -v
```

---

## Security Architecture

| Layer | Mechanism | Details |
|-------|-----------|---------|
| **Authentication** | API Key (`X-API-Key` header) | All `/api/v1/*` routes require a matching secret key. Returns `401` on mismatch. Rotatable via env var. |
| **Rate Limiting** | `slowapi` (token bucket) | 10 requests/minute per IP address. Returns `429 Too Many Requests` with a `Retry-After` header. |
| **Upload Validation** | Extension + row-count guard | Only `.csv`, `.xlsx`, `.xls` are accepted. Files above 10 MB (configurable) or 50,000 rows are rejected with `422`. |
| **CORS** | Strict origin allowlist | Only origins listed in `ALLOWED_ORIGINS` env var are permitted. No wildcard `*` in production. |
| **Request Size Guard** | ASGI middleware | Raw `content-length` header checked before the body is read — prevents memory exhaustion from oversized payloads. |
| **Container Isolation** | Non-root user + resource limits | Backend container runs as `appuser` (non-root). Compose resource limits: 1 CPU / 512 MB RAM. |
| **Secrets Management** | Environment variables only | No secrets in source code. `.env` is gitignored. `.env.example` documents keys without values. |

---

## Project Structure

```
sales-insight-automator/
├── backend/
│   ├── main.py              # FastAPI app — all routes, middleware, helpers
│   ├── requirements.txt     # Pinned Python dependencies
│   └── Dockerfile           # Multi-stage build (builder → runtime)
│
├── frontend/
│   ├── index.html           # Single-page app (vanilla JS + CSS)
│   └── Dockerfile           # nginx static server with security headers
│
├── .github/
│   └── workflows/
│       └── ci.yml           # CI/CD pipeline (lint → scan → build → smoke → publish)
│
├── docker-compose.yml       # Local full-stack orchestration
├── .env.example             # Environment variable template
├── .gitignore
├── sales_q1_2026.csv        # Reference test data
└── README.md                # This file
```

---

## CI/CD Pipeline

Triggered on every **Pull Request → main** and **push → main**.

```
PR / Push
    │
    ├─► Job 1: Lint Backend       (Ruff lint + format check)
    │
    ├─► Job 2: Security Scan      (Bandit — Python security linter)
    │
    ├─► Job 3: Docker Build       (backend + frontend images, cache via GHA)
    │       └── needs: Job 1
    │
    ├─► Job 4: Smoke Test         (docker-compose up → /health → /openapi.json → frontend)
    │       └── needs: Job 3
    │
    └─► Job 5: Publish to GHCR    (only on merge to main)
            └── needs: Job 4
```

Images are pushed to GitHub Container Registry (`ghcr.io`) with `sha` and `latest` tags.

---

## API Reference

Full interactive docs at `/docs` (Swagger UI) and `/redoc`.

### `GET /health`
Public. Returns service status and timestamp.

### `POST /api/v1/analyze` _(protected)_

**Headers:** `X-API-Key: <your-key>`

**Form fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | ✅ | `.csv` or `.xlsx`, max 10 MB |
| `recipient_email` | string | ✅ | Destination email address |
| `report_title` | string | ❌ | Email subject (default: "Q1 2026 Sales Intelligence Brief") |

**Response (200):**
```json
{
  "success": true,
  "message": "Analysis complete. Summary dispatched to inbox.",
  "summary_preview": "Electronics led Q1 with $449,750 in revenue...",
  "rows_processed": 6,
  "recipient": "exec@company.com"
}
```

---

## Deployment Guide

### Backend → Render

1. Connect your GitHub repo in Render dashboard.
2. Create a new **Web Service** pointing to `./backend`.
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add all environment variables from `.env.example` in the Render **Environment** panel.

### Frontend → Vercel

1. Connect your GitHub repo.
2. Set **Root Directory** to `frontend`.
3. Set **Output Directory** to `.` (it's a static HTML file).
4. Add environment variable: `API_BASE=https://your-render-url.onrender.com`
5. Deploy.

> **Tip:** Update the `API_BASE` in `frontend/index.html` or inject it via Vercel env if using a build step.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS · nginx · Syne + DM Sans fonts |
| Backend | Python 3.12 · FastAPI · uvicorn · pandas · openpyxl |
| AI Engine | Google Gemini 1.5-Flash |
| Email | smtplib (STARTTLS) · Gmail App Passwords |
| Auth / Rate Limiting | API Key headers · slowapi |
| Containerisation | Docker (multi-stage) · Docker Compose V2 |
| CI/CD | GitHub Actions · docker/build-push-action · GHCR |
| Deployment | Vercel (frontend) · Render (backend) |

---

_Built in a 3-hour sprint by the Rabbitt AI CloudDevOps team._  
_© 2026 Rabbitt AI. All rights reserved._
