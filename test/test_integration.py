"""
pdfforge/test/test_integration.py — End-to-end integration test

Sample PDF → detect fields → generate fillable PDF → verify it works.
Also tests the CLI interface via main.main().
"""

import os
import sys
import json

import pytest
import fitz

# Add parent dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test.fixtures import create_sample_pdf


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory):
    """Create sample PDF once."""
    path = tmp_path_factory.mktemp("pdfs") / "sample_form.pdf"
    create_sample_pdf(str(path))
    return str(path)


def test_end_to_end_pipeline(sample_pdf, tmp_path):
    """Full pipeline: detect → generate → verify."""
    from detector import detect_fields
    from generator import generate_fillable_pdf, verify_acroform_fields

    # Step 1: Detect
    fields = detect_fields(sample_pdf)
    assert len(fields) > 0

    # Step 2: Generate
    out_path = str(tmp_path / "e2e_fillable.pdf")
    result_path = generate_fillable_pdf(sample_pdf, fields, output_path=out_path)
    assert result_path == out_path
    assert os.path.isfile(out_path)

    # Step 3: Verify
    info = verify_acroform_fields(out_path)
    assert info["total_fields"] == len(fields)
    assert "Text" in info["types"]


def test_cli_default_output(sample_pdf, tmp_path, monkeypatch):
    """CLI should produce <input>_fillable.pdf by default."""
    from main import main

    # Change to temp dir so default output lands there
    monkeypatch.chdir(tmp_path)
    # Copy sample PDF to temp dir for predictable output name
    import shutil
    temp_pdf = str(tmp_path / "test_form.pdf")
    shutil.copy(sample_pdf, temp_pdf)

    ret = main([temp_pdf])
    assert ret == 0
    expected_out = str(tmp_path / "test_form_fillable.pdf")
    assert os.path.isfile(expected_out), f"Default output not found: {expected_out}"


def test_cli_fields_only(sample_pdf, capsys):
    """CLI --fields-only should print JSON and not create a PDF."""
    from main import main

    ret = main([sample_pdf, "--fields-only"])
    assert ret == 0
    captured = capsys.readouterr()
    # Output should be valid JSON
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert len(data) > 0


def test_cli_custom_output(sample_pdf, tmp_path):
    """CLI --output should use the custom path."""
    from main import main

    out_path = str(tmp_path / "custom_output.pdf")
    ret = main([sample_pdf, "--output", out_path])
    assert ret == 0
    assert os.path.isfile(out_path)


def test_cli_verbose(sample_pdf, capsys):
    """CLI --verbose should print detection summary."""
    from main import main

    ret = main([sample_pdf, "--verbose"])
    assert ret == 0
    captured = capsys.readouterr()
    assert "AcroForm fields:" in captured.out


def test_cli_fields_file(sample_pdf, tmp_path):
    """CLI --fields-file should save JSON to a file."""
    from main import main

    fields_path = str(tmp_path / "schema.json")
    ret = main([sample_pdf, "--fields-file", fields_path, "--output",
                str(tmp_path / "out.pdf")])
    assert ret == 0
    assert os.path.isfile(fields_path)
    with open(fields_path) as f:
        data = json.load(f)
    assert len(data) > 0


def test_cli_nonexistent_file():
    """CLI should return error code for missing input file."""
    from main import main

    ret = main(["/nonexistent/file.pdf"])
    assert ret == 1