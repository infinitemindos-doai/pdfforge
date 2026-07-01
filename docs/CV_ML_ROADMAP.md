# PDFForge — CV/ML Enhancement Roadmap

## Status: Phase 2 Proposal (not yet started)

## Background

Feedback from Anthony's contact identified that PDF form field detection is
fundamentally a Computer Vision problem. This is partially correct:

### What our current system does (Phase 1 — COMPLETE)

Our detector v3 uses **PyMuPDF's vector drawing extraction** — it reads the
PDF's internal content stream directly and gets exact coordinates for:
- Horizontal lines → text fields
- Small squares → checkboxes
- Small circles (bezier curves) → radio buttons
- Rectangles → table cells
- Large rectangles → text areas

**This approach is MORE accurate than CV for digital-native PDFs** because:
1. No pixel-level guessing — coordinates come from the PDF spec itself
2. No training data needed — the detector works on any digital PDF
3. No model drift or retraining — deterministic detection
4. Instant execution — no neural network inference

### What our current system CANNOT do (Phase 2 — PROPOSED)

**Scanned PDFs** (photos of paper forms, or PDFs that are just images) have
zero vector drawings. Our detector returns 0 fields. This is where a CV/ML
model trained on real PDF forms would be needed.

## The Contact's Proposal (Correct)

1. **Acquire 100-10,000 real PDFs** with fillable fields — for training data
2. **Add a Computer Vision Engineer** to the CrewAI team
3. **Preprocessing pipeline** — training data (blank vs filled), test data
4. **Update QA Tester** with its own test dataset
5. **Data augmentation** to reduce volume needed

## Key Constraint (Contact is Right)

AI cannot create the training data. If it could, the project wouldn't be
needed. The PDFs must be found/acquired from real sources.

## Implementation Plan (When We're Ready)

### Step 1: Data Acquisition
- Source real PDF forms with existing AcroForm fields
- Sources: IRS tax forms, government forms, enterprise onboarding forms
- Target: 100 PDFs minimum (with augmentation), 1000+ ideal
- Split: 70% training, 15% validation, 15% test

### Step 2: Preprocessing Pipeline
- For each PDF: extract blank version (no field values) and filled version
- Rasterize to images at 150-300 DPI
- Generate ground-truth labels from existing AcroForm field positions
- Data augmentation: rotation, noise, blur, contrast variation

### Step 3: CV Model Training
- Architecture: YOLOv8 or similar object detection model
- Input: rasterized PDF page images
- Output: bounding boxes with field type classification
- Train on augmented dataset
- Evaluate on held-out test set

### Step 4: Integration with Current System
- Add CV model as **fallback** when vector extraction returns 0 fields
- Detection pipeline: vector extraction first → CV fallback if empty
- CV results get lower confidence flag in API response

### Step 5: CrewAI Enhancement
- Add **Computer Vision Engineer** agent to crew.py
- Role: Train, evaluate, and maintain the CV detection model
- Tools: dataset loading, model training, evaluation metrics
- QA Tester gets dedicated test PDFs for CV pipeline validation

### Step 6: Production Deployment
- CV model runs as separate microservice (GPU optional, CPU sufficient)
- Model packaged as ONNX for cross-platform inference
- Fallback trigger: vector extraction returns 0 fields on a page
- Latency budget: CV inference < 2 seconds per page

## What We Have NOW (Phase 1 — Shipped)

- Detector v3: vector extraction with radio, textarea, tab order
- Generator v2: AcroForm widgets with name dedup, NeedAppearances
- API v1.2.0: production-hardened with security headers, rate limiting
- Frontend: DPR-correct field overlays, zoom controls, 5 field types
- CrewAI: 5-agent team (Backend, Frontend, QA, Network, Senior Dev)
- Deployed: GitHub Pages frontend + Cloudflare Tunnel backend
- Tested: 15/15 fields detected, 0 false positives, HTTP 200 generation

## What We Need for Phase 2

- 100+ real PDF forms with fillable fields (training data)
- Computer Vision Engineer role added to CrewAI
- OpenCV/YOLOv8 training pipeline
- Data augmentation toolkit
- ONNX model packaging for production inference
- Estimated effort: 2-4 weeks of focused development

## Contact's Core Insight (Validated)

The contact correctly identified that:
1. The problem has a CV component (for scanned PDFs)
2. Training data must be found, not generated
3. Data augmentation reduces volume but doesn't eliminate the need
4. A CV Engineer role in the team makes sense

Our current vector-extraction approach handles the digital-native PDF
case perfectly. The CV/ML approach is the right solution for the scanned
PDF case, which we currently can't handle at all.