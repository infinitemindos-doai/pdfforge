"""
pdfforge/test/test_generator.py — Test the PDF form generation

Verifies that generator.generate_fillable_pdf() produces a PDF with
real AcroForm fields.
"""

import os
import sys

import pytest
import fitz

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from detector import detect_fields
from generator import generate_fillable_pdf, verify_acroform_fields
from test.fixtures import create_sample_pdf


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    """Create sample PDF once."""
    path = tmp_path_factory.mktemp("pdfs") / "sample_form.pdf"
    create_sample_pdf(str(path))
    return str(path)


@pytest.fixture(scope="module")
def fillable_pdf(sample_pdf, tmp_path_factory):
    """Generate a fillable PDF once for all tests."""
    fields = detect_fields(sample_pdf)
    out_dir = tmp_path_factory.mktemp("output")
    out_path = str(out_dir / "sample_fillable.pdf")
    generate_fillable_pdf(sample_pdf, fields, output_path=out_path)
    return out_path


def test_generator_creates_file(fillable_pdf):
    """Output PDF file should exist."""
    assert os.path.isfile(fillable_pdf), "Output PDF file not created"
    assert os.path.getsize(fillable_pdf) > 0, "Output PDF is empty"


def test_generator_pdf_is_valid(fillable_pdf):
    """Output should be a valid PDF that PyMuPDF can open."""
    doc = fitz.open(fillable_pdf)
    assert len(doc) > 0, "PDF has no pages"
    doc.close()


def test_generator_has_acroform_fields(fillable_pdf):
    """Output PDF should contain AcroForm field widgets."""
    info = verify_acroform_fields(fillable_pdf)
    assert info["total_fields"] > 0, "No AcroForm fields found in output PDF"


def test_generator_field_count_matches(sample_pdf, fillable_pdf):
    """Number of AcroForm fields should match detected fields."""
    fields = detect_fields(sample_pdf)
    info = verify_acroform_fields(fillable_pdf)
    assert info["total_fields"] == len(fields), (
        f"Expected {len(fields)} fields, got {info['total_fields']}"
    )


def test_generator_has_text_fields(fillable_pdf):
    """Output should have text-type AcroForm fields."""
    info = verify_acroform_fields(fillable_pdf)
    assert "Text" in info["types"], f"No Text fields found. Types: {info['types']}"
    assert info["types"]["Text"] >= 3, (
        f"Expected at least 3 Text fields, got {info['types'].get('Text', 0)}"
    )


def test_generator_has_checkbox_fields(fillable_pdf):
    """Output should have checkbox-type AcroForm fields."""
    info = verify_acroform_fields(fillable_pdf)
    # PyMuPDF reports checkbox as "CheckBox"
    cb_count = info["types"].get("CheckBox", 0)
    assert cb_count >= 2, f"Expected at least 2 CheckBox fields, got {cb_count}"


def test_generator_field_names_present(fillable_pdf):
    """All AcroForm fields should have names."""
    info = verify_acroform_fields(fillable_pdf)
    named = [n for n in info["names"] if n]
    assert len(named) == info["total_fields"], "Some fields are missing names"