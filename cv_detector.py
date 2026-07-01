"""
pdfforge/cv_detector.py — Computer Vision Field Detection (Phase 2)

Uses OpenCV-based image analysis to detect form fields in scanned PDFs
or any PDF where vector extraction returns zero fields.

Pipeline:
  1. Rasterize PDF page to image (PyMuPDF)
  2. Preprocess (grayscale, threshold, denoise)
  3. Detect horizontal lines (text field underlines)
  4. Detect rectangles (checkboxes, table cells, text areas)
  5. Detect contours (fallback field candidates)
  6. Label fields using nearest text (OCR via PyMuPDF text blocks)
  7. Return field dicts in same format as detector.py

This is a fallback module — detector.py's vector extraction is primary
and more accurate for digital-native PDFs. This module activates when
vector extraction returns 0 fields (scanned/image-only PDFs).

Future: Replace OpenCV heuristics with a YOLOv8 model trained on
100-10,000 real PDF forms (see docs/CV_ML_ROADMAP.md).
"""

from __future__ import annotations

import json
import re
import logging
from typing import List, Optional, Tuple

import fitz  # PyMuPDF
import cv2
import numpy as np

logger = logging.getLogger("pdfforge.cv_detector")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Render DPI for rasterization (higher = more accurate, slower)
DEFAULT_DPI = 200

# Detection thresholds
MIN_LINE_WIDTH_PX = 40       # Minimum width for a horizontal line (pixels)
MAX_LINE_THICKNESS_PX = 3    # Maximum thickness for a line (pixels)
MIN_CHECKBOX_SIZE_PX = 12    # Minimum checkbox dimension (pixels)
MAX_CHECKBOX_SIZE_PX = 40    # Maximum checkbox dimension (pixels)
MIN_TEXTAREA_WIDTH_PX = 80   # Minimum width for a text area
MIN_TEXTAREA_HEIGHT_PX = 30  # Minimum height for a text area
MIN_CELL_SIZE_PX = 20        # Minimum table cell dimension

# Overlap threshold for deduplication
DEDUP_OVERLAP_THRESHOLD = 0.4


# ---------------------------------------------------------------------------
# Rasterization
# ---------------------------------------------------------------------------

def _rasterize_page(pdf_path: str, page_num: int, dpi: int = DEFAULT_DPI) -> Tuple[np.ndarray, float]:
    """
    Rasterize a PDF page to an OpenCV image.

    Returns:
        (image, scale) where scale converts image pixels back to PDF points.
        PDF points = image_pixels * 72 / dpi
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    doc.close()

    # Convert to OpenCV format (BGR)
    img_bytes = pix.tobytes("png")
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    scale = 72.0 / dpi  # image_pixels * scale = PDF points
    return img, scale


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

def _preprocess(img: np.ndarray) -> dict:
    """
    Preprocess the image for detection.
    Returns a dict of processed images for different detection strategies.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Binary threshold (adaptive for varying lighting in scans)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, blockSize=21, C=5
    )

    # Denoised version for contour detection
    denoised = cv2.fastNlMeansDenoising(gray, h=10)

    return {
        "gray": gray,
        "binary": binary,
        "denoised": denoised,
    }


# ---------------------------------------------------------------------------
# Line detection (horizontal lines = text field underlines)
# ---------------------------------------------------------------------------

def _detect_lines(binary: np.ndarray, scale: float) -> List[dict]:
    """
    Detect horizontal lines that indicate text field positions.
    Returns list of field dicts with type='text'.
    """
    fields = []

    # Use morphological operations to find horizontal lines
    # Kernel width = min line width, height = max thickness
    kernel_w = max(int(MIN_LINE_WIDTH_PX / scale), 20)
    kernel_h = max(int(MAX_LINE_THICKNESS_PX / scale), 3)

    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_w, kernel_h))
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)

    # Find contours of detected lines
    contours, _ = cv2.findContours(horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)

        # Convert to PDF coordinates
        pdf_x = x * scale
        pdf_y = y * scale
        pdf_w = w * scale
        pdf_h = h * scale

        # Filter: must be a horizontal line (wide, thin)
        if pdf_w < 30 or pdf_h > 3:
            continue

        # Text field sits ABOVE the line
        field_y = max(pdf_y - 14, 0)
        field = {
            "type": "text",
            "x": round(pdf_x, 1),
            "y": round(field_y, 1),
            "width": round(pdf_w, 1),
            "height": 14,
            "label": "",  # Will be filled by label finder
            "name": "",
            "flags": [],
            "_source": "cv_line",
        }
        fields.append(field)

    return fields


# ---------------------------------------------------------------------------
# Rectangle detection (checkboxes, table cells, text areas)
# ---------------------------------------------------------------------------

def _detect_rectangles(binary: np.ndarray, scale: float) -> List[dict]:
    """
    Detect rectangular shapes: checkboxes, table cells, and text areas.
    """
    fields = []

    # Find all contours
    contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    for contour in contours:
        # Approximate to polygon
        epsilon = 0.02 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)

        # Only consider quadrilaterals (4 corners)
        if len(approx) != 4:
            continue

        x, y, w, h = cv2.boundingRect(approx)

        # Convert to PDF coordinates
        pdf_x = x * scale
        pdf_y = y * scale
        pdf_w = w * scale
        pdf_h = h * scale

        # Classify by size
        if MIN_CHECKBOX_SIZE_PX <= pdf_w <= MAX_CHECKBOX_SIZE_PX and MIN_CHECKBOX_SIZE_PX <= pdf_h <= MAX_CHECKBOX_SIZE_PX:
            # Roughly square = checkbox
            aspect = pdf_w / pdf_h if pdf_h > 0 else 0
            if 0.7 <= aspect <= 1.4:
                field = {
                    "type": "checkbox",
                    "x": round(pdf_x, 1),
                    "y": round(pdf_y, 1),
                    "width": round(pdf_w, 1),
                    "height": round(pdf_h, 1),
                    "label": "",
                    "name": "",
                    "flags": [],
                    "_source": "cv_checkbox",
                }
                fields.append(field)

        elif pdf_w >= MIN_TEXTAREA_WIDTH_PX and pdf_h >= MIN_TEXTAREA_HEIGHT_PX and pdf_h <= 200:
            # Large rectangle = text area
            field = {
                "type": "textarea",
                "x": round(pdf_x, 1),
                "y": round(pdf_y, 1),
                "width": round(pdf_w, 1),
                "height": round(pdf_h, 1),
                "label": "",
                "name": "",
                "flags": ["multiline"],
                "_source": "cv_textarea",
            }
            fields.append(field)

        elif pdf_w >= MIN_CELL_SIZE_PX and pdf_h >= MIN_CELL_SIZE_PX and pdf_h <= 60:
            # Medium rectangle = table cell
            field = {
                "type": "table_cell",
                "x": round(pdf_x, 1),
                "y": round(pdf_y, 1),
                "width": round(pdf_w, 1),
                "height": round(pdf_h, 1),
                "label": "",
                "name": "",
                "flags": [],
                "_source": "cv_table_cell",
            }
            fields.append(field)

    return fields


# ---------------------------------------------------------------------------
# Label finding (using PyMuPDF text blocks)
# ---------------------------------------------------------------------------

def _sanitize_label(label: str) -> str:
    """Turn a label into a valid AcroForm field name."""
    if not label:
        return ""
    cleaned = re.sub(r'[*:?]+$', '', label).strip()
    cleaned = re.sub(r'[^A-Za-z0-9 ]+', '', cleaned).strip()
    cleaned = cleaned.replace(' ', '_')
    if cleaned and cleaned[0].isdigit():
        cleaned = 'f_' + cleaned
    return cleaned or 'field'


def _find_labels(fields: List[dict], text_blocks: list) -> None:
    """
    Find nearest text label for each field.
    Modifies fields in-place, setting 'label' and 'name'.
    """
    for field in fields:
        best_label = ""
        best_dist = float("inf")
        fx = field["x"]
        fy = field["y"]
        fw = field["width"]
        fh = field["height"]
        ftype = field["type"]

        for blk in text_blocks:
            bx, by = blk["cx"], blk["cy"]
            blk_right = blk["x1"]
            blk_left = blk["x0"]

            if ftype in ("checkbox", "radio"):
                is_right = blk_left >= fx - 5 and abs(by - (fy + fh / 2)) < 20
                if not is_right:
                    continue
                dist = ((fx + fw - blk_left) ** 2 + (fy + fh / 2 - by) ** 2) ** 0.5
            elif ftype == "textarea":
                is_above = by < fy - 2 and abs(bx - (fx + fw / 2)) < fw * 0.7
                if not is_above:
                    continue
                dist = ((fx + fw / 2 - bx) ** 2 + (fy - by) ** 2) ** 0.5
            elif ftype == "table_cell":
                is_above = by < fy - 2 and abs(bx - fx) < fw * 0.8
                is_left = blk_right <= fx + 5 and abs(by - (fy + fh / 2)) < fh
                if not (is_above or is_left):
                    continue
                dist = ((fx - bx) ** 2 + (fy - by) ** 2) ** 0.5
            else:  # text
                is_left = blk_right <= fx + 10 and abs(by - (fy + 7)) < 15
                is_above = by < fy - 2 and abs(bx - fx) < 30
                if not (is_left or is_above):
                    continue
                dist = ((fx - bx) ** 2 + (fy + 7 - by) ** 2) ** 0.5
                if is_above and not is_left:
                    dist += 30

            if dist < best_dist and dist <= 150:
                best_dist = dist
                best_label = blk["text"]

        if best_label:
            lines = [l.strip() for l in best_label.split('\n') if l.strip()]
            if ftype in ("checkbox", "radio", "textarea"):
                best_label = ' '.join(lines)
            else:
                best_label = lines[-1] if lines else ""
            best_label = re.sub(r'[*:?]+$', '', best_label).strip()

        field["label"] = best_label
        base = _sanitize_label(best_label) or ftype
        field["name"] = f"{base}_{field['page']}_{int(field['x'])}_{int(field['y'])}"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _overlap(a: dict, b: dict, threshold: float = DEDUP_OVERLAP_THRESHOLD) -> bool:
    """Check if two rectangles overlap by more than threshold fraction."""
    ax0, ay0 = a["x"], a["y"]
    ax1, ay1 = a["x"] + a.get("width", 0), a["y"] + a.get("height", 0)
    bx0, by0 = b["x"], b["y"]
    bx1, by1 = b["x"] + b.get("width", 0), b["y"] + b.get("height", 0)

    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    intersection = ix * iy

    area_a = a.get("width", 0) * a.get("height", 0)
    area_b = b.get("width", 0) * b.get("height", 0)
    smaller = min(area_a, area_b)
    if smaller <= 0:
        return False
    return (intersection / smaller) >= threshold


def _deduplicate(fields: List[dict]) -> List[dict]:
    """Remove overlapping fields, keeping the first occurrence."""
    result = []
    for f in fields:
        if not any(_overlap(f, existing) for existing in result):
            result.append(f)
    return result


# ---------------------------------------------------------------------------
# Main CV detection function
# ---------------------------------------------------------------------------

def detect_fields_cv(pdf_path: str, verbose: bool = False) -> List[dict]:
    """
    Detect form fields using computer vision (OpenCV).
    Used as a fallback when vector extraction returns 0 fields.

    Args:
        pdf_path: Path to the PDF file
        verbose: Print detection summary

    Returns:
        List of field dicts in the same format as detector.detect_fields()
    """
    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    doc.close()

    # Extract text blocks for labeling (same as vector detector)
    text_pages = {}
    doc = fitz.open(pdf_path)
    for pno in range(num_pages):
        page = doc[pno]
        blocks = []
        for block in page.get_text("blocks"):
            x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
            text = text.strip()
            if text:
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                blocks.append({
                    "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "text": text,
                    "cx": (x0 + x1) / 2,
                    "cy": (y0 + y1) / 2,
                    "lines": lines,
                })
        text_pages[pno] = blocks
    doc.close()

    all_fields = []

    for pno in range(num_pages):
        try:
            img, scale = _rasterize_page(pdf_path, pno)
        except Exception as e:
            logger.warning(f"Failed to rasterize page {pno}: {e}")
            continue

        processed = _preprocess(img)

        # Detect lines (text fields)
        page_lines = _detect_lines(processed["binary"], scale)

        # Detect rectangles (checkboxes, table cells, text areas)
        page_rects = _detect_rectangles(processed["binary"], scale)

        # Add page numbers
        for f in page_lines + page_rects:
            f["page"] = pno

        # Deduplicate within page
        page_fields = _deduplicate(page_lines + page_rects)

        # Find labels
        _find_labels(page_fields, text_pages.get(pno, []))

        # Remove internal _source key
        for f in page_fields:
            f.pop("_source", None)

        # Sort by reading order
        page_fields.sort(key=lambda f: (f["y"], f["x"]))

        all_fields.extend(page_fields)

    if verbose:
        print(f"\n--- CV Detection Summary ---")
        by_type = {}
        for f in all_fields:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"  {t}: {c}")
        print(f"Total fields: {len(all_fields)}\n")

    return all_fields


# ---------------------------------------------------------------------------
# Hybrid detection (vector first, CV fallback)
# ---------------------------------------------------------------------------

def detect_fields_hybrid(pdf_path: str, verbose: bool = False) -> List[dict]:
    """
    Try vector extraction first (detector.py). If 0 fields found,
    fall back to CV detection (this module).

    This is the recommended entry point for production use.
    """
    from detector import detect_fields as vector_detect

    # Try vector extraction first
    fields = vector_detect(pdf_path, verbose=verbose)

    if len(fields) > 0:
        if verbose:
            print(f"Vector extraction found {len(fields)} fields — CV fallback not needed.")
        return fields

    if verbose:
        print(f"Vector extraction found 0 fields — falling back to CV detection...")

    # Fall back to CV
    cv_fields = detect_fields_cv(pdf_path, verbose=verbose)

    if verbose and len(cv_fields) == 0:
        print("CV detection also found 0 fields. This may be a scanned PDF with no detectable form elements.")

    return cv_fields


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python cv_detector.py <input.pdf>")
        sys.exit(1)
    fields = detect_fields_cv(sys.argv[1], verbose=True)
    print(json.dumps(fields, indent=2))