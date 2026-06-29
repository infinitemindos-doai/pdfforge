"""
pdfforge/detector.py — Phase 1: Field Detection Engine

Takes a flat PDF (no existing form fields) and detects where fillable
areas should go: horizontal lines (text fields), checkbox squares,
and table cells.  Uses pdfplumber for vector/table extraction, OpenCV
for rasterised line/shape detection, and PyMuPDF for text-position
labelling.

Output: list of field dicts (JSON-serialisable) with keys:
    page, type, x, y, width, height, label, name
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, asdict
from typing import List, Optional

import cv2
import fitz  # PyMuDB
import numpy as np
import pdfplumber
from PIL import Image


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """A single detected form field."""
    page: int          # 0-indexed
    type: str          # "text" | "checkbox" | "table_cell"
    x: float           # PDF coordinate (top-left x, points)
    y: float           # PDF coordinate (top-left y, points)
    width: float
    height: float
    label: str = ""
    name: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_label(label: str) -> str:
    """Turn a human-readable label into a valid AcroForm field name."""
    if not label:
        return ""
    # Remove non-alphanumeric, replace spaces with underscores
    cleaned = re.sub(r'[^A-Za-z0-9 ]+', '', label).strip()
    cleaned = cleaned.replace(' ', '_')
    # Avoid leading digit
    if cleaned and cleaned[0].isdigit():
        cleaned = 'f_' + cleaned
    return cleaned or 'field'


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Text extraction (PyMuPDF) for labelling
# ---------------------------------------------------------------------------

def _extract_text_blocks(pdf_path: str) -> dict:
    """Return {page_index: [ {x0, y0, x1, y1, text}, ... ]} for every page."""
    doc = fitz.open(pdf_path)
    pages = {}
    for pno in range(len(doc)):
        page = doc[pno]
        blocks = []
        for block in page.get_text("blocks"):
            # block = (x0, y0, x1, y1, text, block_no, block_type)
            x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
            text = text.strip()
            if text:
                blocks.append({
                    "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "text": text,
                    "cx": (x0 + x1) / 2,
                    "cy": (y0 + y1) / 2,
                })
        pages[pno] = blocks
    doc.close()
    return pages


def _find_nearest_label(
    field_x: float,
    field_y: float,
    text_blocks: list,
    max_distance: float = 120,
) -> str:
    """
    Find the nearest text block that sits above or to the left of the field,
    which is the conventional label position for form fields.
    """
    best_label = ""
    best_dist = float("inf")

    for blk in text_blocks:
        bx, by = blk["cx"], blk["cy"]
        # Label should be above (smaller y) or to the left (smaller x)
        is_above = by <= field_y + 5
        is_left = bx <= field_x + 5 and abs(by - field_y) < 20
        if not (is_above or is_left):
            continue
        d = _distance(field_x, field_y, bx, by)
        if d < best_dist and d <= max_distance:
            best_dist = d
            best_label = blk["text"]

    # Clean up multi-line labels — take first meaningful line
    if best_label:
        lines = [l.strip() for l in best_label.split('\n') if l.strip()]
        best_label = lines[-1] if lines else ""  # last line closest to field
    return best_label


# ---------------------------------------------------------------------------
# Rasterise page → OpenCV image
# ---------------------------------------------------------------------------

def _rasterise_page(pdf_path: str, page_index: int, dpi: int = 200) -> np.ndarray:
    """Render a PDF page as an OpenCV BGR image at the given DPI."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    # Scale factor: 72 DPI is PDF default
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    doc.close()

    img_bytes = pix.tobytes("png")
    pil_img = Image.open(io.BytesIO(img_bytes))
    cv_img = np.array(pil_img)
    # RGB → BGR
    if cv_img.ndim == 3 and cv_img.shape[2] == 4:
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGBA2BGR)
    elif cv_img.ndim == 3:
        cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
    return cv_img


# ---------------------------------------------------------------------------
# OpenCV line & checkbox detection
# ---------------------------------------------------------------------------

def _detect_horizontal_lines(
    cv_img: np.ndarray,
    page_width: float,
    page_height: float,
    min_line_len_pt: float = 40,
    dpi: int = 200,
) -> List[dict]:
    """
    Detect horizontal lines in the rasterised image and convert their
    pixel coordinates back to PDF points.
    Returns list of {x, y, width, height} dicts.
    """
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Threshold to get dark pixels (lines are dark)
    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)

    # Horizontal kernel — width much larger than height
    min_kernel_w = max(int(min_line_len_pt * dpi / 72), 30)
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (min_kernel_w, 1))
    detected = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horiz_kernel)

    # Find contours of detected horizontal lines
    contours, _ = cv2.findContours(detected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    scale = 72.0 / dpi  # pixel → point
    lines = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        # Filter: must be wide and short (a line, not a box)
        if cw < min_kernel_w or ch > 5:
            continue
        # Convert to PDF coordinates
        px = x * scale
        py = y * scale
        pw = cw * scale
        ph = max(ch * scale, 1.5)  # min height for a usable field
        lines.append({"x": px, "y": py, "width": pw, "height": ph})

    return lines


def _detect_checkboxes(
    cv_img: np.ndarray,
    page_width: float,
    page_height: float,
    min_size_pt: float = 8,
    max_size_pt: float = 25,
    dpi: int = 200,
) -> List[dict]:
    """
    Detect small square/rectangle shapes that look like checkboxes.
    Returns list of {x, y, width, height} dicts.
    """
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Edge detection
    edges = cv2.Canny(gray, 50, 150)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    scale = 72.0 / dpi
    min_px = int(min_size_pt * dpi / 72)
    max_px = int(max_size_pt * dpi / 72)

    checkboxes = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        # Must be roughly square and within size bounds
        aspect = cw / ch if ch > 0 else 0
        if (min_px <= cw <= max_px and
                min_px <= ch <= max_px and
                0.7 <= aspect <= 1.3):
            px = x * scale
            py = y * scale
            pw = cw * scale
            ph = ch * scale
            checkboxes.append({"x": px, "y": py, "width": pw, "height": ph})

    return checkboxes


# ---------------------------------------------------------------------------
# pdfplumber table detection
# ---------------------------------------------------------------------------

def _detect_table_cells(pdf_path: str) -> List[dict]:
    """
    Use pdfplumber's table detection to find table cells.
    Returns list of {page, x, y, width, height} dicts.
    """
    cells = []
    with pdfplumber.open(pdf_path) as pdf:
        for pno, page in enumerate(pdf.pages):
            tables = page.find_tables()
            for table in tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell is not None:
                            x0, top, x1, bottom = cell
                            cells.append({
                                "page": pno,
                                "x": float(x0),
                                "y": float(top),
                                "width": float(x1 - x0),
                                "height": float(bottom - top),
                            })
    return cells


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _overlap(a: dict, b: dict, threshold: float = 0.5) -> bool:
    """Check if two rectangles overlap by more than threshold fraction."""
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["width"], a["y"] + a["height"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["width"], b["y"] + b["height"]

    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    intersection = ix * iy

    area_a = a["width"] * a["height"]
    area_b = b["width"] * b["height"]
    smaller = min(area_a, area_b)
    if smaller <= 0:
        return False
    return (intersection / smaller) >= threshold


def _dedup(fields: List[dict], existing: List[dict]) -> bool:
    """Return True if `fields` item overlaps with anything in `existing`."""
    for f in fields:
        for e in existing:
            if _overlap(f, e):
                return True
    return False


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def detect_fields(pdf_path: str, verbose: bool = False) -> List[dict]:
    """
    Detect form fields in a flat PDF.

    Returns a list of field dicts:
        page, type, x, y, width, height, label, name
    """
    # 1. Extract text blocks for labelling
    text_pages = _extract_text_blocks(pdf_path)

    # 2. Get page count and dimensions from PyMuPDF
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    page_sizes = []
    for pno in range(page_count):
        page = doc[pno]
        page_sizes.append((page.rect.width, page.rect.height))
    doc.close()

    all_fields: List[Field] = []
    dpi = 200

    # 3. Detect table cells via pdfplumber
    table_cells_raw = _detect_table_cells(pdf_path)
    for idx, tc in enumerate(table_cells_raw):
        pno = tc["page"]
        blocks = text_pages.get(pno, [])
        label = _find_nearest_label(tc["x"], tc["y"], blocks)
        base_name = _sanitize_label(label) or f"table_cell"
        name = f"{base_name}_{idx}_{pno}_{int(tc['x'])}_{int(tc['y'])}"
        all_fields.append(Field(
            page=pno, type="table_cell",
            x=tc["x"], y=tc["y"],
            width=tc["width"], height=tc["height"],
            label=label, name=name,
        ))

    # 4. Per-page: rasterise → detect lines & checkboxes
    for pno in range(page_count):
        pw, ph = page_sizes[pno]
        cv_img = _rasterise_page(pdf_path, pno, dpi=dpi)
        blocks = text_pages.get(pno, [])

        # Horizontal lines → text fields
        lines = _detect_horizontal_lines(cv_img, pw, ph, dpi=dpi)
        for ln in lines:
            # Skip if overlaps a table cell
            if any(_overlap(ln, {"x": f.x, "y": f.y, "width": f.width, "height": f.height})
                   for f in all_fields if f.page == pno):
                continue
            # The field sits ON the line; bump y up slightly so the field
            # sits above the line (where you write)
            field_y = max(ln["y"] - 14, 0)
            field_h = 14
            label = _find_nearest_label(ln["x"], field_y, blocks)
            base_name = _sanitize_label(label) or "text"
            name = f"{base_name}_{pno}_{int(ln['x'])}_{int(ln['y'])}"
            all_fields.append(Field(
                page=pno, type="text",
                x=ln["x"], y=field_y,
                width=ln["width"], height=field_h,
                label=label, name=name,
            ))

        # Checkboxes
        checkboxes = _detect_checkboxes(cv_img, pw, ph, dpi=dpi)
        for cb in checkboxes:
            if any(_overlap(cb, {"x": f.x, "y": f.y, "width": f.width, "height": f.height})
                   for f in all_fields if f.page == pno):
                continue
            label = _find_nearest_label(cb["x"], cb["y"], blocks)
            base_name = _sanitize_label(label) or "checkbox"
            name = f"{base_name}_{pno}_{int(cb['x'])}_{int(cb['y'])}"
            all_fields.append(Field(
                page=pno, type="checkbox",
                x=cb["x"], y=cb["y"],
                width=cb["width"], height=cb["height"],
                label=label, name=name,
            ))

    if verbose:
        print(f"\n--- Detection Summary ---")
        print(f"Pages scanned: {page_count}")
        by_type = {}
        for f in all_fields:
            by_type[f.type] = by_type.get(f.type, 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"  {t}: {c}")
        print(f"Total fields: {len(all_fields)}\n")

    return [f.to_dict() for f in all_fields]


def detect_fields_json(pdf_path: str, verbose: bool = False) -> str:
    """Same as detect_fields but returns JSON string."""
    return json.dumps(detect_fields(pdf_path, verbose=verbose), indent=2)


# ---------------------------------------------------------------------------
# CLI helper for --fields-only
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python detector.py <input.pdf>")
        sys.exit(1)
    print(detect_fields_json(sys.argv[1], verbose=True))