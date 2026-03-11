"""
Sales Insight Automator - FastAPI Backend
Rabbitt AI | Production Prototype
"""

import io
import os
import logging
import smtplib
import time
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from contextlib import asynccontextmanager

import pandas as pd
from groq import Groq
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
import uvicorn

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("sales-insight")

# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GEMINI_API_KEY", "")   # reusing same env var
SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASS: str = os.getenv("SMTP_PASS", "")
SENDER_NAME: str = os.getenv("SENDER_NAME", "Rabbitt AI Sales Insights")
API_KEY: str = os.getenv("APP_API_KEY", "rabbitt-dev-key-change-in-prod")
ALLOWED_ORIGINS: list = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:80,http://localhost"
).split(",")
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "10"))

# ─────────────────────────────────────────────────────────────
# Rate Limiter
# ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ─────────────────────────────────────────────────────────────
# App Lifespan
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    if GROQ_API_KEY:
        logger.info("Groq AI configured successfully.")
    else:
        logger.warning("GROQ API KEY not set - AI features will be mocked.")
    yield
    logger.info("Application shutting down.")

# ─────────────────────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="Sales Insight Automator",
    description=(
        "Upload a CSV/XLSX sales file and receive an AI-generated executive "
        "summary via email. Built for Rabbitt AI by the CloudDevOps team."
    ),
    version="1.0.0",
    contact={"name": "Rabbitt AI Engineering", "email": "engineering@rabbitt.ai"},
    license_info={"name": "Proprietary"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ─────────────────────────────────────────────────────────────
# CORS Middleware
# ─────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Request Size Guard
# ─────────────────────────────────────────────────────────────
@app.middleware("http")
async def limit_upload_size(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_FILE_SIZE_MB * 1024 * 1024:
            return JSONResponse(
                status_code=413,
                content={"detail": f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB."},
            )
    return await call_next(request)

# ─────────────────────────────────────────────────────────────
# API Key Auth
# ─────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(key: Optional[str] = Security(api_key_header)):
    if key is None or key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Include X-API-Key header.",
        )
    return key

# ─────────────────────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: float

class AnalyzeResponse(BaseModel):
    success: bool
    message: str
    summary_preview: str
    rows_processed: int
    recipient: str

# ─────────────────────────────────────────────────────────────
# File Parser
# ─────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

def parse_uploaded_file(filename: str, contents: bytes) -> pd.DataFrame:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{ext}'. Use .csv or .xlsx.")
    try:
        buf = io.BytesIO(contents)
        df = pd.read_csv(buf) if ext == ".csv" else pd.read_excel(buf, engine="openpyxl")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")
    if df.empty:
        raise HTTPException(status_code=422, detail="Uploaded file contains no data.")
    if len(df) > 50000:
        raise HTTPException(status_code=422, detail="File exceeds 50,000-row limit.")
    return df

# ─────────────────────────────────────────────────────────────
# Data Profiler
# ─────────────────────────────────────────────────────────────
def build_data_profile(df: pd.DataFrame) -> str:
    lines = [
        f"Rows: {len(df)}, Columns: {list(df.columns)}",
        "",
        "=== Sample (first 5 rows) ===",
        df.head(5).to_string(index=False),
        "",
    ]
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        lines.append("=== Numeric Summary ===")
        lines.append(df[numeric_cols].describe().to_string())
        lines.append("")
    for col in df.select_dtypes(include="object").columns.tolist()[:3]:
        lines.append(f"=== Top values in '{col}' ===")
        lines.append(df[col].value_counts().head(5).to_string())
        lines.append("")
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────
# AI Summary via Groq
# ─────────────────────────────────────────────────────────────
SUMMARY_PROMPT_TEMPLATE = """You are a senior business analyst preparing an executive brief for C-suite leadership.

Analyse the following quarterly sales data and produce a professional, narrative-driven summary.

Your response MUST include:
1. Executive Overview - 2-3 sentence snapshot of overall performance.
2. Key Metrics - Revenue totals, unit volumes, top-performing categories/regions.
3. Trends and Insights - Notable patterns, growth areas, or concerns.
4. Risks and Anomalies - Any cancelled orders, under-performing segments, or data gaps.
5. Strategic Recommendations - 2-3 actionable next steps for the sales team.

Tone: Professional, concise, data-driven.

--- DATA PROFILE ---
{data_profile}
--- END DATA PROFILE ---

Format the response in clean HTML suitable for an email body (use <h2>, <p>, <ul>, <li> tags).
Do NOT include <html>, <head>, or <body> tags.
"""

def generate_ai_summary(data_profile: str) -> str:
    if not GROQ_API_KEY:
        logger.warning("Using mock summary - no API key set.")
        return _mock_summary(data_profile)
    try:
        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": SUMMARY_PROMPT_TEMPLATE.format(data_profile=data_profile)}],
            max_tokens=1500,
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.error("Groq API error: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI service error: {exc}")

def _mock_summary(data_profile: str) -> str:
    return """<h2>Executive Overview</h2>
<p>This is a <strong>mock summary</strong>. Configure your API key to enable live AI summaries.</p>
<h2>Data Profile Snapshot</h2>
<pre style="font-size:12px;background:#f4f4f4;padding:8px;">{}</pre>""".format(data_profile[:500])

# ─────────────────────────────────────────────────────────────
# Email Sender
# ─────────────────────────────────────────────────────────────
EMAIL_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background:#f8f9fa; margin:0; padding:0; }}
  .wrapper {{ max-width:680px; margin:32px auto; background:#ffffff; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,.08); overflow:hidden; }}
  .header {{ background:#0f172a; padding:28px 36px; }}
  .header h1 {{ color:#f97316; margin:0; font-size:22px; }}
  .header p {{ color:#94a3b8; margin:4px 0 0; font-size:13px; }}
  .body {{ padding:28px 36px; color:#1e293b; line-height:1.7; }}
  .body h2 {{ color:#0f172a; border-bottom:2px solid #f97316; padding-bottom:4px; }}
  .body ul {{ padding-left:20px; }}
  .footer {{ background:#f1f5f9; padding:16px 36px; font-size:12px; color:#64748b; text-align:center; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Rabbitt AI - Sales Insight Report</h1>
    <p>AI-generated executive brief - Quarterly Sales Data</p>
  </div>
  <div class="body">{summary_html}</div>
  <div class="footer">Generated automatically by the Sales Insight Automator. Rabbitt AI - Confidential</div>
</div>
</body>
</html>
"""

def send_email(recipient: str, subject: str, summary_html: str) -> None:
    if not SMTP_USER or not SMTP_PASS:
        logger.warning("SMTP credentials not configured - skipping email delivery.")
        return
    html_body = EMAIL_TEMPLATE.format(summary_html=summary_html)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, [recipient], msg.as_string())
        logger.info("Email sent to %s", recipient)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP auth failure: %s", exc)
        raise HTTPException(status_code=502, detail="Email service authentication failed.")
    except Exception as exc:
        logger.error("Email delivery error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Email delivery failed: {exc}")

# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, summary="Health Check", tags=["System"])
async def health_check():
    return HealthResponse(status="ok", version="1.0.0", timestamp=time.time())


@app.post(
    "/api/v1/analyze",
    response_model=AnalyzeResponse,
    summary="Analyze Sales Data and Dispatch Email",
    tags=["Sales Insights"],
    dependencies=[Depends(verify_api_key)],
)
@limiter.limit("10/minute")
async def analyze_and_email(
    request: Request,
    file: UploadFile = File(..., description="Sales data file (.csv or .xlsx, max 10 MB)"),
    recipient_email: str = Form(..., description="Recipient email address"),
    report_title: Optional[str] = Form(default="Q1 2026 Sales Intelligence Brief"),
    _key: str = Depends(verify_api_key),
):
    """
    Main endpoint. Upload a CSV/XLSX file, get an AI summary emailed to the recipient.

    **Authentication:** Requires X-API-Key header.

    **Rate limit:** 10 requests/minute per IP.
    """
    logger.info("Analyze request | file=%s | recipient=%s", file.filename, recipient_email)

    if "@" not in recipient_email or "." not in recipient_email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Invalid email address.")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    df = parse_uploaded_file(file.filename or "upload", contents)
    data_profile = build_data_profile(df)
    logger.info("Data profile built | rows=%d", len(df))

    summary_html = generate_ai_summary(data_profile)
    logger.info("AI summary generated | length=%d chars", len(summary_html))

    send_email(recipient_email, report_title, summary_html)

    preview_text = re.sub(r"<[^>]+>", "", summary_html)[:300].strip()

    return AnalyzeResponse(
        success=True,
        message="Analysis complete. Summary dispatched to inbox.",
        summary_preview=preview_text,
        rows_processed=len(df),
        recipient=recipient_email,
    )


@app.get("/", include_in_schema=False)
async def root():
    return {"service": "Sales Insight Automator", "company": "Rabbitt AI", "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)