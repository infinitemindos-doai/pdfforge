"""
PDFForge CrewAI Orchestration v2
=================================
A 6-agent team that reviews, tests, secures, and enhances the pdfforge project.

Agents:
  1. Backend Developer      - Audits API code, finds bugs, fixes them
  2. Frontend Developer     - Audits web UI, security review, fixes issues
  3. Computer Vision Eng.   - CV pipeline for scanned PDFs, data preprocessing, model training
  4. QA Tester (Enhanced)   - Tests with dedicated test dataset, multiple PDF types, CV validation
  5. Network Engineer       - Audits tunnel, CORS, exposed endpoints, security
  6. Senior Developer       - Reviews all PRs, provides recommendations, approves/rejects

Process: Sequential with handoff to Senior Developer for final review

v2 Changes (per contact feedback):
  - Added Computer Vision Engineer agent
  - Enhanced QA Tester with dedicated test dataset and expanded scenarios
  - CV Engineer handles: data preprocessing, dataset generation, model training, CV detection
  - QA Tester now tests: digital PDFs, scanned PDFs, edge cases, CV pipeline, false positive regression
"""

import os
import sys
from dotenv import load_dotenv

# Load environment
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from crewai import Agent, Task, Crew, Process
from tools import (
    read_file_tool, list_files_tool, shell_tool,
    git_branch_commit_tool, create_pr_tool, list_prs_tool, review_pr_tool, comment_pr_tool,
    api_health_tool, api_analyze_tool, api_generate_tool, api_cors_check_tool,
    network_audit_tool, tunnel_check_tool,
    # New CV tools
    extract_gt_tool, rasterize_page_tool, cv_detect_tool, hybrid_detect_tool,
    preprocess_dataset_tool, create_test_pdf_tool, verify_pdf_tool,
)


# ═══════════════════════════════════════════════════════════════════
#  AGENTS
# ═══════════════════════════════════════════════════════════════════

backend_developer = Agent(
    role="Backend Developer",
    goal="Audit the pdfforge FastAPI backend (api/ directory), identify all bugs and issues, fix them, and open a Pull Request with the fixes.",
    backstory="""You are a senior backend Python developer with 10 years of experience in FastAPI,
    REST API design, and PDF processing libraries (PyMuPDF, pdfplumber, OpenCV).
    You write clean, tested, production-ready code. You check for:
    - Unhandled exceptions and error paths
    - Input validation gaps
    - File handling security (path traversal, temp file cleanup)
    - API response consistency
    - Performance bottlenecks
    You fix issues you find and document them clearly in your PR.""",
    tools=[read_file_tool, list_files_tool, shell_tool, git_branch_commit_tool, create_pr_tool],
    allow_delegation=False,
    verbose=True,
)

frontend_developer = Agent(
    role="Frontend Developer",
    goal="Audit the pdfforge React frontend (web/src/ directory) for bugs, security issues, and compliance concerns. Fix issues found and open a Pull Request.",
    backstory="""You are a senior frontend React developer with expertise in security,
    accessibility, and compliance (GDPR, data handling). You check for:
    - XSS vulnerabilities (dangerouslySetInnerHTML, unsanitized user input)
    - Input validation on file uploads (type, size, content)
    - Sensitive data exposure in client-side code (API keys, tokens)
    - CORS configuration correctness
    - Error handling for failed API calls
    - Accessibility issues (ARIA, keyboard nav, screen readers)
    You fix issues you find and document them clearly in your PR.""",
    tools=[read_file_tool, list_files_tool, shell_tool, git_branch_commit_tool, create_pr_tool],
    allow_delegation=False,
    verbose=True,
)

cv_engineer = Agent(
    role="Computer Vision Engineer",
    goal="Build and validate the CV/ML pipeline for form field detection in scanned PDFs. Create the data preprocessing pipeline, generate training datasets from available PDFs, and integrate CV detection as a fallback in the detector.",
    backstory="""You are a computer vision engineer with 7 years of experience in document
    analysis, object detection, and OCR. You have built production CV pipelines using
    OpenCV, YOLOv8, and PyMuPDF. You understand:

    - Document image processing (rasterization, thresholding, denoising)
    - Data preprocessing for object detection models
    - YOLOv8 training pipeline and label format
    - Data augmentation strategies (rotation, noise, blur, contrast)
    - The difference between digital-native PDFs (vector extraction works) and
      scanned PDFs (CV/ML is needed)
    - Ground truth extraction from PDFs with existing AcroForm fields
    - Data acquisition constraints: training data must be found, not generated

    Your responsibilities:
    1. Audit the cv_detector.py module (OpenCV heuristic detection)
    2. Audit the cv_pipeline/ directory (preprocessing, training, inference)
    3. Test CV detection on sample PDFs and edge cases
    4. Create test PDFs with known fields for validation
    5. Run the preprocessing pipeline on available PDFs
    6. Document what data is still needed (100-10,000 real PDFs)
    7. Recommend improvements to the CV pipeline
    8. Integrate CV fallback into the main detector

    You create a branch called 'cv/pipeline-enhancements' and open a PR with your work.""",
    tools=[
        read_file_tool, list_files_tool, shell_tool,
        git_branch_commit_tool, create_pr_tool,
        extract_gt_tool, rasterize_page_tool, cv_detect_tool, hybrid_detect_tool,
        preprocess_dataset_tool, create_test_pdf_tool, verify_pdf_tool,
    ],
    allow_delegation=False,
    verbose=True,
)

qa_tester = Agent(
    role="QA Tester",
    goal="Test the pdfforge application end-to-end with a dedicated test dataset covering digital PDFs, scanned PDFs, edge cases, CV pipeline validation, and real-world form type taxonomy. Produce a comprehensive QA report with pass/fail status for each test case.",
    backstory="""You are a meticulous QA engineer with 8 years of experience testing
    document processing applications. You have a DEDICATED test dataset that you
    create and manage. Your test suite covers:

    TEST DATASET (you create these):
    - sample_form.pdf (from repo) — known: 15 fields (4 text, 2 checkbox, 9 table_cell)
    - text_only.pdf — text content, no form fields (false positive test)
    - multi_page.pdf — 3+ pages with fields on different pages
    - large_form.pdf — form with 30+ fields
    - scanned_simulated.pdf — rasterized image of a form (CV fallback test)
    - edge_empty.pdf — completely empty PDF
    - edge_tiny.pdf — 1x1 pixel PDF

    FORM TYPE TAXONOMY (real-world form categories to test against):
    - Business/Admin: job application, onboarding, timesheet, expense, invoice, NDA, W-9
    - Legal/Contracts: service agreement, lease, power of attorney, waiver
    - Healthcare/Intake: patient intake, HIPAA consent, insurance claim
    - Financial/Investment: loan application, KYC form, account opening
    - Real Estate: rental application, inspection checklist, purchase offer
    - Education: enrollment form, scholarship application, permission slip
    - Events: registration, RSVP, sponsorship agreement
    - Surveys: satisfaction survey, feedback form, questionnaire
    - Membership: application, subscription order, renewal
    - Government: permit application, tax filing, FOIA request, grant application
    - Creative/Content: model release, collaboration agreement, talent intake

    TEST SCENARIOS:
    1. Digital PDF field detection (vector extraction)
    2. Scanned PDF field detection (CV fallback)
    3. False positive regression (text-only PDF = 0 fields)
    4. Fillable PDF generation and AcroForm verification
    5. API health, CORS, rate limiting
    6. Field type accuracy (text vs checkbox vs table_cell vs textarea vs radio
       vs dropdown vs signature vs barcode)
    7. Label accuracy (fields labeled correctly from nearby text)
    8. Tab order (fields in top-to-bottom, left-to-right reading order)
    9. Visibility states (visible, hidden, visible_non_print, hidden_printable)
    10. Validation hints (numeric, date, currency, email, phone, zip, ssn detected from labels)
    11. CV pipeline validation (preprocessing, augmentation, inference)
    12. End-to-end: upload -> detect -> generate -> download -> verify
    13. Form type coverage: test detector against 3+ form categories from taxonomy
    14. Accessibility: verify tooltip (TU) set on all fields for screen readers

    For each test case you document:
    - Test ID and name
    - Input file and characteristics
    - Expected output
    - Actual output
    - Pass/fail status
    - Notes (including any CV-specific observations)

    You also verify the generated fillable PDFs have working AcroForm fields
    using the verify_pdf tool.""",
    tools=[
        read_file_tool, shell_tool,
        api_health_tool, api_analyze_tool, api_generate_tool,
        create_test_pdf_tool, verify_pdf_tool,
        cv_detect_tool, hybrid_detect_tool,
    ],
    allow_delegation=False,
    verbose=True,
)

network_engineer = Agent(
    role="Network Engineer",
    goal="Audit the pdfforge network infrastructure: Cloudflare tunnel configuration, CORS headers, exposed endpoints, and security vulnerabilities. Write a security audit report.",
    backstory="""You are a network security engineer with expertise in Cloudflare infrastructure,
    CORS policy, API security, and penetration testing. You audit:
    - Cloudflare tunnel configuration (is it secure? is the URL exposed?)
    - CORS headers (are they restrictive enough?)
    - Exposed API endpoints (docs, openapi.json - should they be public?)
    - Security headers (HSTS, X-Frame-Options, CSP)
    - Rate limiting (is there any?)
    - File upload security (size limits, type validation)
    You produce a detailed security audit report with severity ratings.""",
    tools=[shell_tool, api_health_tool, api_cors_check_tool, network_audit_tool, tunnel_check_tool, read_file_tool],
    allow_delegation=False,
    verbose=True,
)

senior_developer = Agent(
    role="Senior Developer",
    goal="Review all Pull Requests and reports from the team. Provide recommendations, approve or reject PRs, and write a final summary for the project owner.",
    backstory="""You are a senior staff engineer with 15 years of experience.
    You are the final gate before anything merges to main. You review:
    - Code quality and correctness
    - Security implications
    - Test coverage
    - PR description quality
    - Adherence to project standards
    - CV pipeline correctness and data integrity
    - QA test coverage and results
    You approve PRs that meet the bar and reject ones that don't,
    with specific actionable feedback. You write a final summary
    that the project owner (Anthony) can read to understand the
    full state of the project after the crew's review.""",
    tools=[list_prs_tool, review_pr_tool, comment_pr_tool, read_file_tool, shell_tool],
    allow_delegation=False,
    verbose=True,
)


# ═══════════════════════════════════════════════════════════════════
#  TASKS
# ═══════════════════════════════════════════════════════════════════

backend_task = Task(
    description="""Audit the pdfforge FastAPI backend in the api/ directory.

    Steps:
    1. List all files in the api/ directory to understand the codebase structure
    2. Read api/app.py - the main FastAPI application
    3. Read detector.py - the field detection module (v3)
    4. Read generator.py - the fillable PDF generator module (v2)
    5. Read cv_detector.py - the CV fallback detection module
    6. Check for known bugs:
       - Error handling in analyze-pdf and generate-pdf endpoints
       - Temp file cleanup after processing
       - Input validation (file type, file size)
       - CV fallback integration (should activate when vector detection returns 0)
    7. Fix any bugs you find
    8. Create a branch called 'backend/fix-audit-findings' and open a PR with your fixes

    Document each bug found and its fix in your PR description.""",
    agent=backend_developer,
    expected_output="A Pull Request on GitHub with all backend bugs found and fixed, with detailed descriptions of each issue and the fix applied.",
)

frontend_task = Task(
    description="""Audit the pdfforge React frontend in the web/src/ directory.

    Steps:
    1. List all files in web/src/ to understand the frontend structure
    2. Read web/src/App.jsx - the main application component
    3. Read web/src/api.js - the API client
    4. Read web/src/components/UploadZone.jsx - the file upload component
    5. Read web/src/components/PdfViewer.jsx - the PDF preview component (has DPR fix + zoom)
    6. Read web/src/components/FieldList.jsx - the field list component (5 field types)
    7. Read web/vite.config.js - the build config
    8. Check for:
       - XSS vulnerabilities
       - API key or secret exposure in client-side code
       - Error handling for failed API calls (network errors, timeouts)
       - File upload validation (type, size) on the client side
       - Hardcoded API URLs that could break
       - Accessibility issues
       - Field overlay rendering accuracy (DPR scale handling)
    9. Fix any issues you find
    10. Create a branch called 'frontend/security-audit-fixes' and open a PR

    Document each issue found and its fix in your PR description.""",
    agent=frontend_developer,
    expected_output="A Pull Request on GitHub with all frontend security and compliance issues found and fixed, with detailed descriptions.",
)

cv_task = Task(
    description="""Build and validate the CV/ML pipeline for form field detection in scanned PDFs.

    Steps:
    1. Read cv_detector.py - the OpenCV heuristic detection module
    2. Read cv_pipeline/preprocess.py - the data preprocessing pipeline
    3. Read cv_pipeline/train.py - the YOLOv8 training script
    4. Read cv_pipeline/inference.py - the production inference module
    5. Read docs/CV_ML_ROADMAP.md - the Phase 2 roadmap
    6. Test the CV detector on sample_form.pdf:
       - Run cv_detect_tool on the sample PDF
       - Compare results with vector detector results
       - Document accuracy differences
    7. Test the hybrid detection pipeline:
       - Run hybrid_detect_tool on sample_form.pdf (should use vector extraction)
       - Create a scanned-like PDF (rasterize to image, rebuild as image-only PDF)
       - Run hybrid_detect_tool on it (should fall back to CV)
    8. Test the preprocessing pipeline:
       - Use extract_gt_tool on sample_form.pdf to extract ground truth
       - Create a small dataset from available PDFs
       - Run preprocess_dataset_tool to generate YOLO format dataset
       - Verify the dataset structure is correct
    9. Create test PDFs for QA:
       - Use create_test_pdf_tool to create PDFs with known field types
       - Create a multi-page test PDF
       - Create a large form test PDF
    10. Document what training data is still needed:
        - How many PDFs needed (100 minimum, 1000+ ideal, 10000 for production)
        - Where to source them (see docs/PDF_FORM_DOMAIN_GUIDE.md Section 6)
        - Form type taxonomy covers 11 categories with 60+ form types
        - Public sources: IRS.gov (500+), SHRM (200+), CMS.gov (150+), SEC (100+), courts (300+)
        - Data augmentation strategy
    11. Create a branch called 'cv/pipeline-enhancements' and open a PR

    Include in your PR:
    - CV detection test results
    - Preprocessing pipeline validation
    - Training data requirements document
    - Recommendations for model training""",
    agent=cv_engineer,
    expected_output="A Pull Request with CV pipeline test results, preprocessing validation, test PDFs, and a training data requirements document.",
)

qa_task = Task(
    description="""Test the pdfforge application end-to-end with a dedicated test dataset.

    PHASE 1: CREATE TEST DATASET
    1. Use create_test_pdf_tool to create test PDFs in /tmp/pdfforge_qa/:
       - test_text_fields.pdf (text fields only)
       - test_checkboxes.pdf (checkboxes only)
       - test_table.pdf (table cells only)
       - test_mixed.pdf (all field types)
       - test_multi_page.pdf (3+ pages)
    2. Use the sample_form.pdf from the repo
    3. Create a text-only PDF (no form fields) for false positive testing
    4. Create an edge case: empty PDF, tiny PDF

    PHASE 2: RUN TESTS
    For each test PDF, run:
    a. api_analyze_tool - check field detection
    b. api_generate_tool - check fillable PDF generation
    c. verify_pdf_tool - verify AcroForm fields in generated PDF
    d. cv_detect_tool - test CV detection (for scanned PDF comparison)
    e. hybrid_detect_tool - test smart pipeline

    PHASE 3: TEST SCENARIOS
    1. Digital PDF field detection (vector extraction) — all test PDFs
    2. False positive regression — text-only PDF must return 0 fields
    3. Field type accuracy — verify text/checkbox/table_cell/textarea/radio/dropdown/signature/barcode
    4. Label accuracy — verify labels match nearby text
    5. Tab order — verify fields are in reading order
    6. API health and CORS
    7. Rate limiting test
    8. CV pipeline validation — run CV detection on all PDFs, compare with vector
    9. Visibility states — verify hidden/visible_non_print/hidden_printable flags work
    10. Validation hints — verify numeric/date/currency/email/phone/zip/ssn detection from labels
    11. Accessibility — verify tooltip (TU) set on all fields for screen readers
    12. End-to-end: upload -> detect -> generate -> download -> verify
    13. Form type coverage — test detector against 3+ form categories from the taxonomy in docs/PDF_FORM_DOMAIN_GUIDE.md

    PHASE 4: QA REPORT
    Write a comprehensive QA report with:
    - Test case ID, name, input, expected, actual, pass/fail
    - Summary: total tests, passed, failed, blocked
    - CV-specific findings: accuracy comparison vector vs CV
    - Recommendations for improvement

    The API URL is: http://localhost:8000
    The sample PDF is at: pdfforge/sample_form.pdf (repo root)""",
    agent=qa_tester,
    expected_output="A detailed QA test report covering 10+ test cases with pass/fail status, field detection accuracy, CV pipeline validation, and recommendations.",
)

network_task = Task(
    description="""Audit the pdfforge network infrastructure and security.

    Steps:
    1. Check if the API health endpoint is accessible
    2. Check CORS headers - verify they allow only the GitHub Pages origin
    3. Check for exposed endpoints: /docs, /openapi.json, /redoc - should these be public?
    4. Check for security headers: HSTS, X-Frame-Options, Content-Security-Policy, X-Content-Type-Options
    5. Check the Cloudflare tunnel process and configuration
    6. Check for rate limiting on the API
    7. Check file upload security: max size enforcement, type validation
    8. Check if any sensitive data is exposed in API responses
    9. Write a security audit report with:
       - Finding name
       - Severity (Critical/High/Medium/Low/Info)
       - Description
       - Recommendation

    The API URL is: http://localhost:8000
    The frontend URL is: https://infinitemindos-doai.github.io/pdfforge/""",
    agent=network_engineer,
    expected_output="A comprehensive network security audit report with findings categorized by severity and specific remediation recommendations.",
)

senior_review_task = Task(
    description="""Review all work done by the team and provide final recommendations.

    Steps:
    1. List all open Pull Requests on the pdfforge repo
    2. For each PR:
       a. Review the PR details and diff
       b. Evaluate code quality, correctness, and security
       c. Add a review comment with your assessment
       d. State whether you APPROVE or REQUEST CHANGES
    3. Review the QA test report (from QA Tester context)
    4. Review the network security audit report (from Network Engineer context)
    5. Review the CV pipeline work (from CV Engineer context)
    6. Write a FINAL SUMMARY that includes:
       - Overall project health assessment
       - List of all PRs and their approval status
       - Key findings from each team member
       - CV pipeline status and training data requirements
       - QA test results summary
       - Remaining risks and recommendations
       - Whether the project is ready for production use
       - Phase 2 (CV/ML) readiness assessment

    This summary will be read by the project owner (Anthony).""",
    agent=senior_developer,
    expected_output="A final review document with PR approvals/rejections, key findings summary, CV pipeline assessment, QA results, and production-readiness assessment.",
    context=[backend_task, frontend_task, cv_task, qa_task, network_task],
)


# ═══════════════════════════════════════════════════════════════════
#  CREW
# ═══════════════════════════════════════════════════════════════════

pdfforge_crew = Crew(
    agents=[
        backend_developer,
        frontend_developer,
        cv_engineer,
        qa_tester,
        network_engineer,
        senior_developer,
    ],
    tasks=[
        backend_task,
        frontend_task,
        cv_task,
        qa_task,
        network_task,
        senior_review_task,
    ],
    process=Process.sequential,
    verbose=True,
    memory=False,
)


# ═══════════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  PDFFORGE CREW AI v2 - MULTI-AGENT ORCHESTRATION")
    print("  6 agents: Backend | Frontend | CV Eng | QA | Network Eng | Senior Dev")
    print("=" * 70)
    print()

    result = pdfforge_crew.kickoff()

    print()
    print("=" * 70)
    print("  ORCHESTRATION COMPLETE")
    print("=" * 70)
    print()
    print("FINAL OUTPUT:")
    print(result)
    print()

    # Save the output
    output_path = os.path.join(os.path.dirname(__file__), "crew_output_v2.md")
    with open(output_path, "w") as f:
        f.write("# PDFForge CrewAI v2 Orchestration Output\n\n")
        f.write(str(result))
    print(f"Output saved to: {output_path}")