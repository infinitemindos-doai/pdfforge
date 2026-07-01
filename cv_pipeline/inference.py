"""
pdfforge/cv_pipeline/inference.py — YOLOv8 Inference Module (Phase 2)

Loads a trained YOLOv8 model and runs field detection on PDFs.
This is the production inference module that replaces cv_detector.py's
OpenCV heuristics with a trained neural network.

Usage:
    from cv_pipeline.inference import detect_fields_yolo
    fields = detect_fields_yolo("scanned_form.pdf", model_path="best.pt")

    # Or via CLI:
    python cv_pipeline/inference.py --pdf input.pdf --model best.pt
"""

from __future__ import annotations

import os
import sys
import json
import logging
from typing import List, Optional

import fitz  # PyMuPDF
import cv2
import numpy as np

logger = logging.getLogger("pdfforge.inference")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DPI = 200
DEFAULT_CONF_THRESHOLD = 0.25

# Reverse class mapping (index -> name)
CLASS_NAMES = ["text", "checkbox", "radio", "table_cell", "textarea"]


# ---------------------------------------------------------------------------
# Rasterization
# ---------------------------------------------------------------------------

def _rasterize_page(pdf_path: str, page_num: int, dpi: int = DEFAULT_DPI) -> tuple:
    """Rasterize a PDF page to OpenCV image."""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    page_w = page.rect.width
    page_h = page.rect.height
    doc.close()

    img_bytes = pix.tobytes("png")
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

    return img, page_w, page_h, dpi


# ---------------------------------------------------------------------------
# Label extraction (for field naming)
# ---------------------------------------------------------------------------

def _sanitize_label(label: str) -> str:
    if not label:
        return ""
    import re
    cleaned = re.sub(r'[*:?]+$', '', label).strip()
    cleaned = re.sub(r'[^A-Za-z0-9 ]+', '', cleaned).strip()
    cleaned = cleaned.replace(' ', '_')
    if cleaned and cleaned[0].isdigit():
        cleaned = 'f_' + cleaned
    return cleaned or 'field'


def _find_labels(fields: List[dict], text_blocks: list) -> None:
    """Find nearest text label for each field."""
    import re

    for field in fields:
        best_label = ""
        best_dist = float("inf")
        fx, fy = field["x"], field["y"]
        fw, fh = field["width"], field["height"]
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
            else:
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
# Text block extraction
# ---------------------------------------------------------------------------

def _extract_text_blocks(pdf_path: str) -> dict:
    """Extract text blocks for labeling."""
    doc = fitz.open(pdf_path)
    pages = {}
    for pno in range(len(doc)):
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
        pages[pno] = blocks
    doc.close()
    return pages


# ---------------------------------------------------------------------------
# YOLO inference
# ---------------------------------------------------------------------------

def detect_fields_yolo(
    pdf_path: str,
    model_path: str = "best.pt",
    conf_threshold: float = DEFAULT_CONF_THRESHOLD,
    dpi: int = DEFAULT_DPI,
    verbose: bool = False,
) -> List[dict]:
    """
    Detect form fields using a trained YOLOv8 model.

    Args:
        pdf_path: Path to the PDF file
        model_path: Path to trained model weights (.pt or .onnx)
        conf_threshold: Minimum confidence for detections
        dpi: Rasterization DPI
        verbose: Print detection summary

    Returns:
        List of field dicts in the same format as detector.detect_fields()
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("ultralytics not installed. Run: pip install ultralytics")
        return []

    # Load model
    model = YOLO(model_path)

    # Extract text blocks for labeling
    text_pages = _extract_text_blocks(pdf_path)

    # Get page count
    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    doc.close()

    all_fields = []

    for pno in range(num_pages):
        # Rasterize
        img, page_w, page_h, actual_dpi = _rasterize_page(pdf_path, pno, dpi)

        # Run inference
        results = model(img, conf=conf_threshold, verbose=False)

        scale = 72.0 / actual_dpi  # pixels -> PDF points

        for result in results:
            boxes = result.boxes
            for i in range(len(boxes)):
                # Get box coordinates (pixel space)
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                conf = float(boxes.conf[i].cpu().numpy())
                cls_id = int(boxes.cls[i].cpu().numpy())

                if cls_id >= len(CLASS_NAMES):
                    logger.warning(f"Unknown class ID {cls_id}, skipping")
                    continue

                cls_name = CLASS_NAMES[cls_id]

                # Convert to PDF coordinates
                pdf_x = x1 * scale
                pdf_y = y1 * scale
                pdf_w = (x2 - x1) * scale
                pdf_h = (y2 - y1) * scale

                # For text fields detected as lines, place above
                if cls_name == "text" and pdf_h < 5:
                    pdf_y = max(pdf_y - 14, 0)
                    pdf_h = 14

                field = {
                    "page": pno,
                    "type": cls_name,
                    "x": round(pdf_x, 1),
                    "y": round(pdf_y, 1),
                    "width": round(pdf_w, 1),
                    "height": round(pdf_h, 1),
                    "label": "",
                    "name": "",
                    "flags": ["multiline"] if cls_name == "textarea" else [],
                    "confidence": round(conf, 3),
                }
                all_fields.append(field)

        # Find labels
        _find_labels(
            [f for f in all_fields if f["page"] == pno],
            text_pages.get(pno, [])
        )

    # Sort by reading order
    all_fields.sort(key=lambda f: (f["page"], f["y"], f["x"]))

    if verbose:
        print(f"\n--- YOLO Detection Summary ---")
        by_type = {}
        for f in all_fields:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"  {t}: {c}")
        print(f"Total fields: {len(all_fields)}\n")

    return all_fields


# ---------------------------------------------------------------------------
# Hybrid detection: vector -> CV heuristic -> YOLO model
# ---------------------------------------------------------------------------

def detect_fields_smart(pdf_path: str, model_path: Optional[str] = None, verbose: bool = False) -> List[dict]:
    """
    Smart detection pipeline:
    1. Try vector extraction (detector.py) — best for digital PDFs
    2. If 0 fields, try CV heuristic (cv_detector.py) — for simple scanned PDFs
    3. If model available, try YOLO inference — for complex scanned PDFs

    Args:
        pdf_path: Path to PDF
        model_path: Optional path to trained YOLOv8 model
        verbose: Print progress

    Returns:
        List of field dicts
    """
    # Step 1: Vector extraction
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from detector import detect_fields as vector_detect

    fields = vector_detect(pdf_path, verbose=verbose)
    if len(fields) > 0:
        if verbose:
            print(f"Vector extraction: {len(fields)} fields found. Done.")
        return fields

    if verbose:
        print("Vector extraction: 0 fields. Trying CV heuristic...")

    # Step 2: CV heuristic
    from cv_detector import detect_fields_cv
    fields = detect_fields_cv(pdf_path, verbose=verbose)
    if len(fields) > 0:
        if verbose:
            print(f"CV heuristic: {len(fields)} fields found.")
        return fields

    # Step 3: YOLO model (if available)
    if model_path and os.path.exists(model_path):
        if verbose:
            print("CV heuristic: 0 fields. Trying YOLO model...")
        fields = detect_fields_yolo(pdf_path, model_path, verbose=verbose)
        if verbose:
            print(f"YOLO model: {len(fields)} fields found.")
        return fields

    if verbose:
        print("All detection methods exhausted. No fields found.")

    return fields


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PDFForge YOLOv8 Inference")
    parser.add_argument("--pdf", "-p", required=True, help="Input PDF file")
    parser.add_argument("--model", "-m", default="best.pt", help="Path to trained model weights")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument("--dpi", type=int, default=200, help="Rasterization DPI")
    parser.add_argument("--smart", action="store_true", help="Use smart pipeline (vector -> CV -> YOLO)")

    args = parser.parse_args()

    if args.smart:
        fields = detect_fields_smart(args.pdf, model_path=args.model, verbose=True)
    else:
        fields = detect_fields_yolo(args.pdf, args.model, conf_threshold=args.conf, dpi=args.dpi, verbose=True)

    print(json.dumps(fields, indent=2))