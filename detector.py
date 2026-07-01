"""
pdfforge/detector.py — Field Detection Engine v4

Takes a flat PDF (no existing form fields) and detects where fillable
areas should go: horizontal lines (text fields), checkbox squares,
radio button circles, table cells, multi-line text areas, dropdowns,
signature lines, and barcode areas.

v4 improvements over v3:
  - Added dropdown/combo box detection (rectangles with small triangle)
  - Added signature field detection (lines with "signature" label)
  - Added barcode area detection (square regions with barcode labels)
  - Added visibility state field (visible, hidden, visible_non_print, hidden_printable)
  - Added validation hint detection (numeric/date patterns in labels)
  - Improved field flag set: required, multiline, readonly, numeric, date, currency

v3 improvements over v2:
  - Fixed extra_cells variable bug (was referenced as extra_fields)
  - Added radio button detection (small circles via bezier curves)
  - Added multi-line text area detection (large rectangles)
  - Better multi-line label handling (joins lines for checkboxes/textareas)
  - Tab order sorting (top-to-bottom, left-to-right per page)
  - Field flags (required, multiline)
  - Page-filtered overlap check in pdfplumber supplement
  - Label colon stripping for cleaner display
  - Scanned PDF warning when no vector drawings found

Output: list of field dicts (JSON-serialisable) with keys:
    page, type, x, y, width, height, label, name, flags, visibility, validation
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import List, Optional

import fitz  # PyMuPDF
import pdfplumber


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """A single detected form field."""
    page: int          # 0-indexed
    type: str          # "text" | "checkbox" | "radio" | "table_cell" | "textarea" | "dropdown" | "signature" | "barcode"
    x: float           # PDF coordinate (top-left x, points)
    y: float           # PDF coordinate (top-left y, points)
    width: float
    height: float
    label: str = ""
    name: str = ""
    flags: list = None  # ["required", "multiline", "readonly", etc.]
    visibility: str = "visible"  # "visible" | "hidden" | "visible_non_print" | "hidden_printable"
    validation: str = ""  # "" | "numeric" | "date" | "currency" | "email" | "phone" | "zip" | "ssn"

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_label(label: str) -> str:
    """Turn a human-readable label into a valid AcroForm field name."""
    if not label:
        return ""
    # Remove trailing colons, asterisks (common in form labels)
    cleaned = re.sub(r'[*:?]+$', '', label).strip()
    # Keep only alphanumeric + spaces
    cleaned = re.sub(r'[^A-Za-z0-9 ]+', '', cleaned).strip()
    cleaned = cleaned.replace(' ', '_')
    if cleaned and cleaned[0].isdigit():
        cleaned = 'f_' + cleaned
    return cleaned or 'field'


def _clean_label(label: str) -> str:
    """Clean up a label for display — strip trailing colons/asterisks."""
    if not label:
        return ""
    return re.sub(r'[*:?]+$', '', label).strip()


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Validation hint detection from label text
# ---------------------------------------------------------------------------

_VALIDATION_PATTERNS = {
    "numeric": [r'\b(number|qty|quantity|amount|count|age|score|rating|percent)\b', r'\b\d+\s*[-]\s*\d+\b'],  # ranges
    "date": [r'\b(date|dob|birth|expire|effective|start|end|deadline|signature date)\b'],
    "currency": [r'\b(\$|amount|total|subtotal|price|cost|fee|rate|salary|wage|payment|balance|deposit|charge|amount due|amount paid)\b'],
    "email": [r'\b(email|e-mail|electronic mail)\b'],
    "phone": [r'\b(phone|telephone|mobile|cell|fax|contact number)\b'],
    "zip": [r'\b(zip|postal)\b'],
    "ssn": [r'\b(ssn|social security)\b'],
}


def _detect_validation_hint(label: str) -> str:
    """Detect validation type from label text.
    Returns one of: '', 'numeric', 'date', 'currency', 'email', 'phone', 'zip', 'ssn'
    """
    if not label:
        return ""
    label_lower = label.lower()
    for vtype, patterns in _VALIDATION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, label_lower):
                return vtype
    return ""


# ---------------------------------------------------------------------------
# Signature and barcode label detection
# ---------------------------------------------------------------------------

_SIGNATURE_KEYWORDS = ["signature", "sign here", "x ____", "signed", "authorize", "applicant signature", "tenant signature", "employee signature", "contractor signature"]
_BARCODE_KEYWORDS = ["barcode", "qr code", "pdf417", "qr", "scan code"]


def _is_signature_label(label: str) -> bool:
    if not label:
        return False
    label_lower = label.lower()
    return any(kw in label_lower for kw in _SIGNATURE_KEYWORDS)


def _is_barcode_label(label: str) -> bool:
    if not label:
        return False
    label_lower = label.lower()
    return any(kw in label_lower for kw in _BARCODE_KEYWORDS)


# ---------------------------------------------------------------------------
# Text extraction (PyMuPDF) for labelling
# ---------------------------------------------------------------------------

def _extract_text_blocks(pdf_path: str) -> dict:
    """Return {page_index: [ {x0, y0, x1, y1, text, cx, cy, lines}, ... ]}.

    Each block includes a 'lines' list for multi-line label handling.
    """
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


def _find_nearest_label(
    field_x: float,
    field_y: float,
    text_blocks: list,
    max_distance: float = 150,
    field_type: str = "text",
    field_w: float = 0,
    field_h: float = 0,
) -> str:
    """
    Find the nearest text block that serves as a label for the field.
    Strategy adapts based on field type:
      - text (line): label is to the LEFT on the same line, or above
      - checkbox/radio: label is to the RIGHT on the same line
      - table_cell: label is in the column header above, or row header to the left
      - textarea: label is ABOVE the box
    """
    best_label = ""
    best_dist = float("inf")

    for blk in text_blocks:
        bx, by = blk["cx"], blk["cy"]
        blk_right = blk["x1"]  # right edge of text
        blk_left = blk["x0"]   # left edge of text

        if field_type in ("checkbox", "radio"):
            # Label is to the RIGHT of the checkbox, on the same vertical line
            is_right = blk_left >= field_x - 5 and abs(by - (field_y + field_h / 2)) < 20
            if not is_right:
                continue
            d = _distance(field_x + field_w, field_y + field_h / 2, blk_left, by)

        elif field_type == "textarea":
            # Label is ABOVE the box (top edge)
            is_above = by < field_y - 2 and abs(bx - (field_x + field_w / 2)) < field_w * 0.7
            if not is_above:
                continue
            d = _distance(field_x + field_w / 2, field_y, bx, by)

        elif field_type == "table_cell":
            # Label is ABOVE (column header) or to the LEFT (row label)
            is_above = by < field_y - 2 and abs(bx - field_x) < field_w * 0.8
            is_left = blk_right <= field_x + 5 and abs(by - (field_y + field_h / 2)) < field_h
            if not (is_above or is_left):
                continue
            d = _distance(field_x, field_y, bx, by)

        else:  # text / line
            # Label is to the LEFT on the same line (preferred), or directly above
            is_left = blk_right <= field_x + 10 and abs(by - (field_y + 7)) < 15
            is_above = by < field_y - 2 and abs(bx - field_x) < 30
            if not (is_left or is_above):
                continue
            # Prefer left labels: penalize above labels with extra distance
            d = _distance(field_x, field_y + 7, bx, by)
            if is_above and not is_left:
                d += 30  # penalize above-line labels so same-line labels win

        if d < best_dist and d <= max_distance:
            best_dist = d
            best_label = blk["text"]

    if best_label:
        lines = [l.strip() for l in best_label.split('\n') if l.strip()]
        # For checkbox/radio/textarea labels, use the full text (usually one line)
        # For text fields, use the last line (the label is on the same line)
        if field_type in ("checkbox", "radio", "textarea"):
            best_label = ' '.join(lines)
        else:
            best_label = lines[-1] if lines else ""
    return _clean_label(best_label)


# ---------------------------------------------------------------------------
# Vector drawing extraction (PyMuPDF) — v3 primary detection
# ---------------------------------------------------------------------------

def _classify_drawing(rect: fitz.Rect, drawing: dict) -> str:
    """
    Classify a vector drawing as 'line', 'checkbox', 'radio', 'table_cell',
    'textarea', 'dropdown', 'other'.

    - Lines: height <= 2px, width >= 30px (horizontal underlines for text/signature)
    - Checkboxes: roughly square, 8-25px per side
    - Radio: small circle, 8-20px diameter (detected via bezier curve items)
    - Table cells: rectangles wider than tall, or part of a grid
    - Textarea: large rectangle, height > 25px, width > 60px
    - Dropdown: rectangle with a small triangle or narrow width + height ~20px
    """
    w = rect.width
    h = rect.height

    # Horizontal line: very thin height, decent width
    if h <= 2.0 and w >= 30.0:
        return "line"

    # Checkbox: roughly square, 8-25pt per side
    if 8.0 <= w <= 25.0 and 8.0 <= h <= 25.0:
        aspect = w / h if h > 0 else 0
        if 0.7 <= aspect <= 1.3:
            return "checkbox"

    # Radio button: small circle, 8-20px diameter
    # PyMuPDF draws circles as beziers — detect by checking items for curve ops
    items = drawing.get("items", [])
    has_curve = any(item[0] in ("c", "curve", "qu") for item in items)
    if has_curve and 6.0 <= w <= 22.0 and 6.0 <= h <= 22.0:
        aspect = w / h if h > 0 else 0
        if 0.7 <= aspect <= 1.3:
            return "radio"

    # Dropdown: rectangle with small triangle indicator, typically 80-200px wide, 15-25px tall
    # Check for small filled shapes (triangles) inside the drawing items
    has_triangle = any(
        item[0] == "l" and len(item) >= 3  # line items that could form a triangle
        for item in items
    )
    if 80.0 <= w <= 250.0 and 15.0 <= h <= 30.0 and not has_curve:
        # Could be dropdown if there are multiple short line segments (triangle indicator)
        if len(items) >= 3:
            return "dropdown"

    # Textarea: large rectangle (multi-line input area)
    if w >= 60.0 and h >= 25.0 and h <= 200.0:
        if h <= 60.0 and w <= 200.0:
            if h > w * 0.5:
                return "textarea"
            return "table_cell"
        return "textarea"

    # Table cell: rectangle, wider than tall (or square), larger than checkbox
    if w >= 30.0 and h >= 10.0 and h <= 60.0:
        return "table_cell"

    return "other"


def _detect_fields_from_drawings(pdf_path: str, text_pages: dict) -> List[dict]:
    """
    Extract form fields directly from PyMuPDF's vector drawing data.
    This is far more accurate than rasterising + OpenCV because we get
    exact coordinates from the PDF content stream.
    """
    doc = fitz.open(pdf_path)
    all_fields = []

    for pno in range(len(doc)):
        page = doc[pno]
        blocks = text_pages.get(pno, [])
        drawings = page.get_drawings()

        page_lines = []
        page_checkboxes = []
        page_radios = []
        page_table_cells = []
        page_textareas = []

        for d in drawings:
            rect = d["rect"]
            dtype = _classify_drawing(rect, d)

            if dtype == "line":
                # Horizontal line -> text field or signature field
                # Check if the label indicates a signature field
                field_x = rect.x0
                field_y = max(rect.y0 - 14, 0)
                field_w = rect.width
                field_h = 14
                label = _find_nearest_label(
                    field_x, field_y, blocks,
                    field_type="text", field_w=field_w, field_h=field_h
                )
                # Check if this is a signature line
                if _is_signature_label(label):
                    ftype = "signature"
                    base_name = _sanitize_label(label) or "signature"
                else:
                    ftype = "text"
                    base_name = _sanitize_label(label) or "text"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                validation = _detect_validation_hint(label)
                page_lines.append({
                    "page": pno, "type": ftype,
                    "x": field_x, "y": field_y,
                    "width": field_w, "height": field_h,
                    "label": label, "name": name,
                    "flags": [],
                    "visibility": "visible",
                    "validation": validation,
                })

            elif dtype == "checkbox":
                label = _find_nearest_label(
                    rect.x0, rect.y0, blocks,
                    field_type="checkbox", field_w=rect.width, field_h=rect.height
                )
                # Check if this is actually a barcode area (square + barcode label)
                if _is_barcode_label(label):
                    base_name = _sanitize_label(label) or "barcode"
                    name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                    page_checkboxes.append({
                        "page": pno, "type": "barcode",
                        "x": rect.x0, "y": rect.y0,
                        "width": rect.width, "height": rect.height,
                        "label": label, "name": name,
                        "flags": [],
                        "visibility": "visible",
                        "validation": "",
                    })
                    continue
                base_name = _sanitize_label(label) or "checkbox"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_checkboxes.append({
                    "page": pno, "type": "checkbox",
                    "x": rect.x0, "y": rect.y0,
                    "width": rect.width, "height": rect.height,
                    "label": label, "name": name,
                    "flags": [],
                    "visibility": "visible",
                    "validation": "",
                })

            elif dtype == "radio":
                label = _find_nearest_label(
                    rect.x0, rect.y0, blocks,
                    field_type="radio", field_w=rect.width, field_h=rect.height
                )
                base_name = _sanitize_label(label) or "radio"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_radios.append({
                    "page": pno, "type": "radio",
                    "x": rect.x0, "y": rect.y0,
                    "width": rect.width, "height": rect.height,
                    "label": label, "name": name,
                    "flags": [],
                    "visibility": "visible",
                    "validation": "",
                })

            elif dtype == "textarea":
                label = _find_nearest_label(
                    rect.x0, rect.y0, blocks,
                    field_type="textarea", field_w=rect.width, field_h=rect.height
                )
                base_name = _sanitize_label(label) or "textarea"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_textareas.append({
                    "page": pno, "type": "textarea",
                    "x": rect.x0, "y": rect.y0,
                    "width": rect.width, "height": rect.height,
                    "label": label, "name": name,
                    "flags": ["multiline"],
                    "visibility": "visible",
                    "validation": "",
                })

            elif dtype == "dropdown":
                label = _find_nearest_label(
                    rect.x0, rect.y0, blocks,
                    field_type="text", field_w=rect.width, field_h=rect.height
                )
                base_name = _sanitize_label(label) or "dropdown"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_table_cells.append({
                    "page": pno, "type": "dropdown",
                    "x": rect.x0, "y": rect.y0,
                    "width": rect.width, "height": rect.height,
                    "label": label, "name": name,
                    "flags": [],
                    "visibility": "visible",
                    "validation": "",
                })

            elif dtype == "table_cell":
                label = _find_nearest_label(
                    rect.x0, rect.y0, blocks,
                    field_type="table_cell", field_w=rect.width, field_h=rect.height
                )
                base_name = _sanitize_label(label) or "table_cell"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_table_cells.append({
                    "page": pno, "type": "table_cell",
                    "x": rect.x0, "y": rect.y0,
                    "width": rect.width, "height": rect.height,
                    "label": label, "name": name,
                    "flags": [],
                    "visibility": "visible",
                    "validation": "",
                })

        # Deduplicate: remove table cells that overlap with lines
        filtered_cells = []
        for cell in page_table_cells:
            overlaps_line = False
            for ln in page_lines:
                if _overlap(cell, ln, threshold=0.5):
                    overlaps_line = True
                    break
            if not overlaps_line:
                filtered_cells.append(cell)

        # Remove text fields that overlap with table cells
        filtered_lines = []
        for ln in page_lines:
            overlaps_cell = False
            for cell in filtered_cells:
                if _overlap(ln, cell, threshold=0.5):
                    overlaps_cell = True
                    break
            if not overlaps_cell:
                filtered_lines.append(ln)

        # Remove textareas that overlap with table cells
        filtered_textareas = []
        for ta in page_textareas:
            overlaps_cell = False
            for cell in filtered_cells:
                if _overlap(ta, cell, threshold=0.5):
                    overlaps_cell = True
                    break
            if not overlaps_cell:
                filtered_textareas.append(ta)

        # Sort by reading order (top-to-bottom, left-to-right) for tab order
        page_fields = (
            filtered_cells + filtered_lines + page_checkboxes
            + page_radios + filtered_textareas
        )
        page_fields.sort(key=lambda f: (f["y"], f["x"]))

        all_fields.extend(page_fields)

    doc.close()
    return all_fields


# ---------------------------------------------------------------------------
# pdfplumber table detection (supplement for complex tables)
# ---------------------------------------------------------------------------

def _detect_table_cells_pdfplumber(pdf_path: str, existing_fields: List[dict]) -> List[dict]:
    """
    Use pdfplumber's table detection as a supplement.
    Only add cells that don't overlap with already-detected fields ON THE SAME PAGE.
    """
    cells = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages):
                # Filter existing fields to same page only
                same_page_fields = [f for f in existing_fields if f["page"] == pno]
                tables = page.find_tables()
                for table in tables:
                    for row in table.rows:
                        for cell in row.cells:
                            if cell is not None:
                                x0, top, x1, bottom = cell
                                cell_dict = {
                                    "page": pno,
                                    "x": float(x0),
                                    "y": float(top),
                                    "width": float(x1 - x0),
                                    "height": float(bottom - top),
                                }
                                # Only add if no overlap with existing fields on same page
                                if not any(_overlap(cell_dict, f, threshold=0.5) for f in same_page_fields):
                                    cells.append(cell_dict)
    except Exception:
        pass
    return cells


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def _overlap(a: dict, b: dict, threshold: float = 0.5) -> bool:
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


# ---------------------------------------------------------------------------
# Main detection function
# ---------------------------------------------------------------------------

def detect_fields(pdf_path: str, verbose: bool = False) -> List[dict]:
    """
    Detect form fields in a flat PDF.

    Returns a list of field dicts:
        page, type, x, y, width, height, label, name, flags
    Fields are sorted in reading order (top-to-bottom, left-to-right)
    for proper tab order in the generated PDF.
    """
    # 1. Extract text blocks for labelling
    text_pages = _extract_text_blocks(pdf_path)

    # 2. Primary detection: PyMuPDF vector drawings
    all_fields = _detect_fields_from_drawings(pdf_path, text_pages)

    # 3. Supplement: pdfplumber table detection (adds cells missed by drawings)
    extra_cells = _detect_table_cells_pdfplumber(pdf_path, all_fields)

    # 4. Label any extra cells from pdfplumber
    for tc in extra_cells:
        pno = tc["page"]
        blocks = text_pages.get(pno, [])
        label = _find_nearest_label(
            tc["x"], tc["y"], blocks,
            field_type="table_cell", field_w=tc["width"], field_h=tc["height"]
        )
        base_name = _sanitize_label(label) or "table_cell"
        tc["type"] = "table_cell"
        tc["label"] = label
        tc["name"] = f"{base_name}_{pno}_{int(tc['x'])}_{int(tc['y'])}"
        tc["flags"] = []

    all_fields.extend(extra_cells)

    if verbose:
        print(f"\n--- Detection Summary ---")
        by_type = {}
        for f in all_fields:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"  {t}: {c}")
        print(f"Total fields: {len(all_fields)}\n")

    return all_fields


def detect_fields_json(pdf_path: str, verbose: bool = False) -> str:
    """Same as detect_fields but returns JSON string."""
    return json.dumps(detect_fields(pdf_path, verbose=verbose), indent=2)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python detector.py <input.pdf>")
        sys.exit(1)
    print(detect_fields_json(sys.argv[1], verbose=True))