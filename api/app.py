"""
pdfforge/api/app.py — FastAPI backend for pdfforge web app (v1.2.0 production-hardened).

Endpoints:
  GET  /api/health       — health check
  GET  /api/samples      — list available sample PDFs
  GET  /api/samples?download=<name> — download a specific sample PDF
  POST /api/analyze-pdf  — upload PDF, get detected field schema (JSON)
  POST /api/generate-pdf — upload PDF + optional fields, get fillable PDF download
"""

from __future__ import annotations

import os
import logging
import re
import sys
import tempfile
import shutil
import json
from pathlib import Path
from typing import Optional, List

import fitz  # PyMuPDF
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.background import BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn

# Rate limiting
try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    SLOWAPI_AVAILABLE = True
except ImportError:
    SLOWAPI_AVAILABLE = False

# ── Import detector & generator from parent directory ──────────────────
PARENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PARENT_DIR))

from detector import detect_fields, detect_fields_json
try:
    from cv_detector import detect_fields_hybrid
    CV_FALLBACK_AVAILABLE = True
except Exception:
    CV_FALLBACK_AVAILABLE = False
from generator import generate_fillable_pdf, verify_acroform_fields

# ── Environment ─────────────────────────────────────────────────────────
ENV = os.environ.get("ENV", "development").lower()
IS_PRODUCTION = ENV == "production"

# ── Logging ────────────────────────────────────────────────────────────
logger = logging.getLogger("pdfforge")
logging.basicConfig(
    level=logging.INFO if IS_PRODUCTION else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── Config ──────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".pdf"}
PDF_MAGIC = b"%PDF"  # All valid PDF files start with these bytes

# CORS: allow GitHub Pages + localhost dev
ALLOWED_ORIGINS = [
    "https://infinitemindos-doai.github.io",
    "https://infinitemindos-doai.github.io/pdfforge",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:3000",
]
# Remove localhost origins in production
if IS_PRODUCTION:
    ALLOWED_ORIGINS = [o for o in ALLOWED_ORIGINS if "localhost" not in o and "127.0.0.1" not in o]

# Sample PDFs live in a dedicated directory
SAMPLES_DIR = PARENT_DIR / "samples"

app = FastAPI(
    title="pdfforge API",
    description="Detect form fields in flat PDFs and generate fillable PDFs.",
    version="1.2.0",
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)


# ── Security Headers Middleware ────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
            response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ── Request Size Limit Middleware ──────────────────────────────────────
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl and int(cl) > MAX_UPLOAD_BYTES + 1024:
            return JSONResponse(
                status_code=413,
                content={"detail": f"Request body too large. Maximum {MAX_UPLOAD_BYTES // (1024*1024)} MB."},
            )
        return await call_next(request)

app.add_middleware(RequestSizeLimitMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Rate Limiter ───────────────────────────────────────────────────────
if SLOWAPI_AVAILABLE:
    limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please slow down."},
        )


# ── Helpers ─────────────────────────────────────────────────────────────

def _validate_pdf(filename: str, file_size: int, content: bytes | None = None) -> None:
    """Validate uploaded file is a PDF and within size limit.

    Checks:
    1. File extension is .pdf
    2. File size is within MAX_UPLOAD_BYTES
    3. File content starts with PDF magic bytes (%PDF) if content is provided
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{ext}'. Only PDF files are accepted.",
        )
    if file_size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )
    if content is not None and not content.startswith(PDF_MAGIC):
        raise HTTPException(
            status_code=400,
            detail="File does not appear to be a valid PDF (missing PDF header).",
        )


def _safe_filename(filename: str) -> str:
    """Sanitize a filename to prevent path traversal attacks.

    Strips directory components and replaces potentially dangerous
    characters. Ensures the result is a simple basename with a .pdf
    extension.
    """
    # Take only the basename — strips any directory traversal (../, /, \)
    basename = os.path.basename(filename or "input.pdf")
    # Replace any remaining non-alphanumeric characters (except . - _) with _
    basename = re.sub(r'[^\w.\-]', '_', basename)
    # Ensure it has a .pdf extension
    if not basename.lower().endswith('.pdf'):
        basename = (basename or "input") + '.pdf'
    if not basename or basename == '.pdf':
        basename = 'input.pdf'
    return basename


def _validate_fields(fields: list) -> None:
    """Validate that a list of field dicts has the required structure.

    Required keys: page, type, x, y, width, height
    Valid types: text, checkbox, table_cell
    """
    if not isinstance(fields, list):
        raise HTTPException(
            status_code=400,
            detail="fields_json must be a JSON array of field objects.",
        )
    required_keys = {"page", "type", "x", "y", "width", "height"}
    valid_types = {"text", "checkbox", "radio", "table_cell", "textarea"}
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Field at index {i} is not a JSON object.",
            )
        missing = required_keys - set(f.keys())
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Field at index {i} is missing required keys: {sorted(missing)}",
            )
        if f["type"] not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Field at index {i} has invalid type '{f['type']}'. "
                    f"Valid types: {sorted(valid_types)}"
                ),
            )
        if not isinstance(f["page"], int) or f["page"] < 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Field at index {i} has invalid page number '{f['page']}'. "
                    f"Must be a non-negative integer."
                ),
            )


# ── Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "pdfforge-api", "version": "1.2.0"}


@app.get("/api/samples")
async def list_samples(
    download: Optional[str] = Query(
        None, description="Sample PDF filename to download"
    ),
):
    """List available sample PDFs, or download a specific one.

    Without the ``download`` query parameter, returns a JSON list of
    available sample PDFs.  When ``?download=<filename>`` is provided,
    returns the actual PDF file as a download.
    """
    # ── Download mode: return the requested PDF file ──
    if download is not None:
        safe_name = _safe_filename(download)
        sample_path = SAMPLES_DIR / safe_name

        # Guard against path traversal: ensure resolved path stays
        # within SAMPLES_DIR
        try:
            sample_path.resolve().relative_to(SAMPLES_DIR.resolve())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid sample filename.",
            )

        if not sample_path.exists() or not sample_path.is_file():
            raise HTTPException(
                status_code=404,
                detail=f"Sample PDF '{safe_name}' not found.",
            )

        return FileResponse(
            path=str(sample_path),
            media_type="application/pdf",
            filename=safe_name,
        )

    # ── List mode: return JSON metadata for all sample PDFs ──
    samples = []
    if SAMPLES_DIR.exists():
        for f in sorted(SAMPLES_DIR.iterdir()):
            if f.suffix.lower() == ".pdf" and f.is_file():
                samples.append({
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                    "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                })
    return {"samples": samples}


@app.post("/api/analyze-pdf")
async def analyze_pdf(file: UploadFile = File(...)):
    """
    Upload a flat PDF and get the detected form field schema as JSON.

    Returns:
        { "fields": [...], "page_count": N, "page_sizes": [...], "field_count": M }
    """
    # Read file content to check size and validate
    content = await file.read()
    _validate_pdf(file.filename or "", len(content), content=content)

    tmp_dir = tempfile.mkdtemp(prefix="pdfforge_")
    try:
        safe_name = _safe_filename(file.filename or "input.pdf")
        pdf_path = os.path.join(tmp_dir, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(content)

        # Run detection (hybrid: vector first, CV fallback for scanned PDFs)
        try:
            if CV_FALLBACK_AVAILABLE:
                fields = detect_fields_hybrid(pdf_path, verbose=False)
            else:
                fields = detect_fields(pdf_path, verbose=False)
        except Exception as e:
            logger.exception("Field detection failed for uploaded PDF")
            raise HTTPException(
                status_code=422,
                detail="Field detection failed. The PDF may be corrupted or use unsupported features.",
            )

        # Get page count and sizes — wrap in try/finally to ensure
        # the PyMuPDF document is always closed, even on error
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            logger.exception("Failed to open uploaded PDF with PyMuPDF")
            raise HTTPException(
                status_code=422,
                detail="Failed to open PDF. The file may be corrupted.",
            )
        try:
            page_count = len(doc)
            page_sizes = []
            for pno in range(page_count):
                page = doc[pno]
                page_sizes.append({
                    "width": page.rect.width,
                    "height": page.rect.height,
                })
        finally:
            doc.close()

        # Build field type summary
        type_summary = {}
        for f in fields:
            type_summary[f.get("type", "unknown")] = type_summary.get(f.get("type", "unknown"), 0) + 1

        return JSONResponse({
            "fields": fields,
            "page_count": page_count,
            "page_sizes": page_sizes,
            "field_count": len(fields),
            "type_summary": type_summary,
        })

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/generate-pdf")
async def generate_pdf(
    file: UploadFile = File(...),
    fields_json: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Upload a flat PDF and get a fillable PDF back.

    If fields_json is provided, use that field schema. Otherwise,
    run detection automatically and generate from detected fields.

    Returns the fillable PDF as a file download.
    """
    content = await file.read()
    _validate_pdf(file.filename or "", len(content), content=content)

    tmp_dir = tempfile.mkdtemp(prefix="pdfforge_gen_")
    response_prepared = False  # track whether FileResponse is about to be returned
    try:
        safe_name = _safe_filename(file.filename or "input.pdf")
        pdf_path = os.path.join(tmp_dir, safe_name)
        with open(pdf_path, "wb") as f:
            f.write(content)

        # Parse provided fields or auto-detect
        if fields_json:
            try:
                fields = json.loads(fields_json)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid fields_json: not valid JSON.",
                )
            # Validate field structure to prevent unhandled errors
            # downstream in generate_fillable_pdf
            _validate_fields(fields)
        else:
            try:
                if CV_FALLBACK_AVAILABLE:
                    fields = detect_fields_hybrid(pdf_path, verbose=False)
                else:
                    fields = detect_fields(pdf_path, verbose=False)
            except Exception as e:
                logger.exception("Field detection failed for uploaded PDF in generate-pdf")
                raise HTTPException(
                    status_code=422,
                    detail="Field detection failed. The PDF may be corrupted or use unsupported features.",
                )

        if not fields:
            raise HTTPException(
                status_code=422,
                detail="No form fields detected in this PDF.",
            )

        # Generate fillable PDF
        base_name = Path(safe_name).stem
        output_name = f"{base_name}_fillable.pdf"
        output_path = os.path.join(tmp_dir, output_name)

        try:
            generate_fillable_pdf(
                pdf_path, fields, output_path=output_path, verbose=False
            )
        except Exception as e:
            logger.exception("PDF generation failed")
            raise HTTPException(
                status_code=500,
                detail="PDF generation failed. Please try again or contact support.",
            )

        # Verify AcroForm fields were embedded
        try:
            verification = verify_acroform_fields(output_path)
        except Exception as e:
            logger.exception("AcroForm verification failed")
            raise HTTPException(
                status_code=500,
                detail="PDF verification failed. Please try again.",
            )

        # Compute page count from field data (max page index + 1)
        page_count = max(f["page"] for f in fields) + 1 if fields else 0

        # Schedule cleanup of the temp directory AFTER the response
        # has been fully streamed to the client.  BackgroundTasks
        # run after the response is sent, so the output file will
        # still exist when FileResponse reads it.
        background_tasks.add_task(shutil.rmtree, tmp_dir, ignore_errors=True)
        response_prepared = True

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=output_name,
            headers={
                "X-Field-Count": str(verification["total_fields"]),
                "X-Page-Count": str(page_count),
            },
        )

    except HTTPException:
        # On any error before the response is prepared, clean up
        # the temp directory immediately.  If the response was
        # already prepared, the BackgroundTask handles cleanup.
        if not response_prepared:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as e:
        # Catch-all for any unexpected error not already handled
        if not response_prepared:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.exception("Unexpected error during PDF generation")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again.",
        )


@app.get("/")
async def root():
    """Root endpoint — redirect info."""
    if IS_PRODUCTION:
        return {"name": "pdfforge API", "version": "1.2.0"}
    return {
        "name": "pdfforge API",
        "docs": "/docs",
        "endpoints": [
            "/api/health",
            "/api/samples",
            "/api/analyze-pdf",
            "/api/generate-pdf",
        ],
    }


if __name__ == "__main__":
    if IS_PRODUCTION:
        uvicorn.run(
            "api.app:app",
            host="127.0.0.1",
            port=8000,
            reload=False,
            workers=2,
            log_level="info",
        )
    else:
        uvicorn.run(
            "api.app:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
        )
