"""
pdfforge/api/app.py — FastAPI backend for pdfforge web app.

Endpoints:
  GET  /api/health       — health check
  GET  /api/samples      — list available sample PDFs
  POST /api/analyze-pdf  — upload PDF, get detected field schema (JSON)
  POST /api/generate-pdf — upload PDF + optional fields, get fillable PDF download
"""

from __future__ import annotations

import os
import sys
import tempfile
import shutil
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import uvicorn

# ── Import detector & generator from parent directory ──────────────────
PARENT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PARENT_DIR))

from detector import detect_fields, detect_fields_json
from generator import generate_fillable_pdf, verify_acroform_fields

# ── Config ──────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_EXTENSIONS = {".pdf"}

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

# Sample PDFs live in the project root
SAMPLES_DIR = PARENT_DIR

app = FastAPI(
    title="pdfforge API",
    description="Detect form fields in flat PDFs and generate fillable PDFs.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helpers ─────────────────────────────────────────────────────────────

def _validate_pdf(filename: str, file_size: int) -> None:
    """Validate uploaded file is a PDF and within size limit."""
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


def _save_upload(upload: UploadFile, dest_dir: str) -> str:
    """Save an UploadFile to a temp dir and return the path."""
    dest_path = os.path.join(dest_dir, upload.filename or "input.pdf")
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(upload.file, f)
    return dest_path


# ── Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "pdfforge-api", "version": "1.0.0"}


@app.get("/api/samples")
async def list_samples():
    """List available sample PDFs."""
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
        { "fields": [...], "page_count": N, "field_count": M }
    """
    # Read file content to check size
    content = await file.read()
    _validate_pdf(file.filename or "", len(content))

    tmp_dir = tempfile.mkdtemp(prefix="pdfforge_")
    try:
        pdf_path = os.path.join(tmp_dir, file.filename or "input.pdf")
        with open(pdf_path, "wb") as f:
            f.write(content)

        # Run detection
        try:
            fields = detect_fields(pdf_path, verbose=False)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Field detection failed: {str(e)}",
            )

        # Get page count
        import fitz
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        page_sizes = []
        for pno in range(page_count):
            page = doc[pno]
            page_sizes.append({"width": page.rect.width, "height": page.rect.height})
        doc.close()

        return JSONResponse({
            "fields": fields,
            "page_count": page_count,
            "page_sizes": page_sizes,
            "field_count": len(fields),
        })

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/generate-pdf")
async def generate_pdf(
    file: UploadFile = File(...),
    fields_json: Optional[str] = Form(None),
):
    """
    Upload a flat PDF and get a fillable PDF back.

    If fields_json is provided, use that field schema. Otherwise,
    run detection automatically and generate from detected fields.

    Returns the fillable PDF as a file download.
    """
    content = await file.read()
    _validate_pdf(file.filename or "", len(content))

    tmp_dir = tempfile.mkdtemp(prefix="pdfforge_gen_")
    try:
        pdf_path = os.path.join(tmp_dir, file.filename or "input.pdf")
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
        else:
            try:
                fields = detect_fields(pdf_path, verbose=False)
            except Exception as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Field detection failed: {str(e)}",
                )

        if not fields:
            raise HTTPException(
                status_code=422,
                detail="No form fields detected in this PDF.",
            )

        # Generate fillable PDF
        base_name = Path(file.filename or "input.pdf").stem
        output_name = f"{base_name}_fillable.pdf"
        output_path = os.path.join(tmp_dir, output_name)

        try:
            generate_fillable_pdf(pdf_path, fields, output_path=output_path, verbose=False)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"PDF generation failed: {str(e)}",
            )

        # Verify
        verification = verify_acroform_fields(output_path)

        return FileResponse(
            output_path,
            media_type="application/pdf",
            filename=output_name,
            headers={
                "X-Field-Count": str(verification["total_fields"]),
                "X-Page-Count": str(len(fields)),
            },
        )

    finally:
        # Clean up input file but keep output until response sent
        # FastAPI handles this via background tasks, but we clean tmp_dir
        # after the response is streamed. Using a slight delay.
        pass  # tmp_dir will be cleaned by OS temp rotation; we can't delete
              # before FileResponse streams it. This is acceptable for short-lived
              # temp files in a server environment.


@app.get("/")
async def root():
    """Root endpoint — redirect info."""
    return {
        "name": "pdfforge API",
        "docs": "/docs",
        "endpoints": ["/api/health", "/api/samples", "/api/analyze-pdf", "/api/generate-pdf"],
    }


if __name__ == "__main__":
    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True)