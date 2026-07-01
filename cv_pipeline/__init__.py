"""
pdfforge.cv_pipeline — CV/ML pipeline for form field detection (Phase 2)

Modules:
    preprocess  — Data preprocessing and dataset generation for YOLOv8
    train       — YOLOv8 model training
    inference   — Production inference using trained YOLOv8 model

The pipeline works in three stages:
    1. Collect PDFs with fillable fields → preprocess.py → YOLO dataset
    2. Train YOLOv8 on dataset → train.py → best.pt model weights
    3. Use model for inference → inference.py → detected fields

See docs/CV_ML_ROADMAP.md for the full plan.
"""