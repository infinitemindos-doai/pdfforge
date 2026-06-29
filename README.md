# pdfforge — PDF Form Field Generator

Takes a flat PDF (no existing form fields), detects where fillable areas
should go (lines, checkboxes, table cells), and generates a **new PDF with
real embedded AcroForm fillable fields** that work in any PDF reader.

## Quick Start

```bash
# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run on a PDF
python main.py input.pdf

# Output: input_fillable.pdf
```

## Usage

```bash
# Generate fillable PDF (default output: <input>_fillable.pdf)
python main.py form.pdf

# Custom output path
python main.py form.pdf --output custom_fillable.pdf

# Only detect and print field schema as JSON (no PDF generation)
python main.py form.pdf --fields-only

# Save field schema to a JSON file
python main.py form.pdf --fields-file schema.json

# Verbose output (detection + generation summary)
python main.py form.pdf --verbose
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--output, -o PATH` | Custom output PDF path |
| `--fields-only` | Print detected field schema as JSON, don't generate PDF |
| `--fields-file PATH` | Save field schema to a JSON file |
| `--verbose, -v` | Print detailed detection and generation summaries |

## How It Works

### Phase 1: Field Detection (`detector.py`)

1. **pdfplumber** extracts vector lines, rectangles, and detects table structures
2. **OpenCV** rasterizes each page and detects:
   - Horizontal lines → write-in text fields
   - Small square shapes → checkboxes
3. **PyMuPDF** extracts text positions to label each field (finds nearest text above/left)
4. Outputs a JSON schema: page, type, coordinates, dimensions, label, field name

### Phase 2: PDF Generation (`generator.py`)

1. Opens the original PDF with **PyMuPDF**
2. Embeds AcroForm widgets at detected positions:
   - Text fields over write-in lines
   - Checkbox widgets over detected squares
   - Text fields inside table cells
3. Sets field names, tooltips (labels), and font sizes
4. Saves as a new fillable PDF

### Field Types

| Type | Detection Method | AcroForm Widget |
|------|-----------------|-----------------|
| `text` | Horizontal line detection (OpenCV) | Text field |
| `checkbox` | Square shape detection (OpenCV) | Checkbox |
| `table_cell` | Table detection (pdfplumber) | Text field |

## Testing

```bash
source .venv/bin/activate
pytest test/ -v
```

Tests create their own sample PDF fixture (no external PDF needed).

## Project Structure

```
pdfforge/
├── main.py          # CLI interface (argparse)
├── detector.py      # Field detection engine (OpenCV + pdfplumber + PyMuPDF)
├── generator.py     # AcroForm field embedding (PyMuPDF)
├── requirements.txt # Pinned dependencies
├── README.md        # This file
└── test/
    ├── fixtures.py        # Sample PDF generator
    ├── test_detector.py   # Detection tests
    ├── test_generator.py  # Generation tests
    └── test_integration.py # End-to-end tests
```

## Dependencies

- **PyMuPDF** (fitz) — PDF manipulation, text extraction, AcroForm embedding
- **pdfplumber** — Table detection, vector extraction
- **opencv-python** — Rasterized page analysis for line/shape detection
- **pillow** — Image handling (rasterization bridge)
- **pytest** — Test framework

## Limitations

- Detection is heuristic — may miss fields on complex/irregular layouts
- No OCR (text must be extractable from the PDF directly)
- No radio button or dropdown detection (text + checkbox only)
- Coordinates use PDF top-left origin (PyMuPDF convention)