"""
pdfforge/test/test_detector.py — Test the field detection engine

Verifies that detector.detect_fields() finds the fields we drew in
the sample fixture PDF.
"""

import os
import sys
import json

import pytest

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import detect_fields
from test.fixtures import create_sample_pdf


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    """Create a sample PDF once for all tests in this module."""
    path = tmp_path_factory.mktemp("pdfs") / "sample_form.pdf"
    create_sample_pdf(str(path))
    return str(path)


def test_detector_returns_list(sample_pdf):
    """Detector should return a list of field dicts."""
    fields = detect_fields(sample_pdf)
    assert isinstance(fields, list)
    assert len(fields) > 0, "Should detect at least one field"


def test_detector_field_structure(sample_pdf):
    """Each field should have all required keys."""
    fields = detect_fields(sample_pdf)
    required_keys = {"page", "type", "x", "y", "width", "height", "label", "name"}
    for f in fields:
        assert required_keys.issubset(f.keys()), f"Missing keys in field: {f}"


def test_detector_finds_text_fields(sample_pdf):
    """Should detect horizontal lines as text fields."""
    fields = detect_fields(sample_pdf)
    text_fields = [f for f in fields if f["type"] == "text"]
    assert len(text_fields) >= 3, (
        f"Expected at least 3 text fields, got {len(text_fields)}"
    )


def test_detector_finds_checkboxes(sample_pdf):
    """Should detect checkbox squares."""
    fields = detect_fields(sample_pdf)
    checkboxes = [f for f in fields if f["type"] == "checkbox"]
    assert len(checkboxes) >= 2, (
        f"Expected at least 2 checkboxes, got {len(checkboxes)}"
    )


def test_detector_field_types_valid(sample_pdf):
    """All field types should be one of the valid types."""
    fields = detect_fields(sample_pdf)
    valid_types = {"text", "checkbox", "table_cell"}
    for f in fields:
        assert f["type"] in valid_types, f"Invalid type: {f['type']}"


def test_detector_field_names_unique(sample_pdf):
    """All field names should be unique."""
    fields = detect_fields(sample_pdf)
    names = [f["name"] for f in fields]
    assert len(names) == len(set(names)), "Duplicate field names found"


def test_detector_field_coordinates_reasonable(sample_pdf):
    """Field coordinates should be within page bounds."""
    fields = detect_fields(sample_pdf)
    page_w, page_h = 612, 792  # US Letter
    for f in fields:
        assert 0 <= f["x"] <= page_w, f"x out of bounds: {f['x']}"
        assert 0 <= f["y"] <= page_h, f"y out of bounds: {f['y']}"
        assert f["width"] > 0, f"width must be positive: {f['width']}"
        assert f["height"] > 0, f"height must be positive: {f['height']}"
        assert f["x"] + f["width"] <= page_w + 5, f"field extends past page width"
        assert f["y"] + f["height"] <= page_h + 5, f"field extends past page height"