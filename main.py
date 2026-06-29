#!/usr/bin/env python3
"""
pdfforge/main.py — Phase 3: CLI Interface

Usage:
    python main.py <input.pdf>                         → outputs <input>_fillable.pdf
    python main.py <input.pdf> --fields-only           → outputs detected field schema as JSON
    python main.py <input.pdf> --output <custom.pdf>   → custom output path
    python main.py <input.pdf> --verbose               → prints detection summary
    python main.py <input.pdf> --fields-file <f.json>  → save fields JSON to file
"""

import argparse
import json
import os
import sys

# Ensure we can import sibling modules regardless of CWD
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detector import detect_fields, detect_fields_json
from generator import generate_fillable_pdf, verify_acroform_fields


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfforge",
        description="PDF Form Field Generator — detect fillable areas in a flat PDF "
                    "and generate a new PDF with embedded AcroForm fields.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py form.pdf\n"
            "  python main.py form.pdf --verbose\n"
            "  python main.py form.pdf --fields-only\n"
            "  python main.py form.pdf --output custom_fillable.pdf\n"
            "  python main.py form.pdf --fields-file schema.json\n"
        ),
    )
    parser.add_argument(
        "input_pdf",
        help="Path to the input flat PDF file.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Custom output PDF path (default: <input>_fillable.pdf).",
    )
    parser.add_argument(
        "--fields-only",
        action="store_true",
        help="Only detect and print the field schema as JSON. Do not generate a PDF.",
    )
    parser.add_argument(
        "--fields-file",
        default=None,
        help="Save detected field schema to this JSON file (in addition to stdout).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed detection and generation summaries.",
    )
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Validate input file
    if not os.path.isfile(args.input_pdf):
        print(f"Error: input file not found: {args.input_pdf}", file=sys.stderr)
        return 1

    if not args.input_pdf.lower().endswith(".pdf"):
        print(f"Warning: file does not have .pdf extension: {args.input_pdf}",
              file=sys.stderr)

    # Phase 1: Detect fields
    if args.verbose:
        print(f"Analyzing: {args.input_pdf}")
    fields = detect_fields(args.input_pdf, verbose=args.verbose)

    # --fields-only: print JSON and exit
    if args.fields_only:
        fields_json = json.dumps(fields, indent=2)
        print(fields_json)
        if args.fields_file:
            with open(args.fields_file, "w") as f:
                f.write(fields_json)
            if args.verbose:
                print(f"Field schema saved to: {args.fields_file}")
        return 0

    # Save fields to file if requested
    if args.fields_file:
        with open(args.fields_file, "w") as f:
            json.dump(fields, f, indent=2)
        if args.verbose:
            print(f"Field schema saved to: {args.fields_file}")

    # Phase 2: Generate fillable PDF
    output_path = generate_fillable_pdf(
        args.input_pdf,
        fields,
        output_path=args.output,
        verbose=args.verbose,
    )

    # Verification
    info = verify_acroform_fields(output_path)
    if args.verbose or True:  # Always show basic verification
        print(f"\n✅ Output: {output_path}")
        print(f"   AcroForm fields: {info['total_fields']}")
        if info["types"]:
            types_str = ", ".join(f"{t}: {c}" for t, c in sorted(info["types"].items()))
            print(f"   Types: {types_str}")

    if info["total_fields"] == 0:
        print("   ⚠️  No AcroForm fields were embedded — check the input PDF.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())