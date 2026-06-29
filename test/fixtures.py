"""
pdfforge/test/fixtures.py — Create a sample flat PDF for testing

Draws horizontal lines, checkboxes, and a table on a blank page
using PyMuPDF. No external PDF needed.
"""

import os
import fitz  # PyMuPDF


def create_sample_pdf(output_path: str) -> str:
    """
    Create a sample flat PDF with:
    - 3 horizontal write-in lines with labels
    - 2 checkbox squares with labels
    - A 3x2 table (6 cells) with a header row

    Returns the path to the created PDF.
    """
    doc = fitz.open()  # new empty document
    page = doc.new_page(width=612, height=792)  # US Letter

    # --- Title ---
    page.insert_text((72, 50), "Sample Form — pdfforge Test Fixture",
                     fontsize=16, fontname="helv")

    # --- Section: Text fields (horizontal lines) ---
    page.insert_text((72, 90), "Personal Information",
                     fontsize=12, fontname="helv")

    labels_and_ys = [
        ("First Name:", 120),
        ("Last Name:", 150),
        ("Date of Birth:", 180),
    ]

    for label, y in labels_and_ys:
        # Label text
        page.insert_text((72, y), label, fontsize=10, fontname="helv")
        # Draw a horizontal line to write on (starts after the label)
        label_width = fitz.get_text_length(label, fontname="helv", fontsize=10)
        line_x0 = 72 + label_width + 10
        line_x1 = 400
        page.draw_line(
            fitz.Point(line_x0, y + 2),
            fitz.Point(line_x1, y + 2),
            color=(0, 0, 0),
            width=0.5,
        )

    # --- Section: Checkboxes ---
    page.insert_text((72, 230), "Preferences",
                     fontsize=12, fontname="helv")

    checkbox_labels = [
        ("Subscribe to newsletter", 260),
        ("Agree to terms and conditions", 290),
    ]

    for label, y in checkbox_labels:
        # Label text
        page.insert_text((100, y + 10), label, fontsize=10, fontname="helv")
        # Draw a checkbox square (12x12 pt)
        cb_x, cb_y = 72, y
        cb_size = 12
        page.draw_rect(
            fitz.Rect(cb_x, cb_y, cb_x + cb_size, cb_y + cb_size),
            color=(0, 0, 0),
            width=0.8,
        )

    # --- Section: Table ---
    page.insert_text((72, 340), "Order Details",
                     fontsize=12, fontname="helv")

    # Draw a 3x3 table (header + 2 data rows, 3 columns)
    table_x0, table_y0 = 72, 360
    col_widths = [150, 100, 80]
    row_heights = [25, 25, 25]  # header + 2 rows
    row_count = 3
    col_count = 3

    # Compute cell positions
    for row in range(row_count):
        for col in range(col_count):
            x0 = table_x0 + sum(col_widths[:col])
            y0 = table_y0 + sum(row_heights[:row])
            x1 = x0 + col_widths[col]
            y1 = y0 + row_heights[row]
            page.draw_rect(
                fitz.Rect(x0, y0, x1, y1),
                color=(0, 0, 0),
                width=0.8,
            )

    # Add header text
    headers = ["Item", "Quantity", "Price"]
    for col, header in enumerate(headers):
        x = table_x0 + sum(col_widths[:col]) + 5
        y = table_y0 + 17  # vertically centred-ish
        page.insert_text((x, y), header, fontsize=10, fontname="helv")

    # --- Footer ---
    page.insert_text((72, 480), "Signature:",
                     fontsize=10, fontname="helv")
    # Signature line
    sig_label_width = fitz.get_text_length("Signature:", fontname="helv", fontsize=10)
    page.draw_line(
        fitz.Point(72 + sig_label_width + 10, 482),
        fitz.Point(400, 482),
        color=(0, 0, 0),
        width=0.5,
    )

    doc.save(output_path, deflate=True)
    doc.close()
    return output_path


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "sample_form.pdf")
    create_sample_pdf(out)
    print(f"Created sample PDF: {out}")