# pdfforge — Setup Guide for New Users

## What This Is

A tool that takes a flat PDF (a normal PDF with no form fields) and automatically detects where fillable areas should go — lines, checkboxes, table cells — then generates a NEW PDF with real, clickable, typeable form fields that work in any PDF reader (Adobe Acrobat, Preview, browser viewers, etc.).

No manual field drawing required. Drop in a flat PDF, get out a fillable one.

---

## Step 1: Install Python 3

You need Python 3.10 or newer installed on your computer.

### Windows
1. Go to https://www.python.org/downloads/
2. Download the latest Python 3 installer
3. Run the installer — **IMPORTANT: check the box that says "Add Python to PATH"** at the bottom of the installer window
4. Click "Install Now"
5. Verify: open Command Prompt and type `python --version` — you should see `Python 3.x.x`

### Mac
1. Go to https://www.python.org/downloads/
2. Download the latest Python 3 installer for macOS
3. Run the installer (standard Mac install — click through)
4. Verify: open Terminal and type `python3 --version` — you should see `Python 3.x.x`

### Linux
Python 3 is likely already installed. Check with:
```bash
python3 --version
```
If not, install via your package manager:
```bash
# Ubuntu/Debian
sudo apt update && sudo apt install python3 python3-venv python3-pip

# Fedora
sudo dnf install python3 python3-devel
```

---

## Step 2: Install Poppler (Required for PDF Processing)

### Windows
1. Go to https://github.com/oschwartz10612/poppler-windows/releases
2. Download the latest `Release-xx.xx.0-0.zip`
3. Extract it to `C:\poppler`
4. Add `C:\poppler\Library\bin` to your system PATH:
   - Search "Environment Variables" in Windows search
   - Click "Edit the system environment variables"
   - Click "Environment Variables" button
   - Under "System variables" find "Path" → click Edit
   - Click New → type `C:\poppler\Library\bin`
   - Click OK on all windows
5. Verify: open a NEW Command Prompt and type `pdftotext -v` — you should see version info

### Mac
```bash
brew install poppler
```
Verify: `pdftotext -v`

### Linux
```bash
# Ubuntu/Debian
sudo apt install poppler-utils

# Fedora
sudo dnf install poppler-utils
```

---

## Step 3: Set Up pdfforge

1. Unzip the `pdfforge-bundle.tar.gz` (or `pdfforge.zip`) file you received
2. Open Terminal (Mac/Linux) or Command Prompt (Windows)
3. Navigate into the folder:
   ```bash
   cd pdfforge
   ```

4. Create a virtual environment:
   ```bash
   # Mac/Linux
   python3 -m venv .venv
   source .venv/bin/activate

   # Windows
   python -m venv .venv
   .venv\Scripts\activate
   ```

5. Install the dependencies:
   ```bash
   pip install -r requirements.txt
   ```

6. Test it works with the sample:
   ```bash
   python main.py sample_form.pdf --verbose
   ```

   You should see output listing detected fields and a confirmation that `sample_form_fillable.pdf` was created.

7. Open the result:
   ```bash
   # Mac
   open sample_form_fillable.pdf

   # Windows
   start sample_form_fillable.pdf

   # Linux
   xdg-open sample_form_fillable.pdf
   ```

   You should see a PDF with fillable form fields — click into them and type.

---

## Step 4: Use It On Your Own PDFs

```bash
# Make sure your virtual environment is active
# Mac/Linux:  source .venv/bin/activate
# Windows:    .venv\Scripts\activate

# Basic usage — creates yourfile_fillable.pdf
python main.py your_flat_form.pdf

# Custom output name
python main.py your_flat_form.pdf --output my_fillable_form.pdf

# See what fields it detects (without generating a PDF)
python main.py your_flat_form.pdf --fields-only

# Verbose mode — shows detection summary
python main.py your_flat_form.pdf --verbose
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `python: command not found` (Mac/Linux) | Use `python3` instead of `python` |
| `pip: command not found` | Use `pip3` instead, or run `python3 -m pip install -r requirements.txt` |
| `pdftotext not found` | Poppler isn't installed or not on PATH — see Step 2 |
| No fields detected in my PDF | The PDF may be scanned/image-based. pdfforge works best on PDFs with actual vector lines and text. For scanned forms, you'd need OCR first. |
| `ModuleNotFoundError` | Make sure your virtual environment is activated (Step 3, item 4) |

---

## What's Inside

| File | Purpose |
|------|---------|
| `main.py` | CLI entry point — this is what you run |
| `detector.py` | Scans the PDF for lines, checkboxes, and table cells |
| `generator.py` | Embeds real AcroForm fillable fields into the PDF |
| `requirements.txt` | Python dependencies list |
| `README.md` | Technical documentation |
| `sample_form.pdf` | Test PDF to try it out |
| `sample_form_fillable.pdf` | Pre-generated fillable version of the sample |
| `test/` | Automated test suite |

---

## Questions?

This tool is 100% free and open-source. All dependencies are free. No API keys, no subscriptions, no cloud services required. Everything runs locally on your machine.