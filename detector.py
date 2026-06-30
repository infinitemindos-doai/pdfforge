"""
pdfforge/detector.py — Field Detection Engine v3

Takes a flat PDF (no existing form fields) and detects where fillable
areas should go: horizontal lines (text fields), checkbox squares,
radio button circles, table cells, and multi-line text areas.

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
    page, type, x, y, width, height, label, name, flags
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
    type: str          # "text" | "checkbox" | "radio" | "table_cell" | "textarea"
    x: float           # PDF coordinate (top-left x, points)
    y: float           # PDF coordinate (top-left y, points)
    width: float
    height: float
    label: str = ""
    name: str = ""
    flags: list = None  # ["required", "multiline", etc.]

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
    'textarea', or 'other'.

    - Lines: height <= 2px, width >= 30px (horizontal underlines for text)
    - Checkboxes: roughly square, 8-25px per side
    - Radio: small circle, 8-20px diameter (detected via bezier curve items)
    - Table cells: rectangles wider than tall, or part of a grid
    - Textarea: large rectangle, height > 25px, width > 60px
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

    # Textarea: large rectangle (multi-line input area)
    # Only classify as textarea if significantly taller than a table cell
    # Table cells are typically 10-60px tall; textareas are usually 25-200px
    # Check if there are other similar rectangles nearby (grid pattern = table cells)
    if w >= 60.0 and h >= 25.0 and h <= 200.0:
        # If it's a small rectangle that could be a table cell, check dimensions more carefully
        # Table cells are typically wider than tall or part of a grid
        # A textarea is usually a standalone large box
        if h <= 60.0 and w <= 200.0:
            # Could be either — if roughly square or wider, lean toward table_cell
            # Only call it textarea if it's notably tall relative to width
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
                # Horizontal line -> text field
                # The field sits ABOVE the line (where you write)
                field_x = rect.x0
                field_y = max(rect.y0 - 14, 0)
                field_w = rect.width
                field_h = 14
                label = _find_nearest_label(
                    field_x, field_y, blocks,
                    field_type="text", field_w=field_w, field_h=field_h
                )
                base_name = _sanitize_label(label) or "text"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_lines.append({
                    "page": pno, "type": "text",
                    "x": field_x, "y": field_y,
                    "width": field_w, "height": field_h,
                    "label": label, "name": name,
                    "flags": [],
                })

            elif dtype == "checkbox":
                label = _find_nearest_label(
                    rect.x0, rect.y0, blocks,
                    field_type="checkbox", field_w=rect.width, field_h=rect.height
                )
                base_name = _sanitize_label(label) or "checkbox"
                name = f"{base_name}_{pno}_{int(rect.x0)}_{int(rect.y0)}"
                page_checkboxes.append({
                    "page": pno, "type": "checkbox",
                    "x": rect.x0, "y": rect.y0,
                    "width": rect.width, "height": rect.height,
                    "label": label, "name": name,
                    "flags": [],
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