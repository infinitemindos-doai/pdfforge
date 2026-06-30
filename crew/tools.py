"""
Custom tools for the PDFForge CrewAI team.
Each tool lets an agent interact with the codebase, shell, GitHub, or the live API.
"""

import os
import subprocess
import json
import requests
from crewai.tools import tool


# ── Path config ──
PDFFORGE_ROOT = os.environ.get("PDFFORGE_ROOT", "/Users/infinitemind/.openclaw/workspace/pdfforge")
API_URL = os.environ.get("PDFFORGE_API_URL", "http://localhost:8000")
GH = os.environ.get("GH_CLI_PATH", "gh")


# ── File Tools ──

@tool("Read file from the pdfforge repo")
def read_file_tool(file_path: str) -> str:
    """Read the contents of a file in the pdfforge repository.
    Use a path relative to the repo root, e.g. 'api/app.py' or 'web/src/App.jsx'.
    """
    full_path = os.path.join(PDFFORGE_ROOT, file_path)
    if not os.path.exists(full_path):
        return f"Error: File not found at {full_path}"
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Truncate very large files
        if len(content) > 30000:
            content = content[:30000] + f"\n\n... [truncated, file is {len(content)} chars total]"
        return content
    except Exception as e:
        return f"Error reading file: {e}"


@tool("List files in a directory")
def list_files_tool(directory: str = ".") -> str:
    """List files in a directory within the pdfforge repo.
    Use a relative path like 'api/' or 'web/src/components/' or '.' for root.
    """
    full_path = os.path.join(PDFFORGE_ROOT, directory)
    if not os.path.exists(full_path):
        return f"Error: Directory not found at {full_path}"
    result = []
    for root, dirs, files in os.walk(full_path):
        # Skip hidden dirs, node_modules, venv, dist
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", "dist", ".venv", ".venv-crewai")]
        for f in files:
            if not f.startswith("."):
                rel = os.path.relpath(os.path.join(root, f), PDFFORGE_ROOT)
                result.append(rel)
    return "\n".join(sorted(result))


# ── Shell Tools ──

@tool("Run a shell command in the pdfforge repo")
def shell_tool(command: str) -> str:
    """Run a shell command in the pdfforge repository root.
    Useful for: grep, find, python scripts, curl tests, git status, etc.
    The command runs with a 30-second timeout.
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=PDFFORGE_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[EXIT CODE: {result.returncode}]"
        if len(output) > 20000:
            output = output[:20000] + "\n... [truncated]"
        return output if output.strip() else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 30 seconds"
    except Exception as e:
        return f"Error: {e}"


# ── GitHub Tools ──

@tool("Create a git branch and commit changes")
def git_branch_commit_tool(branch_name: str, commit_message: str, files: str = "") -> str:
    """Create a new git branch, stage files, and commit.
    Args:
        branch_name: Name for the new branch (e.g. 'backend/fix-cors-headers')
        commit_message: The commit message
        files: Space-separated file paths to stage (e.g. 'api/app.py api/detector.py'). Use '.' for all changes.
    """
    try:
        cmds = [
            f"git checkout -b {branch_name}",
            f"git add {files}",
            f'git commit -m "{commit_message}"',
        ]
        results = []
        for cmd in cmds:
            r = subprocess.run(cmd, shell=True, cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=15)
            results.append(f"$ {cmd}\n{r.stdout}{r.stderr}")
        return "\n\n".join(results)
    except Exception as e:
        return f"Error: {e}"


@tool("Push branch and create a GitHub Pull Request")
def create_pr_tool(branch_name: str, title: str, body: str) -> str:
    """Push a branch to GitHub and open a Pull Request.
    Args:
        branch_name: The branch to push
        title: PR title
        body: PR description (markdown)
    """
    try:
        # Push
        r1 = subprocess.run(
            f"git push -u origin {branch_name}",
            shell=True, cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=30
        )
        push_out = r1.stdout + r1.stderr

        # Create PR
        r2 = subprocess.run(
            [GH, "pr", "create", "--title", title, "--body", body, "--head", branch_name],
            cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=30
        )
        pr_out = r2.stdout + r2.stderr
        return f"Push:\n{push_out}\n\nPR:\n{pr_out}"
    except Exception as e:
        return f"Error: {e}"


@tool("List open Pull Requests")
def list_prs_tool() -> str:
    """List all open Pull Requests on the pdfforge GitHub repo."""
    try:
        r = subprocess.run(
            [GH, "pr", "list", "--state", "open", "--json", "number,title,headRefName,author,body"],
            cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=15
        )
        return r.stdout if r.stdout.strip() else "No open PRs"
    except Exception as e:
        return f"Error: {e}"


@tool("Review a specific Pull Request")
def review_pr_tool(pr_number: str) -> str:
    """Get full details of a specific PR including diff.
    Args:
        pr_number: The PR number to review
    """
    try:
        r1 = subprocess.run(
            [GH, "pr", "view", pr_number, "--json", "title,body,headRefName,author,additions,deletions,changedFiles"],
            cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=15
        )
        r2 = subprocess.run(
            [GH, "pr", "diff", pr_number],
            cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=15
        )
        diff = r2.stdout
        if len(diff) > 15000:
            diff = diff[:15000] + "\n... [diff truncated]"
        return f"PR Details:\n{r1.stdout}\n\nDiff:\n{diff}"
    except Exception as e:
        return f"Error: {e}"


@tool("Add a comment to a Pull Request")
def comment_pr_tool(pr_number: str, comment: str) -> str:
    """Add a review comment to a PR.
    Args:
        pr_number: The PR number
        comment: The review comment (markdown)
    """
    try:
        r = subprocess.run(
            [GH, "pr", "comment", pr_number, "--body", comment],
            cwd=PDFFORGE_ROOT, capture_output=True, text=True, timeout=15
        )
        return r.stdout if r.stdout.strip() else f"Comment added to PR #{pr_number}"
    except Exception as e:
        return f"Error: {e}"


# ── API Testing Tools ──

@tool("Test the pdfforge API health endpoint")
def api_health_tool() -> str:
    """Check if the pdfforge backend API is healthy and responsive."""
    try:
        r = requests.get(f"{API_URL}/api/health", timeout=10)
        return f"Status {r.status_code}: {r.text}"
    except Exception as e:
        return f"Error: {e}"


@tool("Test PDF analysis via the API")
def api_analyze_tool(pdf_path: str) -> str:
    """Upload a PDF to the pdfforge API and get detected fields.
    Args:
        pdf_path: Absolute path to a PDF file to test
    """
    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{API_URL}/api/analyze-pdf",
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                timeout=60,
            )
        return f"Status {r.status_code}: {r.text[:5000]}"
    except Exception as e:
        return f"Error: {e}"


@tool("Test fillable PDF generation via the API")
def api_generate_tool(pdf_path: str) -> str:
    """Upload a PDF to the pdfforge API and generate a fillable version.
    Args:
        pdf_path: Absolute path to a PDF file to test
    """
    try:
        with open(pdf_path, "rb") as f:
            r = requests.post(
                f"{API_URL}/api/generate-pdf",
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                timeout=60,
            )
        if r.status_code == 200:
            out_path = f"/tmp/pdfforge_test_{os.path.basename(pdf_path)}"
            with open(out_path, "wb") as out:
                out.write(r.content)
            return f"Status 200: Generated fillable PDF saved to {out_path} ({len(r.content)} bytes)"
        else:
            return f"Status {r.status_code}: {r.text[:2000]}"
    except Exception as e:
        return f"Error: {e}"


@tool("Check CORS headers on the API")
def api_cors_check_tool() -> str:
    """Check if the API has proper CORS headers for the GitHub Pages frontend."""
    try:
        origin = "https://infinitemindos-doai.github.io"
        r = requests.options(
            f"{API_URL}/api/analyze-pdf",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
            timeout=10,
        )
        headers = dict(r.headers)
        cors_headers = {k: v for k, v in headers.items() if "access-control" in k.lower() or "cors" in k.lower()}
        return f"Status {r.status_code}\nCORS Headers: {json.dumps(cors_headers, indent=2)}"
    except Exception as e:
        return f"Error: {e}"


# ── Network Audit Tools ──

@tool("Check exposed endpoints and security headers")
def network_audit_tool() -> str:
    """Audit the pdfforge API for exposed endpoints, security headers, and potential vulnerabilities."""
    results = []
    endpoints = ["/api/health", "/api/samples", "/docs", "/openapi.json", "/redoc"]
    for ep in endpoints:
        try:
            r = requests.get(f"{API_URL}{ep}", timeout=10)
            security_headers = {
                k: v for k, v in dict(r.headers).items()
                if any(s in k.lower() for s in ["x-frame", "x-content", "strict-transport", "x-xss", "content-security"])
            }
            results.append(f"{ep}: Status {r.status_code}, Security headers: {security_headers or 'NONE'}")
        except Exception as e:
            results.append(f"{ep}: Error - {e}")
    return "\n".join(results)


@tool("Check Cloudflare tunnel configuration")
def tunnel_check_tool() -> str:
    """Check the Cloudflare tunnel status and configuration."""
    try:
        r = subprocess.run(
            "ps aux | grep cloudflared | grep -v grep",
            shell=True, capture_output=True, text=True, timeout=10
        )
        return f"Running tunnels:\n{r.stdout}" if r.stdout.strip() else "No cloudflared process found"
    except Exception as e:
        return f"Error: {e}"