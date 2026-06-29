"""
pdfforge/generator.py — Phase 2: PDF Form Generation

Takes the original flat PDF and a list of detected field dicts (from
detector.py), embeds real AcroForm widgets using PyMuPDF, and writes
a new fillable PDF.

Supported field types:
    text         → Text widget (single-line)
    checkbox     → CheckBox widget
    table_cell   → Text widget sized to the cell

Output file gets a "_fillable" suffix by default.
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FONT_SIZE = 10       # pt
DEFAULT_TEXT_HEIGHT = 14     # pt
CHECKBOX_SIZE = 10           # pt


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _make_rect(field: dict) -> fitz.Rect:
    """Build a PyMuPDF Rect from a field dict (PDF top-left coords)."""
    x = field["x"]
    y = field["y"]
    w = field["width"]
    h = field["height"]
    return fitz.Rect(x, y, x + w, y + h)


# ---------------------------------------------------------------------------
# Field insertion via Widget API
# ---------------------------------------------------------------------------

def _add_text_field(page, field: dict, field_counter: int) -> str:
    """
    Add a text widget to the page using PyMuPDF's Widget API.
    Returns the internal field name used.
    """
    rect = _make_rect(field)
    # Ensure minimum height for usability
    if rect.height < 10:
        rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + DEFAULT_TEXT_HEIGHT)

    name = field.get("name") or f"text_field_{field_counter}"
    tooltip = field.get("label") or name

    widget = fitz.Widget()
    widget.field_name = name
    widget.field_label = tooltip       # tooltip / alternate text
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = rect
    widget.text_font = "Helv"
    widget.text_fontsize = DEFAULT_FONT_SIZE
    widget.text_color = (0, 0, 0)
    widget.border_color = None         # invisible border
    widget.fill_color = None           # no background

    page.add_widget(widget)
    return name


def _add_checkbox_field(page, field: dict, field_counter: int) -> str:
    """
    Add a checkbox widget to the page using PyMuPDF's Widget API.
    Returns the internal field name used.
    """
    rect = _make_rect(field)
    # Normalise checkbox to a square
    size = CHECKBOX_SIZE
    cx = (rect.x0 + rect.x1) / 2
    cy = (rect.y0 + rect.y1) / 2
    rect = fitz.Rect(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)

    name = field.get("name") or f"checkbox_{field_counter}"
    tooltip = field.get("label") or name

    widget = fitz.Widget()
    widget.field_name = name
    widget.field_label = tooltip
    widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    widget.rect = rect
    widget.border_color = None
    widget.fill_color = None

    page.add_widget(widget)
    return name


def _add_table_cell_field(page, field: dict, field_counter: int) -> str:
    """
    Add a text widget sized to a table cell.
    Returns the internal field name used.
    """
    field_copy = dict(field)
    field_copy["type"] = "text"
    return _add_text_field(page, field_copy, field_counter)


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

def generate_fillable_pdf(
    pdf_path: str,
    fields: List[dict],
    output_path: Optional[str] = None,
    verbose: bool = False,
) -> str:
    """
    Generate a fillable PDF from a flat PDF and a field schema.

    Args:
        pdf_path:   Path to the original flat PDF.
        fields:     List of field dicts (from detector.detect_fields).
        output_path: Custom output path. If None, adds '_fillable' suffix.
        verbose:    Print progress information.

    Returns:
        Path to the generated fillable PDF.
    """
    if output_path is None:
        base, ext = os.path.splitext(pdf_path)
        output_path = f"{base}_fillable{ext or '.pdf'}"

    doc = fitz.open(pdf_path)

    field_counter = 0
    created_fields = []

    for field in fields:
        pno = field["page"]
        if pno >= len(doc):
            if verbose:
                print(f"  WARNING: page {pno} out of range, skipping field '{field.get('name')}'")
            continue

        page = doc[pno]
        ftype = field["type"]

        if ftype == "text":
            name = _add_text_field(page, field, field_counter)
        elif ftype == "checkbox":
            name = _add_checkbox_field(page, field, field_counter)
        elif ftype == "table_cell":
            name = _add_table_cell_field(page, field, field_counter)
        else:
            if verbose:
                print(f"  WARNING: unknown field type '{ftype}', skipping")
            continue

        created_fields.append({"name": name, "type": ftype, "page": pno})
        field_counter += 1

    # Save with garbage collection and compression
    doc.save(output_path, deflate=True, garbage=4)
    doc.close()

    if verbose:
        print(f"\n--- Generation Summary ---")
        print(f"Input:  {pdf_path}")
        print(f"Output: {output_path}")
        by_type = {}
        for f in created_fields:
            by_type[f["type"]] = by_type.get(f["type"], 0) + 1
        for t, c in sorted(by_type.items()):
            print(f"  {t}: {c}")
        print(f"Total AcroForm fields created: {len(created_fields)}\n")

    return output_path


def generate_fillable_pdf_from_json(
    pdf_path: str,
    fields_json_path: str,
    output_path: Optional[str] = None,
    verbose: bool = False,
) -> str:
    """Generate fillable PDF from a JSON field schema file."""
    with open(fields_json_path, "r") as f:
        fields = json.load(f)
    return generate_fillable_pdf(pdf_path, fields, output_path, verbose)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_acroform_fields(pdf_path: str) -> dict:
    """
    Verify that a PDF contains real AcroForm fields.
    Returns dict with count and details.
    """
    doc = fitz.open(pdf_path)
    total_widgets = 0
    field_types = {}
    field_names = []

    for pno in range(len(doc)):
        page = doc[pno]
        for widget in page.widgets():
            total_widgets += 1
            wtype = widget.field_type_string
            field_types[wtype] = field_types.get(wtype, 0) + 1
            if widget.field_name:
                field_names.append(widget.field_name)

    doc.close()
    return {
        "total_fields": total_widgets,
        "types": field_types,
        "names": field_names,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python generator.py <input.pdf> <fields.json> [output.pdf]")
        sys.exit(1)
    out = generate_fillable_pdf_from_json(sys.argv[1], sys.argv[2],
                                          sys.argv[3] if len(sys.argv) > 3 else None,
                                          verbose=True)
    info = verify_acroform_fields(out)
    print(f"Verification: {info}")