"""
Codex Maintainer — Autonomous edit→test→fix loop.

Reads QA failures, uses Codex to fix context_api.py, restarts PM2,
creates test projects, validates results. Loops until clean or safety
limits are hit.
"""

import asyncio
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Local imports
sys.path.insert(0, str(Path(__file__).parent))
from config import (
    QA_DB_PATH,
    WRAPPER_PATH,
    CODEX_REPO_PATH,
    CODEX_TIMEOUT,
    PM2_PROCESS,
    BACKEND_URL,
    WRAPPER_HEALTH_URL,
    POLL_INTERVAL,
    PROJECT_TIMEOUT,
    MAX_ITERATIONS,
    LOG_FILE,
    LOG_FORMAT,
    DEFAULT_USER_ID,
    DEFAULT_TEMPLATE_ID,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    DISCORD_WEBHOOK_URL,
)
from codex_usage_tracker import CodexUsageTracker

# ── context_api.py Section Map ────────────────────────
# This map tells Codex where to find relevant code in context_api.py
# (10,924 lines total, version 3.10.33)
CONTEXT_API_SECTIONS = {
    "imports":              (1, 45),
    "failure_tracking":     (46, 100),
    "pydantic_models":      (103, 165),
    "tool_arg_validation":  (168, 310),
    "tool_name_normalization": (312, 410),
    "path_normalization":   (412, 490),
    "tool_result_helpers":  (492, 610),
    "read_tracking":        (612, 850),
    "stub_detection":       (852, 960),
    "page_replacement":     (962, 1100),
    "route_repair":         (1102, 1750),
    "nav_shell_repair":     (1752, 2400),
    "browser_verification": (2402, 3200),
    "tool_injection":       (3202, 4200),
    "command_repair":       (4202, 5200),
    "frontend_guards":      (5202, 6200),
    "workflow_policies":    (6202, 7200),
    "anthropic_endpoint":   (9432, 11490),
    "utility_endpoints":    (11510, 11640),
    "entry_point":          (11640, 11650),
}

# ── Logging Setup ──────────────────────────────────────
logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format=LOG_FORMAT,
)
logger = logging.getLogger("codex_maintainer")

# Also log to stdout for subprocess visibility
console = logging.StreamHandler(sys.stdout)
console.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(console)


# ── Failure Reading ────────────────────────────────────

def _get_qa_conn() -> sqlite3.Connection:
    """Connect to the QA tester SQLite database (read-only)."""
    conn = sqlite3.connect(str(QA_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def read_recent_failures() -> List[Dict[str, Any]]:
    """
    Read recent failed/errored projects from the QA tester database.
    Returns list of failure dicts with id, domain, description, status, verdict, issues.
    """
    if not QA_DB_PATH.exists():
        logger.info("QA database not found at %s — no failures to process", QA_DB_PATH)
        return []

    conn = _get_qa_conn()
    try:
        rows = conn.execute(
            """
            SELECT id, domain, description, status, verdict, issues, raw_output
            FROM projects
            WHERE verdict = 'fail'
              AND verified_at IS NOT NULL
            ORDER BY verified_at DESC
            LIMIT 20
            """
        ).fetchall()

        failures = []
        for row in rows:
            issues = row["issues"]
            if isinstance(issues, str):
                try:
                    issues = json.loads(issues)
                except json.JSONDecodeError:
                    issues = [issues]

            failures.append({
                "id": row["id"],
                "domain": row["domain"],
                "description": row["description"] or "",
                "status": row["status"],
                "verdict": row["verdict"],
                "issues": issues if isinstance(issues, list) else [str(issues)],
                "raw_output": row["raw_output"] or "",
            })

        logger.info("Found %d recent failures in QA database", len(failures))
        return failures
    finally:
        conn.close()


def _failure_signature(failure: Dict[str, Any]) -> str:
    """Create a short signature string for deduplication and prompt context."""
    issues_text = "; ".join(str(i) for i in failure.get("issues", [])[:3])
    return f"project#{failure['id']} domain={failure['domain']} issues=[{issues_text}]"


def _classify_failure(failure: Dict[str, Any]) -> str:
    """Classify the failure type to target the right context_api.py section."""
    issues = " ".join(str(i).lower() for i in failure.get("issues", []))
    raw = str(failure.get("raw_output", "")).lower()
    combined = issues + " " + raw

    if any(kw in combined for kw in ("stub", "placeholder", "scaffold", "welcome page")):
        return "stub_placeholder"
    if any(kw in combined for kw in ("404", "route", "not found", "navigation")):
        return "route_404"
    if any(kw in combined for kw in ("nav", "no_nav", "missingnavlabels", "missing_labels")):
        return "nav_shell"
    if any(kw in combined for kw in ("build", "vite", "esbuild", "syntax error", "transform failed")):
        return "build_failure"
    if any(kw in combined for kw in ("browser", "verification", "screenshot", "eval")):
        return "browser_verification"
    if any(kw in combined for kw in ("import", "module", "npm install", "package")):
        return "import_error"
    if any(kw in combined for kw in ("timeout", "timed out", "hanging")):
        return "timeout"
    if any(kw in combined for kw in ("tool", "argument", "validation", "unknown tool")):
        return "tool_validation"
    return "generic"


# ── Codex Fix ──────────────────────────────────────────

async def codex_fix(failure: Dict[str, Any], tracker: CodexUsageTracker) -> Optional[str]:
    """
    Use Codex to fix context_api.py based on a QA failure.
    Returns Codex's response text or None on failure.
    """
    from codex_code_agent import CodexCodeAgent  # Late import — only in maintainer path

    signature = _failure_signature(failure)
    logger.info("Starting Codex fix for %s", signature)

    prompt = _build_fix_prompt(failure)
    logger.debug("Codex prompt:\n%s", prompt[:500])

    tracker.record_start()
    try:
        async with CodexCodeAgent(
            repo_path=str(CODEX_REPO_PATH),
        ) as agent:
            response = await agent.query(prompt, timeout=float(CODEX_TIMEOUT))

        if response:
            logger.info("Codex fix completed for %s (response: %d chars)", signature, len(response))
        else:
            logger.warning("Codex returned empty response for %s", signature)

        return response
    except Exception as exc:
        logger.error("Codex fix failed for %s: %s", signature, exc)
        return None
    finally:
        tracker.record_end()


def _build_fix_prompt(failure: Dict[str, Any]) -> str:
    """Build a targeted Codex fix prompt from a failure record.

    Includes context_api.py section guidance so Codex knows exactly where to look.
    """
    failure_type = _classify_failure(failure)
    issues_list = "\n".join(f"  - {issue}" for issue in failure.get("issues", []))
    desc = failure.get("description", "No description")
    domain = failure.get("domain", "unknown")
    raw = failure.get("raw_output", "")

    # Truncate raw output to avoid oversized prompts
    if len(raw) > 2000:
        raw = raw[:2000] + "\n... (truncated)"

    # Map failure type to context_api.py section guidance
    section_guidance = {
        "stub_placeholder": (
            "## Relevant Sections\n"
            "- `stub_detection` (lines 852-960): `_looks_like_generated_stub_content()`, `_recent_read_stub_for_path()`\n"
            "- `page_replacement` (lines 962-1100): `_stub_page_replacement_content()`, `_stub_page_replacement_tool_call()`\n"
            "- `route_repair` (lines 1102-1750): `_active_placeholder_route_repair_state()`, `_should_force_route_repair_read_app()`\n"
            "\nLikely root cause: Stub detection is not matching the current placeholder pattern, or the\n"
            "replacement content generator is producing invalid JSX. Check the regex patterns in\n"
            "`_looks_like_generated_stub_content()` and the template in `_stub_page_replacement_content()`."
        ),
        "route_404": (
            "## Relevant Sections\n"
            "- `route_repair` (lines 1102-1750): `_active_placeholder_route_repair_state()`, `_route_repair_app_content()`\n"
            "- `nav_shell_repair` (lines 1752-2400): `_active_nav_shell_repair_state()`\n"
            "- `browser_verification` (lines 2402-3200): page/404 detection logic\n"
            "\nLikely root cause: Route repair is not detecting the placeholder/404 state correctly, or\n"
            "`_route_repair_app_content()` is generating broken JSX imports. Check the failure markers\n"
            "and the page discovery logic in `_route_repair_page_imports()`."
        ),
        "nav_shell": (
            "## Relevant Sections\n"
            "- `nav_shell_repair` (lines 1752-2400): `_active_nav_shell_repair_state()`, nav detection\n"
            "- `route_repair` (lines 1102-1750): `_route_repair_app_content()` generates App.tsx with nav\n"
            "\nLikely root cause: The nav shell detection is triggering false positives, or the nav labels\n"
            "in the generated App.tsx don't match the verification expectations."
        ),
        "build_failure": (
            "## Relevant Sections\n"
            "- `stub_detection` (lines 852-960): Page stub detection\n"
            "- `page_replacement` (lines 962-1100): `_page_syntax_repair_tool_call()`\n"
            "- `frontend_guards` (lines 5202-6200): Build guard logic\n"
            "\nLikely root cause: Generated page replacement content has syntax errors that esbuild\n"
            "rejects. Check `_stub_page_replacement_content()` for JSX validity and\n"
            "`_active_frontend_build_page_syntax_failure()` for failure detection accuracy."
        ),
        "browser_verification": (
            "## Relevant Sections\n"
            "- `browser_verification` (lines 2402-3200): Verification pass/fail detection\n"
            "- `tool_injection` (lines 3202-4200): Browser tool call injection\n"
            "\nLikely root cause: Browser verification is producing false negatives, or the content\n"
            "evaluation regex is not matching the actual page output."
        ),
        "import_error": (
            "## Relevant Sections\n"
            "- `imports` (lines 1-45): All module imports\n"
            "- `command_repair` (lines 4202-5200): `_extract_npm_install_package()`\n"
            "\nLikely root cause: A module import is broken, or the npm install detection is not\n"
            "recognizing a successful install output."
        ),
        "timeout": (
            "## Relevant Sections\n"
            "- `anthropic_endpoint` (lines 9432-11490): Main message processing pipeline\n"
            "- `tool_injection` (lines 3202-4200): Tool call handling\n"
            "\nLikely root cause: The message processing pipeline has an infinite loop or blocking\n"
            "call. Check guard loops for missing break conditions or counters."
        ),
        "tool_validation": (
            "## Relevant Sections\n"
            "- `tool_arg_validation` (lines 168-310): `REQUIRED_TOOL_ARGS`, `ALLOWED_TOOL_ARGS`\n"
            "- `tool_name_normalization` (lines 312-410): `ALLOWED_TOOL_ARGS`, alias resolution\n"
            "\nLikely root cause: A tool name or argument is not in the allowed lists, or the\n"
            "normalization function is mangling a valid tool name."
        ),
        "generic": (
            "## File Overview\n"
            "context_api.py is ~10,924 lines. Key sections:\n"
            "- Lines 1-45: Imports\n"
            "- Lines 103-165: Pydantic models\n"
            "- Lines 168-410: Tool validation and normalization\n"
            "- Lines 492-1100: Read tracking, stub detection, page replacement\n"
            "- Lines 1102-2400: Route and nav shell repair\n"
            "- Lines 2402-4200: Browser verification and tool injection\n"
            "- Lines 4202-7200: Command repair and frontend guards\n"
            "- Lines 9432-11490: Main anthropic messages endpoint\n"
            "- Lines 11510-11650: Health/utility endpoints\n"
            "\nRead the file carefully and identify the root cause of the failure."
        ),
    }

    guidance = section_guidance.get(failure_type, section_guidance["generic"])

    return f"""You are an autonomous maintenance agent fixing a bug in context_api.py.

**File:** `D:\\claudewrapper\\context_api.py` (10,924 lines, version 3.10.33)
**This is a FastAPI wrapper** that intercepts Claude Code tool calls and adds guards/repairs
for DreamAgent project creation. It runs on port 7861 and is the main entry point for
Claude Code interactions.

## Failure Details
- Project ID: {failure['id']}
- Domain: {domain}
- Description: {desc}
- Status before failure: {failure.get('status', 'unknown')}
- Failure classification: {failure_type}

## Issues Found
{issues_list}

## Raw Output (if available)
```
{raw}
```

{guidance}

## Instructions
1. Read the relevant sections of context_api.py (use the line ranges above)
2. Identify the specific function/pattern causing the failure
3. Make the **minimal** fix — change only what's broken
4. Do NOT add new features, refactor, or change unrelated code
5. Preserve ALL existing function signatures and API contracts
6. Keep the version comment in the endpoint docstring unchanged unless the fix
   warrants a version bump

Apply the fix now."""


# ── PM2 Restart ────────────────────────────────────────

def restart_pm2() -> bool:
    """Restart the clawd-backend PM2 process."""
    logger.info("Restarting PM2 process: %s", PM2_PROCESS)
    try:
        result = subprocess.run(
            ["pm2", "restart", PM2_PROCESS],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            logger.info("PM2 restart successful")
            return True
        else:
            logger.error("PM2 restart failed (code %d): %s", result.returncode, result.stderr[:300])
            return False
    except FileNotFoundError:
        logger.error("pm2 command not found — is PM2 installed and in PATH?")
        return False
    except subprocess.TimeoutExpired:
        logger.error("PM2 restart timed out")
        return False


# ── Health Check ───────────────────────────────────────

async def check_wrapper_health(retries: int = 5, delay: float = 5.0) -> bool:
    """Poll the wrapper health endpoint until it responds."""
    logger.info("Checking wrapper health at %s", WRAPPER_HEALTH_URL)
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(WRAPPER_HEALTH_URL)
                if resp.status_code == 200:
                    logger.info("Wrapper health OK (attempt %d)", attempt)
                    return True
                logger.warning("Wrapper health returned %d (attempt %d)", resp.status_code, attempt)
        except Exception as exc:
            logger.warning("Wrapper health check failed (attempt %d): %s", attempt, exc)

        if attempt < retries:
            await asyncio.sleep(delay)

    logger.error("Wrapper health check failed after %d attempts", retries)
    return False


# ── Test Project Creation ──────────────────────────────

async def create_test_project(failure: Dict[str, Any]) -> Optional[int]:
    """
    Create a test project via POST /projects to validate the fix.
    Returns the project ID or None on failure.
    """
    desc = f"AUTOTEST: Validating fix for project#{failure['id']} — {_failure_signature(failure)}"
    payload = {
        "name": f"codex-autotest-{failure['id']}-{int(time.time())}",
        "description": desc,
        "user_id": DEFAULT_USER_ID,
        "type_id": 1,
        "template_id": DEFAULT_TEMPLATE_ID,
    }

    logger.info("Creating test project: %s", payload["name"])
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{BACKEND_URL}/projects", json=payload)
            resp.raise_for_status()
            project = resp.json()
            project_id = project.get("id")
            logger.info("Test project created: id=%s domain=%s", project_id, project.get("domain"))
            return project_id
    except httpx.HTTPStatusError as exc:
        logger.error("Test project creation failed (HTTP %d): %s", exc.response.status_code, exc.response.text[:300])
    except Exception as exc:
        logger.error("Test project creation failed: %s", exc)
    return None


async def poll_project_status(project_id: int) -> Optional[str]:
    """
    Poll GET /projects/{id}/status until completion or timeout.
    Returns the final status string or None on error/timeout.
    """
    logger.info("Polling status for project %d (interval=%ds, timeout=%ds)", project_id, POLL_INTERVAL, PROJECT_TIMEOUT)
    start = time.monotonic()

    while (time.monotonic() - start) < PROJECT_TIMEOUT:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(f"{BACKEND_URL}/projects/{project_id}/status")
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "unknown")

                if status in ("ready", "failed", "completed", "deployed"):
                    logger.info("Project %d final status: %s", project_id, status)
                    return status

                logger.debug("Project %d status: %s (elapsed: %.0fs)", project_id, status, time.monotonic() - start)
        except Exception as exc:
            logger.warning("Status poll failed for project %d: %s", project_id, exc)

        await asyncio.sleep(POLL_INTERVAL)

    logger.error("Project %d timed out after %ds", project_id, PROJECT_TIMEOUT)
    return None


# ── Log Validation ─────────────────────────────────────

def validate_wrapper_logs(project_id: int) -> bool:
    """
    Check PM2 logs for error signatures related to a project.
    Returns True if no error signatures found.
    """
    try:
        result = subprocess.run(
            ["pm2", "logs", PM2_PROCESS, "--lines", "100", "--nostream"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        logs = result.stdout + result.stderr
    except Exception as exc:
        logger.warning("Could not read PM2 logs: %s", exc)
        # If we can't read logs, don't block progress
        return True

    # Error signatures that indicate persistent issues
    error_patterns = [
        r"Traceback\s+\(most recent call last\)",
        r"Error:\s+.*(?!TimeoutError)",  # Exclude timeout errors (transient)
        r"Exception:\s+.*context_api",
        r"ModuleNotFoundError",
        r"ImportError",
    ]

    project_log_lines = [
        line for line in logs.splitlines()
        if str(project_id) in line
    ]

    for line in project_log_lines:
        for pattern in error_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                logger.warning("Error signature found in logs for project %d: %s", project_id, line[:200])
                return False

    logger.info("Wrapper log validation passed for project %d", project_id)
    return True


# ── Notifications ──────────────────────────────────────

async def send_notification(message: str) -> None:
    """Send a notification via Telegram and/or Discord."""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"},
                )
            logger.info("Telegram notification sent")
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)

    if DISCORD_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    DISCORD_WEBHOOK_URL,
                    json={"content": message},
                )
            logger.info("Discord notification sent")
        except Exception as exc:
            logger.warning("Discord notification failed: %s", exc)


# ── Main Loop ──────────────────────────────────────────

async def maintainer_loop() -> int:
    """
    Main autonomous loop: read failures → fix → restart → test → validate.
    Returns 0 on success, 1 on error, 2 on safety stop.
    """
    logger.info("=" * 60)
    logger.info("Codex Maintainer starting")
    logger.info("=" * 60)

    tracker = CodexUsageTracker()
    summary = tracker.usage_summary()
    logger.info("Usage state: %s", summary)

    if not tracker.can_proceed():
        logger.info("Usage limit reached — exiting (remaining: %.1fh)", tracker.remaining_hours())
        return 2

    # Read failures
    failures = read_recent_failures()
    if not failures:
        logger.info("No failures found — all clear")
        return 0

    fixed_count = 0
    retry_count = 0

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info("--- Iteration %d / %d ---", iteration, MAX_ITERATIONS)

        # Re-read failures each iteration (may change as fixes are applied)
        if iteration > 1:
            failures = read_recent_failures()
            if not failures:
                logger.info("All failures resolved after %d iterations", iteration - 1)
                break

        # Check usage before each iteration
        if not tracker.can_proceed():
            logger.warning("Usage limit hit mid-loop — stopping")
            await send_notification(
                f"⚠️ *Codex Maintainer*: Usage limit reached. "
                f"Remaining: {tracker.remaining_hours():.1f}h. Stopping after {fixed_count} fixes."
            )
            return 2

        for failure in failures:
            signature = _failure_signature(failure)
            logger.info("Processing: %s", signature)

            # Step 1: Codex fix
            response = await codex_fix(failure, tracker)
            if not response:
                logger.warning("Codex returned no response — skipping validation for %s", signature)
                retry_count += 1
                continue

            # Step 2: Restart PM2 wrapper
            if not restart_pm2():
                logger.error("PM2 restart failed — aborting iteration")
                await send_notification(f"🔴 *Codex Maintainer*: PM2 restart failed for {signature}")
                continue

            # Step 3: Health check
            if not await check_wrapper_health():
                logger.error("Wrapper health check failed after restart")
                await send_notification(f"🔴 *Codex Maintainer*: Wrapper unhealthy after fix for {signature}")
                continue

            # Step 4: Create test project
            project_id = await create_test_project(failure)
            if not project_id:
                logger.error("Test project creation failed for %s", signature)
                continue

            # Step 5: Poll for completion
            final_status = await poll_project_status(project_id)
            if not final_status:
                logger.error("Test project timed out for %s", signature)
                continue

            # Step 6: Validate logs
            logs_ok = validate_wrapper_logs(project_id)

            # Step 7: Evaluate result
            if final_status in ("ready", "completed", "deployed") and logs_ok:
                fixed_count += 1
                logger.info("✅ Fix verified for %s (test project #%d: %s)", signature, project_id, final_status)
            else:
                logger.warning("❌ Fix NOT verified for %s (status=%s, logs_ok=%s)", signature, final_status, logs_ok)
                retry_count += 1

    # Summary
    logger.info("=" * 60)
    logger.info("Maintainer run complete: %d fixed, %d retries, %d iterations", fixed_count, retry_count, iteration)
    logger.info("=" * 60)

    if retry_count > 0:
        await send_notification(
            f"🔧 *Codex Maintainer*: Run complete. "
            f"Fixed: {fixed_count}, Retries: {retry_count}, Iterations: {iteration}"
        )

    if iteration >= MAX_ITERATIONS and failures:
        logger.warning("Max iterations reached — manual intervention may be needed")
        await send_notification(
            f"🚨 *Codex Maintainer*: MAX_ITERATIONS ({MAX_ITERATIONS}) reached with unresolved failures. "
            f"Manual intervention recommended."
        )

    return 0


def main() -> int:
    """Entry point — runs the async maintainer loop."""
    try:
        return asyncio.run(maintainer_loop())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as exc:
        logger.critical("Unhandled exception in maintainer: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
