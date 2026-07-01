"""
pdfforge/cv_pipeline/train.py — YOLOv8 Training Script (Phase 2)

Trains a YOLOv8 object detection model on the preprocessed dataset
from preprocess.py.

Usage:
    python cv_pipeline/train.py --dataset /path/to/dataset --epochs 100
    python cv_pipeline/train.py --dataset /path/to/dataset --epochs 50 --imgsz 640 --batch 16

Requirements:
    pip install ultralytics

Output:
    - Trained model weights in runs/detect/trainX/weights/best.pt
    - Training metrics and validation results
"""

from __future__ import annotations

import argparse
import os
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("pdfforge.train")


def train_yolo(
    dataset_yaml: str,
    epochs: int = 100,
    imgsz: int = 640,
    batch: int = 16,
    model: str = "yolov8n.pt",
    device: str = "cpu",
    project: str = "runs/detect",
    name: str = "pdfforge_fields",
) -> str:
    """
    Train a YOLOv8 model on the pdfforge dataset.

    Args:
        dataset_yaml: Path to dataset.yaml from preprocess.py
        epochs: Number of training epochs
        imgsz: Image size for training (640 recommended)
        batch: Batch size
        model: Base model to fine-tune (yolov8n.pt = nano, yolov8s.pt = small)
        device: 'cpu' or '0' for GPU
        project: Output project directory
        name: Run name

    Returns:
        Path to the trained model weights
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("ultralytics not installed. Run: pip install ultralytics")
        sys.exit(1)

    # Load base model
    yolo_model = YOLO(model)
    logger.info(f"Loaded base model: {model}")

    # Train
    logger.info(f"Starting training: {epochs} epochs, imgsz={imgsz}, batch={batch}, device={device}")
    results = yolo_model.train(
        data=dataset_yaml,
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        project=project,
        name=name,
        verbose=True,
    )

    # Find best weights
    weights_path = os.path.join(project, name, "weights", "best.pt")
    if not os.path.exists(weights_path):
        # Try to find in runs/detect/trainX/weights/best.pt
        runs_dir = Path(project)
        if runs_dir.exists():
            train_dirs = sorted(runs_dir.glob("train*"))
            if train_dirs:
                weights_path = str(train_dirs[-1] / "weights" / "best.pt")

    if os.path.exists(weights_path):
        logger.info(f"Training complete! Best weights: {weights_path}")
    else:
        logger.warning("Training complete but best.pt not found. Check runs/ directory.")

    return weights_path


def evaluate_model(weights_path: str, dataset_yaml: str) -> dict:
    """
    Evaluate the trained model on the test set.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("ultralytics not installed")
        return {"error": "ultralytics not installed"}

    model = YOLO(weights_path)
    metrics = model.val(data=dataset_yaml, split="test")

    return {
        "mAP50": float(metrics.box.map50),
        "mAP50-95": float(metrics.box.map),
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
    }


def export_onnx(weights_path: str) -> str:
    """
    Export trained model to ONNX format for production inference.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        logger.error("ultralytics not installed")
        return ""

    model = YOLO(weights_path)
    onnx_path = model.export(format="onnx")
    logger.info(f"ONNX model exported: {onnx_path}")
    return str(onnx_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PDFForge YOLOv8 Training")
    parser.add_argument("--dataset", "-d", required=True, help="Path to dataset.yaml")
    parser.add_argument("--epochs", "-e", type=int, default=100, help="Training epochs (default: 100)")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size (default: 640)")
    parser.add_argument("--batch", "-b", type=int, default=16, help="Batch size (default: 16)")
    parser.add_argument("--model", "-m", default="yolov8n.pt", help="Base model (default: yolov8n.pt)")
    parser.add_argument("--device", default="cpu", help="Device: 'cpu' or '0' for GPU (default: cpu)")
    parser.add_argument("--name", default="pdfforge_fields", help="Run name")
    parser.add_argument("--export-onnx", action="store_true", help="Export to ONNX after training")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate on test set after training")

    args = parser.parse_args()

    # Train
    weights = train_yolo(
        dataset_yaml=args.dataset,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        model=args.model,
        device=args.device,
        name=args.name,
    )

    # Evaluate
    if args.evaluate:
        logger.info("Evaluating model on test set...")
        metrics = evaluate_model(weights, args.dataset)
        logger.info(f"Test metrics: {metrics}")

    # Export
    if args.export_onnx:
        onnx_path = export_onnx(weights)
        if onnx_path:
            logger.info(f"ONNX model ready for production: {onnx_path}")