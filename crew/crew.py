"""
PDFForge CrewAI Orchestration
=============================
A 5-agent team that reviews, tests, and secures the pdfforge project.

Agents:
  1. Backend Developer  - Audits API code, finds bugs, fixes them
  2. Frontend Developer - Audits web UI, security review, fixes issues
  3. QA Tester           - Tests PDF upload/analyze/generate flow with real PDFs
  4. Network Engineer    - Audits tunnel, CORS, exposed endpoints, security
  5. Senior Developer    - Reviews all PRs, provides recommendations, approves/rejects

Process: Sequential with handoff to Senior Developer for final review
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

qa_tester = Agent(
    role="QA Tester",
    goal="Test the pdfforge application end-to-end with multiple PDF files. Verify field detection accuracy, fillable PDF generation, and document all test results.",
    backstory="""You are a meticulous QA engineer with 8 years of experience testing 
    document processing applications. You test with:
    - The sample PDF included in the repo
    - Simple text-based PDFs
    - PDFs with checkboxes and tables
    - Edge cases (empty PDFs, large PDFs, scanned PDFs)
    You document every test with: input, expected output, actual output, pass/fail status.
    You also verify the generated fillable PDFs actually have working form fields.""",
    tools=[read_file_tool, shell_tool, api_health_tool, api_analyze_tool, api_generate_tool],
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
    3. Read api/detector.py - the field detection module
    4. Read api/generator.py - the fillable PDF generator module
    5. Check for known bugs:
       - The /api/samples?download= endpoint returns JSON instead of a PDF file
       - Error handling in analyze-pdf and generate-pdf endpoints
       - Temp file cleanup after processing
       - Input validation (file type, file size)
    6. Fix any bugs you find
    7. Create a branch called 'backend/fix-audit-findings' and open a PR with your fixes

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
    5. Read web/src/components/PdfViewer.jsx - the PDF preview component
    6. Read web/src/components/FieldList.jsx - the field list component
    7. Read web/vite.config.js - the build config
    8. Check for:
       - XSS vulnerabilities (any use of dangerouslySetInnerHTML or unsanitized content)
       - API key or secret exposure in client-side code
       - Error handling for failed API calls (network errors, timeouts)
       - File upload validation (type, size) on the client side
       - Hardcoded API URLs that could break
       - Accessibility issues
    9. Fix any issues you find
    10. Create a branch called 'frontend/security-audit-fixes' and open a PR

    Document each issue found and its fix in your PR description.""",
    agent=frontend_developer,
    expected_output="A Pull Request on GitHub with all frontend security and compliance issues found and fixed, with detailed descriptions.",
)

qa_task = Task(
    description="""Test the pdfforge application end-to-end with multiple PDF files.

    Steps:
    1. Check API health endpoint
    2. Read the sample_form.pdf from the repo to understand its structure
    3. Test the analyze endpoint with sample_form.pdf - verify fields are detected
    4. Test the generate endpoint with sample_form.pdf - verify a fillable PDF is produced
    5. Create a simple test PDF with text fields and checkboxes, save it to /tmp/
    6. Test analyze and generate with the custom PDF
    7. Create an edge case: a minimal/empty PDF and test it
    8. For each test, document:
       - Input file and its characteristics
       - API response status and body
       - Whether field detection was accurate
       - Whether the generated fillable PDF has working form fields
       - Pass/fail status
    9. Write a comprehensive QA report

    The API URL is: https://favorites-tiger-contains-impossible.trycloudflare.com
    The sample PDF is at: pdfforge/sample_form.pdf (repo root)""",
    agent=qa_tester,
    expected_output="A detailed QA test report covering at least 3 PDF test cases with pass/fail status, detected fields, and verification of generated fillable PDFs.",
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

    The API URL is: https://favorites-tiger-contains-impossible.trycloudflare.com
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
    3. Review the QA test report (in the context from previous tasks)
    4. Review the network security audit report (in the context from previous tasks)
    5. Write a FINAL SUMMARY that includes:
       - Overall project health assessment
       - List of all PRs and their approval status
       - Key findings from each team member
       - Remaining risks and recommendations
       - Whether the project is ready for production use

    This summary will be read by the project owner (Anthony).""",
    agent=senior_developer,
    expected_output="A final review document with PR approvals/rejections, key findings summary, and a production-readiness assessment.",
    context=[backend_task, frontend_task, qa_task, network_task],
)


# ═══════════════════════════════════════════════════════════════════
#  CREW
# ═══════════════════════════════════════════════════════════════════

pdfforge_crew = Crew(
    agents=[backend_developer, frontend_developer, qa_tester, network_engineer, senior_developer],
    tasks=[backend_task, frontend_task, qa_task, network_task, senior_review_task],
    process=Process.sequential,
    verbose=True,
    memory=False,
)


# ═══════════════════════════════════════════════════════════════════
#  RUN
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  PDFFORGE CREW AI - MULTI-AGENT ORCHESTRATION")
    print("  5 agents: Backend Dev | Frontend Dev | QA | Network Eng | Senior Dev")
    print("=" * 70)
    print()

    # Save intermediate results after each task using callbacks
    task_outputs = {}

    # Run each task's agent and capture output
    # CrewAI sequential process runs tasks in order, passing context forward
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
    output_path = os.path.join(os.path.dirname(__file__), "crew_output.md")
    with open(output_path, "w") as f:
        f.write("# PDFForge CrewAI Orchestration Output\n\n")
        f.write(str(result))
    print(f"Output saved to: {output_path}")