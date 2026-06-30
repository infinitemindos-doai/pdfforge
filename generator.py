"""
pdfforge/generator.py — PDF Form Generation v2

Takes the original flat PDF and a list of detected field dicts (from
detector.py), embeds real AcroForm widgets using PyMuPDF, and writes
a new fillable PDF.

v2 improvements:
  - Field name deduplication (prevents synced-clone bug)
  - try/finally resource management (no file handle leaks)
  - Negative page index check (prevents silent wrap to last page)
  - Field dict validation (clear errors for missing keys)
  - NeedAppearances flag set for PDF viewer compatibility
  - Adaptive checkbox size (uses detected size, not hardcoded)
  - Textarea support (multiline flag)
  - Radio button support
  - Tab order follows detection order (sorted in detector)

Supported field types:
    text         -> Text widget (single-line)
    checkbox     -> CheckBox widget
    radio        -> CheckBox widget (radio group)
    table_cell   -> Text widget sized to the cell
    textarea     -> Text widget with multiline flag

Output file gets a "_fillable" suffix by default.
"""

from __future__ import annotations

import json
import os
import logging
from typing import List, Optional

import fitz  # PyMuPDF

logger = logging.getLogger("pdfforge.generator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_FONT_SIZE = 10       # pt
DEFAULT_TEXT_HEIGHT = 14     # pt
MIN_CHECKBOX_SIZE = 8        # pt
MAX_CHECKBOX_SIZE = 18       # pt


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_field(field: dict, index: int) -> None:
    """Validate a field dict has all required keys with correct types."""
    required = {
        "page": (int,),
        "type": (str,),
        "x": (int, float),
        "y": (int, float),
        "width": (int, float),
        "height": (int, float),
    }
    for key, expected_types in required.items():
        if key not in field:
            raise ValueError(f"Field at index {index} missing required key '{key}'")
        if not isinstance(field[key], expected_types):
            raise ValueError(
                f"Field at index {index}: '{key}' must be {expected_types[0].__name__}, "
                f"got {type(field[key]).__name__}"
            )
    if not isinstance(field["page"], int) or field["page"] < 0:
        raise ValueError(
            f"Field at index {index} has invalid page index {field['page']} (must be non-negative int)"
        )


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

def _add_text_field(page, field: dict, name: str) -> str:
    """Add a text widget to the page using PyMuPDF's Widget API."""
    rect = _make_rect(field)
    # Ensure minimum height for usability
    if rect.height < 10:
        rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + DEFAULT_TEXT_HEIGHT)

    tooltip = field.get("label") or name
    flags = field.get("flags") or []

    widget = fitz.Widget()
    widget.field_name = name
    widget.field_label = tooltip
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.rect = rect
    widget.text_font = "Helv"
    widget.text_fontsize = DEFAULT_FONT_SIZE
    widget.text_color = (0, 0, 0)
    widget.border_color = None
    widget.fill_color = None

    # Set field flags
    if "multiline" in flags:
        widget.field_flags = fitz.PDF_WIDGET_F_MULTILINE

    page.add_widget(widget)
    return name


def _add_checkbox_field(page, field: dict, name: str) -> str:
    """Add a checkbox widget to the page. Size adapts to detected dimensions."""
    rect = _make_rect(field)
    # Use the detected size, clamped to reasonable bounds
    size = max(MIN_CHECKBOX_SIZE, min(MAX_CHECKBOX_SIZE, rect.width, rect.height))
    cx = (rect.x0 + rect.x1) / 2
    cy = (rect.y0 + rect.y1) / 2
    rect = fitz.Rect(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)

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


def _add_radio_field(page, field: dict, name: str) -> str:
    """Add a checkbox widget (radio buttons are checkboxes with the same name)."""
    rect = _make_rect(field)
    size = max(MIN_CHECKBOX_SIZE, min(MAX_CHECKBOX_SIZE, rect.width, rect.height))
    cx = (rect.x0 + rect.x1) / 2
    cy = (rect.y0 + rect.y1) / 2
    rect = fitz.Rect(cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2)

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


def _add_table_cell_field(page, field: dict, name: str) -> str:
    """Add a text widget sized to a table cell."""
    field_copy = dict(field)
    field_copy["type"] = "text"
    return _add_text_field(page, field_copy, name)


def _add_textarea_field(page, field: dict, name: str) -> str:
    """Add a multiline text widget for text areas."""
    field_copy = dict(field)
    if not field_copy.get("flags"):
        field_copy["flags"] = []
    if "multiline" not in field_copy["flags"]:
        field_copy["flags"].append("multiline")
    return _add_text_field(page, field_copy, name)


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
        pdf_path:    Path to the original flat PDF.
        fields:      List of field dicts (from detector.detect_fields).
        output_path: Custom output path. If None, adds '_fillable' suffix.
        verbose:     Print progress information.

    Returns:
        Path to the generated fillable PDF.
    """
    if output_path is None:
        base, ext = os.path.splitext(pdf_path)
        output_path = f"{base}_fillable{ext or '.pdf'}"

    doc = fitz.open(pdf_path)
    try:
        field_counter = 0
        created_fields = []
        seen_names = set()

        for i, field in enumerate(fields):
            # Validate field dict
            try:
                _validate_field(field, i)
            except ValueError as e:
                if verbose:
                    print(f"  WARNING: skipping invalid field at index {i}: {e}")
                logger.warning(f"Skipping invalid field at index {i}: {e}")
                continue

            pno = field["page"]
            # Check page bounds (including negative index — no Python negative wrap)
            if pno < 0 or pno >= len(doc):
                if verbose:
                    print(f"  WARNING: page {pno} out of range, skipping field '{field.get('name')}'")
                logger.warning(f"Page {pno} out of range, skipping field '{field.get('name')}'")
                continue

            page = doc[pno]
            ftype = field["type"]

            # Deduplicate field names — append counter if name already seen
            name = field.get("name") or f"{ftype}_{field_counter}"
            if name in seen_names:
                name = f"{name}_{field_counter}"
            seen_names.add(name)

            if ftype == "text":
                name = _add_text_field(page, field, name)
            elif ftype == "checkbox":
                name = _add_checkbox_field(page, field, name)
            elif ftype == "radio":
                name = _add_radio_field(page, field, name)
            elif ftype == "table_cell":
                name = _add_table_cell_field(page, field, name)
            elif ftype == "textarea":
                name = _add_textarea_field(page, field, name)
            else:
                if verbose:
                    print(f"  WARNING: unknown field type '{ftype}', skipping")
                logger.warning(f"Unknown field type '{ftype}', skipping")
                continue

            created_fields.append({"name": name, "type": ftype, "page": pno})
            field_counter += 1

        # Set NeedAppearances flag for maximum PDF viewer compatibility
        # This tells viewers to regenerate field appearances on open
        try:
            catalog = doc.pdf_catalog()
            if catalog:
                # Try to access the AcroForm and set NeedAppearances
                xref_len = doc.xref_length()
                for xref in range(1, xref_len):
                    obj_str = doc.xref_object(xref, compressed=False)
                    if "/AcroForm" in obj_str:
                        # Found the AcroForm — set NeedAppearances
                        doc.xref_set_key(xref, "NeedAppearances", "true")
                        break
        except Exception as e:
            logger.debug(f"Could not set NeedAppearances: {e}")

        # Save with garbage collection and compression
        doc.save(output_path, deflate=True, garbage=4)

    finally:
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
    try:
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
    finally:
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