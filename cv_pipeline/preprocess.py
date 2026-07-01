"""
pdfforge/cv_pipeline/preprocess.py — Data Preprocessing Pipeline (Phase 2)

Prepares training data for the YOLOv8 form field detection model.

Pipeline:
  1. Load PDFs from a dataset directory
  2. For each PDF: extract ground-truth labels from existing AcroForm fields
  3. Rasterize pages to images at specified DPI
  4. Generate YOLO-format label files (class, x_center, y_center, w, h)
  5. Apply data augmentation (rotation, noise, blur, contrast)
  6. Split into train/val/test sets
  7. Write dataset.yaml for YOLOv8 training

Usage:
    python cv_pipeline/preprocess.py --input /path/to/pdfs --output /path/to/dataset
    python cv_pipeline/preprocess.py --input /path/to/pdfs --output /path/to/dataset --augment --dpi 300

Directory structure of output:
    dataset/
      images/
        train/   (augmented + original training images)
        val/     (validation images)
        test/    (test images)
      labels/
        train/   (YOLO-format .txt label files)
        val/
        test/
      dataset.yaml  (YOLOv8 config)
"""

from __future__ import annotations

import argparse
import os
import sys
import json
import random
import logging
from pathlib import Path
from typing import List, Tuple, Optional

import fitz  # PyMuPDF
import cv2
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("pdfforge.preprocess")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# YOLO class mapping
CLASS_MAP = {
    "text": 0,
    "checkbox": 1,
    "radio": 2,
    "table_cell": 3,
    "textarea": 4,
}

CLASS_NAMES = list(CLASS_MAP.keys())

# Default split ratios
DEFAULT_SPLIT = {"train": 0.70, "val": 0.15, "test": 0.15}

# Augmentation defaults
AUGMENT_PER_IMAGE = 3  # Generate 3 augmented versions per original


# ---------------------------------------------------------------------------
# Step 1: Extract ground truth from PDFs with AcroForm fields
# ---------------------------------------------------------------------------

def extract_ground_truth(pdf_path: str) -> List[dict]:
    """
    Extract ground-truth field annotations from a PDF that already has
    AcroForm fields. These will be used as training labels.

    Returns list of: {page, type, x, y, width, height, name}
    """
    doc = fitz.open(pdf_path)
    fields = []

    for pno in range(len(doc)):
        page = doc[pno]
        for widget in page.widgets():
            rect = widget.rect
            wtype = widget.field_type_string.lower()

            # Map PyMuPDF types to our classes
            if "text" in wtype:
                cls = "text"
            elif "checkbox" in wtype:
                cls = "checkbox"
            elif "radio" in wtype:
                cls = "radio"
            else:
                cls = "text"  # default

            # Check for multiline flag (textarea)
            if cls == "text" and widget.field_flags & fitz.PDF_WIDGET_F_MULTILINE:
                cls = "textarea"

            fields.append({
                "page": pno,
                "type": cls,
                "x": rect.x0,
                "y": rect.y0,
                "width": rect.width,
                "height": rect.height,
                "name": widget.field_name or "",
            })

    doc.close()
    return fields


def extract_flat_pdf_fields(pdf_path: str) -> List[dict]:
    """
    For flat PDFs (no AcroForm fields), use our vector detector to
    generate pseudo-ground-truth labels. This is useful when you have
    a collection of flat PDFs and want to bootstrap a training set.

    NOTE: These are NOT true ground truth — they're our detector's
    predictions. Use with caution. Prefer PDFs with real AcroForm fields.
    """
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from detector import detect_fields
    return detect_fields(pdf_path, verbose=False)


# ---------------------------------------------------------------------------
# Step 2: Rasterize PDF pages
# ---------------------------------------------------------------------------

def rasterize_page(pdf_path: str, page_num: int, dpi: int = 200) -> np.ndarray:
    """Rasterize a PDF page to an OpenCV BGR image."""
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    doc.close()

    img_bytes = pix.tobytes("png")
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)


# ---------------------------------------------------------------------------
# Step 3: Generate YOLO-format labels
# ---------------------------------------------------------------------------

def to_yolo_label(fields: List[dict], page_num: int, img_w: int, img_h: int, dpi: int) -> List[str]:
    """
    Convert field annotations to YOLO format for a specific page.
    YOLO format: class_id x_center y_center width height (all normalized 0-1)
    """
    scale = dpi / 72.0  # PDF points -> pixels
    lines = []

    for f in fields:
        if f["page"] != page_num:
            continue

        cls = f["type"]
        if cls not in CLASS_MAP:
            continue

        class_id = CLASS_MAP[cls]

        # Convert PDF coordinates to pixel coordinates
        x_px = f["x"] * scale
        y_px = f["y"] * scale
        w_px = f["width"] * scale
        h_px = f["height"] * scale

        # Convert to YOLO format (normalized center coordinates)
        x_center = (x_px + w_px / 2) / img_w
        y_center = (y_px + h_px / 2) / img_h
        w_norm = w_px / img_w
        h_norm = h_px / img_h

        # Clamp to [0, 1]
        x_center = max(0, min(1, x_center))
        y_center = max(0, min(1, y_center))
        w_norm = max(0, min(1, w_norm))
        h_norm = max(0, min(1, h_norm))

        lines.append(f"{class_id} {x_center:.6f} {y_center:.6f} {w_norm:.6f} {h_norm:.6f}")

    return lines


# ---------------------------------------------------------------------------
# Step 4: Data augmentation
# ---------------------------------------------------------------------------

def augment_image(img: np.ndarray, labels: List[str], num_variations: int = 3) -> List[Tuple[np.ndarray, List[str]]]:
    """
    Generate augmented versions of an image and its labels.
    Augmentations: rotation, noise, blur, contrast adjustment.
    """
    augmented = []

    for i in range(num_variations):
        aug_img = img.copy()
        aug_labels = labels.copy()  # Bounding boxes stay same for these augmentations

        # Random rotation (small angles to preserve field positions)
        angle = random.uniform(-3, 3)
        h, w = aug_img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        aug_img = cv2.warpAffine(aug_img, M, (w, h), borderMode=cv2.BORDER_REFLECT)

        # Random Gaussian noise
        if random.random() < 0.5:
            noise = np.random.normal(0, random.uniform(5, 15), aug_img.shape).astype(np.uint8)
            aug_img = cv2.add(aug_img, noise)

        # Random blur
        if random.random() < 0.3:
            kernel_size = random.choice([3, 5])
            aug_img = cv2.GaussianBlur(aug_img, (kernel_size, kernel_size), 0)

        # Random contrast adjustment
        if random.random() < 0.4:
            alpha = random.uniform(0.8, 1.2)  # Contrast
            beta = random.uniform(-10, 10)    # Brightness
            aug_img = cv2.convertScaleAbs(aug_img, alpha=alpha, beta=beta)

        augmented.append((aug_img, aug_labels))

    return augmented


# ---------------------------------------------------------------------------
# Step 5: Dataset splitting
# ---------------------------------------------------------------------------

def split_dataset(items: list, split: dict = DEFAULT_SPLIT) -> dict:
    """Split items into train/val/test sets."""
    random.shuffle(items)
    n = len(items)
    train_end = int(n * split["train"])
    val_end = train_end + int(n * split["val"])

    return {
        "train": items[:train_end],
        "val": items[train_end:val_end],
        "test": items[val_end:],
    }


# ---------------------------------------------------------------------------
# Step 6: Write dataset.yaml for YOLOv8
# ---------------------------------------------------------------------------

def write_dataset_yaml(output_dir: str, num_classes: int = len(CLASS_NAMES)) -> str:
    """Write the dataset.yaml config file for YOLOv8 training."""
    yaml_path = os.path.join(output_dir, "dataset.yaml")
    content = f"""# PDFForge Form Field Detection Dataset
# Generated by cv_pipeline/preprocess.py

path: {os.path.abspath(output_dir)}
train: images/train
val: images/val
test: images/test

nc: {num_classes}
names: {CLASS_NAMES}
"""
    with open(yaml_path, "w") as f:
        f.write(content)
    return yaml_path


# ---------------------------------------------------------------------------
# Main preprocessing pipeline
# ---------------------------------------------------------------------------

def process_dataset(input_dir: str, output_dir: str, dpi: int = 200,
                    augment: bool = False, augment_count: int = AUGMENT_PER_IMAGE,
                    use_flat_detection: bool = False) -> dict:
    """
    Process a directory of PDFs into a YOLOv8 training dataset.

    Args:
        input_dir: Directory containing PDF files (with AcroForm fields preferred)
        output_dir: Where to write the dataset
        dpi: Rasterization DPI (200 or 300 recommended)
        augment: Enable data augmentation
        augment_count: Number of augmented versions per original image
        use_flat_detection: Use vector detector for flat PDFs (pseudo-labels)

    Returns:
        Stats dict with counts
    """
    # Find all PDFs
    pdf_files = sorted(Path(input_dir).glob("*.pdf"))
    if not pdf_files:
        logger.error(f"No PDF files found in {input_dir}")
        return {"error": "No PDFs found"}

    logger.info(f"Found {len(pdf_files)} PDF files in {input_dir}")

    # Create output directories
    for split in ["train", "val", "test"]:
        os.makedirs(os.path.join(output_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "labels", split), exist_ok=True)

    # Process each PDF
    all_items = []  # (image_path, label_lines, pdf_name, page_num)
    stats = {"pdfs": 0, "pages": 0, "fields": 0, "augmented": 0}

    for pdf_path in pdf_files:
        pdf_name = pdf_path.stem
        logger.info(f"Processing: {pdf_name}")

        # Extract ground truth
        fields = extract_ground_truth(str(pdf_path))

        if not fields and use_flat_detection:
            logger.warning(f"  No AcroForm fields in {pdf_name}, using vector detector for pseudo-labels")
            fields = extract_flat_pdf_fields(str(pdf_path))

        if not fields:
            logger.warning(f"  No fields found in {pdf_name}, skipping")
            continue

        stats["pdfs"] += 1
        stats["fields"] += len(fields)

        # Rasterize each page
        doc = fitz.open(str(pdf_path))
        num_pages = len(doc)
        doc.close()

        for pno in range(num_pages):
            page_fields = [f for f in fields if f["page"] == pno]
            if not page_fields:
                continue

            img = rasterize_page(str(pdf_path), pno, dpi=dpi)
            h, w = img.shape[:2]

            # Generate YOLO labels
            label_lines = to_yolo_label(fields, pno, w, h, dpi)

            if not label_lines:
                continue

            img_name = f"{pdf_name}_p{pno}"
            all_items.append((img, label_lines, img_name))
            stats["pages"] += 1

    # Split into train/val/test
    splits = split_dataset(all_items)

    # Write to disk
    for split_name, items in splits.items():
        for img, labels, name in items:
            img_path = os.path.join(output_dir, "images", split_name, f"{name}.png")
            lbl_path = os.path.join(output_dir, "labels", split_name, f"{name}.txt")

            cv2.imwrite(img_path, img)
            with open(lbl_path, "w") as f:
                f.write("\n".join(labels))

            # Augmentation (train set only)
            if augment and split_name == "train":
                aug_versions = augment_image(img, labels, num_variations=augment_count)
                for i, (aug_img, aug_labels) in enumerate(aug_versions):
                    aug_img_path = os.path.join(output_dir, "images", split_name, f"{name}_aug{i}.png")
                    aug_lbl_path = os.path.join(output_dir, "labels", split_name, f"{name}_aug{i}.txt")
                    cv2.imwrite(aug_img_path, aug_img)
                    with open(aug_lbl_path, "w") as f:
                        f.write("\n".join(aug_labels))
                    stats["augmented"] += 1

    # Write dataset.yaml
    yaml_path = write_dataset_yaml(output_dir)
    logger.info(f"Dataset config written to: {yaml_path}")

    logger.info(f"\n--- Dataset Stats ---")
    logger.info(f"  PDFs processed: {stats['pdfs']}")
    logger.info(f"  Total pages: {stats['pages']}")
    logger.info(f"  Total fields: {stats['fields']}")
    logger.info(f"  Train: {len(splits['train'])} images")
    logger.info(f"  Val: {len(splits['val'])} images")
    logger.info(f"  Test: {len(splits['test'])} images")
    if augment:
        logger.info(f"  Augmented: {stats['augmented']} additional images")
    logger.info(f"  Total images: {len(splits['train']) + len(splits['val']) + len(splits['test']) + stats['augmented']}")

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDFForge Dataset Preprocessing for YOLOv8 Training")
    parser.add_argument("--input", "-i", required=True, help="Directory containing PDF files")
    parser.add_argument("--output", "-o", required=True, help="Output directory for dataset")
    parser.add_argument("--dpi", type=int, default=200, help="Rasterization DPI (default: 200)")
    parser.add_argument("--augment", "-a", action="store_true", help="Enable data augmentation")
    parser.add_argument("--augment-count", type=int, default=3, help="Augmented versions per image (default: 3)")
    parser.add_argument("--flat", action="store_true", help="Use vector detector for flat PDFs (pseudo-labels)")

    args = parser.parse_args()

    stats = process_dataset(
        input_dir=args.input,
        output_dir=args.output,
        dpi=args.dpi,
        augment=args.augment,
        augment_count=args.augment_count,
        use_flat_detection=args.flat,
    )

    print(f"\nDone! Dataset written to: {args.output}")