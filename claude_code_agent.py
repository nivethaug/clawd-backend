#!/usr/bin/env python3
"""
Claude Code Agent - A Python wrapper for the Claude CLI.

This module provides a clean, asynchronous interface to Claude Code by running
the `claude` CLI directly as a subprocess. It does NOT use acpx or ACP (Agent
Communication Protocol) - it simply wraps the claude CLI and treats all output
as plain text.

The agent accumulates stdout/stderr as plain text lines and applies heuristics
to extract the final answer from the response.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import re
import shutil
import shlex
import time
import urllib.request
import urllib.error
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Callable, Optional, Any

# Configure logger
logger = logging.getLogger(__name__)


def configure_logging(
    level: int = logging.INFO,
    format_string: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    log_file: Optional[str] = None,
) -> None:
    """
    Configure logging for ClaudeCodeAgent.

    Args:
        level: Logging level (default: logging.INFO)
        format_string: Log message format
        log_file: Optional path to log file (default: console only)
    """
    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter(format_string))
    logger.addHandler(handler)
    logger.setLevel(level)


class ClaudeCodeAgent:
    """
    An async context manager that runs Claude Code queries via the claude CLI.

    This class manages Claude CLI subprocess execution, reads plain text output,
    and provides a simple query interface.

    Note: This does NOT use acpx or ACP. It calls `claude` CLI directly.

    Example:
        async with ClaudeCodeAgent("/path/to/repo") as agent:
            response = await agent.query("Write a hello.py")
            print(response)
    """

    def __init__(
        self,
        repo_path: str,
        settings_path: Optional[str] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        claude_path: Optional[str] = None,
        progress_interval: float = 30.0,
        resume_session_id: Optional[str] = None,
    ):
        """
        Initialize Claude Code Agent.

        Args:
            repo_path: Path to repository/workspace to work in
            settings_path: Optional path to Claude Code settings (default: ~/.claude/settings.json)
            on_text: Optional callback for streaming text as it arrives (content - persisted to DB)
            on_progress: Optional callback for progress updates (UI only - NOT persisted to DB)
            claude_path: Optional path to claude CLI (default: auto-detect via shutil.which)
            progress_interval: Seconds between progress updates while waiting (default: 30s, env: CLAUDE_PROGRESS_INTERVAL_SECONDS)
        
        Note: Auto-approve is enabled via --dangerously-skip-permissions (runs as non-root via sudo -u)
        """
        self.repo_path = Path(repo_path).resolve()
        self.settings_path = Path(settings_path or Path.home() / ".claude" / "settings.json")
        self.on_text = on_text
        self.on_progress = on_progress  # Separate callback for progress (not persisted to DB)
        self.claude_path = claude_path
        
        # Progress interval (from env or param, default 30s)
        self.progress_interval = float(os.environ.get("CLAUDE_PROGRESS_INTERVAL_SECONDS", progress_interval))
        logger.info(f"[CLAUDE-AGENT] progress_interval={self.progress_interval}s, on_text={'set' if on_text else 'NOT SET'}, on_progress={'set' if on_progress else 'NOT SET'}")

        # Internal state
        self._running = False
        self._current_process = None  # Track running subprocess for cancellation
        self._cancelled = False  # Flag to distinguish cancel from real crash
        self._progress_dots_offset = 0  # For dot animation (1-2-3 cycling)
        self._last_token_usage = None  # Token usage from last query result
        self._last_session_id: Optional[str] = resume_session_id

        # Load Claude Code settings
        self._settings = self._load_settings()

        logger.info(f"ClaudeCodeAgent initialized: repo_path={self.repo_path}, settings_path={self.settings_path}")

    @staticmethod
    def _env_bool(name: str, default: bool = False) -> bool:
        """Read a permissive boolean env flag."""
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() not in {"0", "false", "no", "off", ""}

    def _cleanup_user(self) -> Optional[str]:
        """Return the Unix user whose agent helper processes should be cleaned up."""
        if os.name != "posix":
            return None
        if os.geteuid() == 0:
            return os.environ.get("CLAUDE_RUN_AS_USER", "dreampilot")
        return None

    def _project_root_for_cleanup(self) -> Path:
        """Use the project root, not just frontend/src, for matching escaped serve processes."""
        path = self.repo_path
        parts = path.parts
        for marker in ("frontend", "src"):
            if marker in parts:
                return Path(*parts[:parts.index(marker)])
        return path

    @staticmethod
    def _read_proc_cmdline(pid: int) -> str:
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
            return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            return ""

    @staticmethod
    def _read_proc_cwd(pid: int) -> Optional[Path]:
        try:
            return Path(os.readlink(f"/proc/{pid}/cwd")).resolve()
        except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
            return None

    @staticmethod
    def _same_or_child_path(candidate: Optional[Path], root: Path) -> bool:
        if candidate is None:
            return False
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            return candidate == root

    async def _terminate_pids(self, pids: set[int], label: str, grace_seconds: float = 1.5) -> None:
        """TERM then KILL a set of pids, ignoring processes that already exited."""
        pids.discard(os.getpid())
        if not pids:
            return

        logger.info(f"[CLAUDE-AGENT] Cleaning up {len(pids)} {label} process(es): {sorted(pids)}")
        for pid in sorted(pids):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError as e:
                logger.warning(f"[CLAUDE-AGENT] Permission denied SIGTERM {label} pid={pid}: {e}")
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] Could not SIGTERM {label} pid={pid}: {e}")

        await asyncio.sleep(grace_seconds)

        for pid in sorted(pids):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError as e:
                logger.warning(f"[CLAUDE-AGENT] Permission denied SIGKILL {label} pid={pid}: {e}")
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] Could not SIGKILL {label} pid={pid}: {e}")

    async def _terminate_process_group(self, pgid: Optional[int], label: str, grace_seconds: float = 1.5) -> None:
        """TERM then KILL the process group opened for the current Claude query."""
        if os.name != "posix" or not pgid:
            return

        try:
            os.killpg(pgid, signal.SIGTERM)
            logger.info(f"[CLAUDE-AGENT] Sent SIGTERM to {label} process group {pgid}")
        except ProcessLookupError:
            return
        except Exception as e:
            logger.warning(f"[CLAUDE-AGENT] Could not SIGTERM {label} process group {pgid}: {e}")
            return

        await asyncio.sleep(grace_seconds)

        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except Exception:
            return

        try:
            os.killpg(pgid, signal.SIGKILL)
            logger.warning(f"[CLAUDE-AGENT] Sent SIGKILL to lingering {label} process group {pgid}")
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.warning(f"[CLAUDE-AGENT] Could not SIGKILL {label} process group {pgid}: {e}")

    async def _cleanup_project_serve_processes(self) -> None:
        """Kill preview servers that Claude left behind for this repo/project only."""
        if os.name != "posix" or not self._env_bool("CLAUDE_AGENT_CLEANUP_PROJECT_SERVERS", False):
            return

        project_root = self._project_root_for_cleanup().resolve()
        repo_path = self.repo_path.resolve()
        candidates: set[int] = set()

        for proc_dir in Path("/proc").iterdir():
            if not proc_dir.name.isdigit():
                continue
            pid = int(proc_dir.name)
            cmdline = self._read_proc_cmdline(pid)
            if not cmdline:
                continue

            lower_cmd = cmdline.lower()
            looks_like_serve = (
                "npx serve" in lower_cmd
                or " serve dist" in lower_cmd
                or "node_modules/.bin/serve" in lower_cmd
            )
            if not looks_like_serve:
                continue

            cwd = self._read_proc_cwd(pid)
            cmd_mentions_project = str(project_root) in cmdline or str(repo_path) in cmdline
            cwd_in_project = self._same_or_child_path(cwd, project_root)
            if cmd_mentions_project or cwd_in_project:
                candidates.add(pid)

        await self._terminate_pids(candidates, "project preview server")

    async def _cleanup_optional_global_helpers(self) -> None:
        """Optionally kill stale global Claude/Chrome helpers after a run.

        These are disabled by default because multiple Claude Code sessions can run in
        parallel. Enable only on workers where one job owns the browser helper.
        """
        if os.name != "posix":
            return

        patterns: list[tuple[str, str]] = []
        if self._env_bool("CLAUDE_AGENT_CLEANUP_CHROME_DEVTOOLS", False):
            patterns.append(("chrome-devtools helper", "chrome-devtools-mcp"))
        if self._env_bool("CLAUDE_AGENT_CLEANUP_STALE_CLAUDE", False):
            patterns.append(("stale claude cli", "/usr/bin/claude -p"))

        if not patterns:
            return

        cleanup_user = self._cleanup_user()
        user_filter = f"-u {shlex.quote(cleanup_user)} " if cleanup_user else ""

        for label, pattern in patterns:
            command = f"pkill -TERM {user_filter}-f {shlex.quote(pattern)} || true"
            logger.info(f"[CLAUDE-AGENT] Optional cleanup: {command}")
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

    async def _cleanup_after_query(self) -> None:
        """Cleanup helpers that may survive Claude's final result."""
        await self._cleanup_project_serve_processes()
        await self._cleanup_optional_global_helpers()

    def _load_settings(self) -> dict[str, Any]:
        """Load Claude Code configuration from settings.json."""
        if not self.settings_path.exists():
            logger.debug(f"Settings file not found: {self.settings_path}")
            return {}

        try:
            with open(self.settings_path, "r") as f:
                settings = json.load(f)
                logger.info(f"Loaded settings from {self.settings_path}: {settings}")
                return settings
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not load settings from {self.settings_path}: {e}")
            return {}

    def _find_claude_cli(self) -> str:
        """
        Find the claude CLI executable.

        Returns:
            Path to claude CLI

        Raises:
            RuntimeError: If claude CLI is not found
        """
        # Use explicit path if provided
        if self.claude_path:
            if Path(self.claude_path).exists():
                logger.debug(f"Using explicit claude_path: {self.claude_path}")
                return self.claude_path
            raise RuntimeError(f"Claude CLI not found at specified path: {self.claude_path}")

        # Auto-detect via shutil.which
        claude_path = shutil.which("claude")
        if claude_path:
            logger.debug(f"Found claude CLI via shutil.which: {claude_path}")
            return claude_path

        # Common fallback paths
        common_paths = [
            "/usr/local/bin/claude",
            "/usr/bin/claude",
            Path.home() / ".local" / "bin" / "claude",
            Path.home() / ".npm-global" / "bin" / "claude",
        ]

        for path in common_paths:
            if Path(path).exists():
                logger.debug(f"Found claude CLI at fallback path: {path}")
                return str(path)

        logger.error("Claude CLI not found in any location")
        raise RuntimeError(
            "Claude CLI not found. Please install claude CLI or specify path via claude_path parameter. "
            "See: https://docs.anthropic.com/claude/docs/claude-cli"
        )

    def _extract_final_answer(self, all_chunks: list[str]) -> Optional[str]:
        """
        Extract final answer from accumulated text chunks using lightweight heuristics.

        Heuristics (in order of preference):
        1. Look for explicit answer markers ("Answer is:", "Result:", "Answer:")
        2. Look for short lines that look like answers (not reasoning-style sentences)
        3. Fall back to last line, never "" or "." or markdown syntax

        Args:
            all_chunks: List of all text chunks received

        Returns:
            The extracted final answer (never empty string, ".", or markdown syntax)
        """
        # Join with '\n' to preserve line structure for splitlines() logic
        full_text = "\n".join(all_chunks).strip()
        if not full_text:
            return None

        # Heuristic 1: If you see a clear "answer/result" phrase, grab what follows
        patterns = [
            r"\bThe answer is:\s*([^.!?]+[.!?]?)",
            r"\bAnswer:\s*([^.!?]+[.!?]?)",
            r"\bResult:\s*([^.!?]+[.!?]?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, full_text, re.IGNORECASE | re.DOTALL)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    return candidate

        # Heuristic 2: Look at last 1-3 lines; pick first that isn't a long reasoning sentence
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        if not lines:
            return None

        # Skip obvious reasoning starters
        reasoning_starters = [
            "the user is asking",
            "this is a simple",
            "this is a straightforward",
            "i should respond",
            "i need to",
            "let me",
            "per my",
            "i'll keep",
        ]

        # Skip markdown syntax and trivial lines
        markdown_syntax = ["```", "``", "---", "***", "___", "##", "###", "####"]

        for line in reversed(lines[-8:]):  # Check last 8 lines for better context
            line_lower = line.lower()
            
            # Skip reasoning starters
            if line_lower.startswith(tuple(reasoning_starters)):
                continue
            
            # Skip markdown syntax
            if line in markdown_syntax or line.strip() in markdown_syntax:
                continue
            
            # Skip lines that are only punctuation/symbols
            if all(c in "`~!@#$%^&*()_-+={}[]|\\:;\"'<>,.?/" for c in line.strip()):
                continue
            
            # Short lines that look like answers (30-150 chars is ideal)
            if 30 <= len(line) < 300:
                return line
            
            # For very short lines, make sure they're meaningful
            if len(line) < 30 and any(c.isalpha() for c in line) and " " in line:
                return line

        # Heuristic 3: Fallback to last meaningful line
        for line in reversed(lines):
            if line not in markdown_syntax and any(c.isalpha() for c in line):
                return line
        
        return lines[-1] if lines else None

    def _extract_token_usage(self, result_data: dict) -> Optional[dict]:
        """
        Extract token usage from a stream-json result message.

        Claude CLI stream-json output includes usage data in the result message:
        - input_tokens: Total input tokens (including cache)
        - output_tokens: Total output tokens
        - cache_creation_input_tokens: Tokens written to cache
        - cache_read_input_tokens: Tokens read from cache
        - cost_usd: Estimated cost in USD

        Args:
            result_data: Parsed JSON from a 'result' type stream message

        Returns:
            Dict with token usage metrics, or None if not available
        """
        # Try direct fields on the result data
        usage_fields = {
            "input_tokens": None,
            "output_tokens": None,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
            "cost_usd": None,
            "reasoning_tokens": None,
            "model": None,
        }

        found_any = False
        for field in usage_fields:
            if field in result_data:
                usage_fields[field] = result_data[field]
                found_any = True

        # Also check nested 'usage' object (some CLI versions use this)
        if not found_any:
            usage_obj = result_data.get("usage", {})
            if isinstance(usage_obj, dict):
                for field in usage_fields:
                    if field in usage_obj:
                        usage_fields[field] = usage_obj[field]
                        found_any = True

        # Model may also be at top-level of result message, not inside usage
        if not usage_fields.get("model"):
            usage_fields["model"] = result_data.get("model", "")

        if not found_any:
            return None

        # Calculate total if not provided directly
        input_tokens = usage_fields.get("input_tokens") or 0
        cache_creation = usage_fields.get("cache_creation_input_tokens") or 0
        cache_read = usage_fields.get("cache_read_input_tokens") or 0
        output_tokens = usage_fields.get("output_tokens") or 0
        reasoning_tokens = usage_fields.get("reasoning_tokens") or 0

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
            # input_tokens already includes cache_read/cache_creation — do NOT add them again
            "total_tokens": input_tokens + output_tokens,
            "cost_usd": usage_fields.get("cost_usd"),
            "reasoning_tokens": reasoning_tokens,
            "model": usage_fields.get("model", ""),
        }

    def _get_progress_message(self, elapsed: float) -> str:
        """Generate phase-appropriate progress message."""
        if elapsed < 30:
            return "🔍 Analyzing your request..."
        elif elapsed < 120:
            return "✨ Working on your changes..."
        elif elapsed < 300:
            return "🔧 Applying fixes and improvements..."
        elif elapsed < 600:
            return "⚙️ Processing complex task..."
        else:
            return "🎯 Almost there, finalizing..."

    async def __aenter__(self) -> "ClaudeCodeAgent":
        """Start the Claude Code Agent."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the Claude Code Agent."""
        await self.stop()

    async def start(self) -> None:
        """Initialize Claude Code Agent (no persistent process needed)."""
        if self._running:
            logger.debug("Agent already running, skipping start")
            return

        # Ensure repository path exists
        if not self.repo_path.exists():
            logger.error(f"Repository path does not exist: {self.repo_path}")
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")

        # Verify claude CLI is available
        self._find_claude_cli()

        self._running = True
        logger.info(f"Agent started: repo_path={self.repo_path}")

    async def stop(self) -> None:
        """Stop the Claude Code Agent (no persistent process to stop)."""
        self._running = False
        logger.info("Agent stopped")

    async def cancel(self) -> bool:
        """
        Cancel the currently running query by killing the entire process group.

        Uses SIGKILL on the process group (not just the parent) to ensure
        all child processes (Claude CLI, inference workers) are terminated.

        Returns:
            True if a process was killed, False if no process was running
        """
        if self._current_process and self._current_process.returncode is None:
            pid = self._current_process.pid
            self._cancelled = True  # Mark as cancelled before killing
            logger.info(f"[CLAUDE-AGENT] Cancelling query - killing process group (PID: {pid})")
            try:
                # Kill the entire process group (parent + all children)
                os.killpg(pid, signal.SIGKILL)
                logger.info(f"[CLAUDE-AGENT] Sent SIGKILL to process group {pid}")
            except ProcessLookupError:
                logger.info(f"[CLAUDE-AGENT] Process group {pid} already terminated")
            except PermissionError:
                logger.warning(f"[CLAUDE-AGENT] Permission denied killing process group {pid}, falling back to single process kill")
                try:
                    self._current_process.kill()
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] Error killing process group: {e}")
                try:
                    self._current_process.kill()
                except Exception:
                    pass

            try:
                await asyncio.wait_for(self._current_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning(f"[CLAUDE-AGENT] Process {pid} did not exit after 5s")
            except Exception:
                pass

            self._current_process = None
            await self._cleanup_after_query()
            return True
        self._cancelled = False  # Reset if nothing to cancel
        logger.info("[CLAUDE-AGENT] Cancel called but no running process found")
        return False

    async def query(self, prompt: str, timeout: float = 1200.0) -> Optional[str]:
        """
        Send a query to Claude Code and return the final answer.

        Args:
            prompt: The text prompt to send to Claude Code
            timeout: Maximum time to wait for a response in seconds (default: 20 minutes)

        Returns:
            The final answer from Claude Code (extracted from response using heuristics), or None if no response

        Raises:
            RuntimeError: If the agent is not running
            asyncio.TimeoutError: If the query takes longer than timeout
        """
        if not self._running:
            logger.error("Query called but agent not running")
            raise RuntimeError("ClaudeCodeAgent is not running. Call await start() or use as an async context manager.")

        logger.info(f"Starting query: prompt='{prompt[:100]}{'...' if len(prompt) > 100 else ''}', timeout={timeout}s")
        start_time = datetime.now()

        # Generate a per-query session ID for wrapper usage correlation.
        # Injected into the prompt's <DREAMPILOT_WORKFLOW_META> block so the
        # wrapper sees it in every API call Claude CLI makes. The wrapper
        # tags usage records with this ID, and we fetch them after the query.
        # This is concurrency-safe: each query gets a unique ID.
        _session_id = f"qry_{uuid.uuid4().hex[:16]}"
        _injected_prompt = self._inject_usage_session(prompt, _session_id)

        try:
            result = await asyncio.wait_for(
                self._execute_query(_injected_prompt),
                timeout=timeout,
            )
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"Query completed in {elapsed:.2f}s: response='{result[:100] if result else None}{'...' if result and len(result) > 100 else ''}'")

            # ── Side-channel token usage from wrapper ──
            # Claude CLI strips custom usage fields from the proxy response,
            # so we fetch real usage directly from the wrapper's usage buffer.
            await self._fetch_usage_session(_session_id)

            return result
        except asyncio.TimeoutError:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error(f"Query timed out after {elapsed:.2f}s (limit: {timeout}s)")
            raise

    @staticmethod
    def _inject_usage_session(prompt: str, session_id: str) -> str:
        """Inject usage_session_id into the prompt's <DREAMPILOT_WORKFLOW_META> block.

        The wrapper extracts metadata from this block on every API call Claude
        CLI makes. By injecting a unique session ID here, the wrapper can tag
        usage records for this specific query — even with concurrent queries.

        If no meta block exists (e.g., plain text prompts), the prompt is
        returned unchanged and usage tracking falls back to global /usage/since.
        """
        if not session_id:
            return prompt
        tag = "usage_session_id"
        meta_start = "<DREAMPILOT_WORKFLOW_META>"
        meta_end = "</DREAMPILOT_WORKFLOW_META>"
        if meta_start not in prompt:
            return prompt
        # Try JSON insertion: find the last closing brace before META_END and
        # inject our field. This handles both indented and compact JSON.
        end_idx = prompt.index(meta_end)
        last_brace = prompt.rfind("}", 0, end_idx)
        if last_brace == -1:
            return prompt
        # Determine indentation from the line containing the closing brace
        line_start = prompt.rfind("\n", 0, last_brace) + 1
        indent = prompt[line_start:last_brace]
        injection = f',\n{indent}"{tag}": "{session_id}"'
        return prompt[:last_brace] + injection + prompt[last_brace:]

    async def _fetch_usage_session(self, session_id: str) -> None:
        """
        Fetch real token usage from the wrapper's side-channel endpoint.

        Uses session-ID correlation: each query gets a unique ID that's
        embedded in the ANTHROPIC_API_KEY env var. The wrapper tags every
        usage record with this ID, so we only get THIS query's usage —
        even when multiple projects query concurrently.
        """
        wrapper_url = os.environ.get("WRAPPER_BASE_URL", "http://127.0.0.1:7861").rstrip("/")
        endpoint = f"{wrapper_url}/usage/session/{session_id}"

        def _do_get() -> dict:
            try:
                req = urllib.request.Request(endpoint, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read().decode())
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] Could not fetch wrapper usage from {endpoint}: {e}")
                return {}

        data = await asyncio.get_event_loop().run_in_executor(None, _do_get)
        totals = data.get("totals") if data else None
        # Extract model name from totals first, then fall back to records
        model_name = ""
        if totals and totals.get("model"):
            model_name = totals["model"]
        else:
            records = data.get("records") if data else None
            if records:
                model_name = records[-1].get("model", "")
        if totals:
            self._last_token_usage = {
                "input_tokens": totals.get("input_tokens", 0),
                "output_tokens": totals.get("output_tokens", 0),
                "cache_read_input_tokens": totals.get("cache_read_input_tokens", 0),
                "cache_creation_input_tokens": 0,
                "reasoning_tokens": totals.get("reasoning_tokens", 0),
                "cost_usd": totals.get("cost_usd", 0),
                "model": model_name,
                "has_writes": totals.get("has_writes", False),
            }
            logger.info(
                f"[CLAUDE-AGENT] Wrapper usage (session={session_id}): "
                f"input={self._last_token_usage['input_tokens']}, "
                f"output={self._last_token_usage['output_tokens']}, "
                f"cache_read={self._last_token_usage['cache_read_input_tokens']}, "
                f"reasoning={self._last_token_usage['reasoning_tokens']}, "
                f"cost=${self._last_token_usage['cost_usd']:.6f}, "
                f"requests={totals.get('request_count', 0)}, "
                f"has_writes={self._last_token_usage['has_writes']}"
            )
        else:
            logger.warning(f"[CLAUDE-AGENT] Wrapper usage endpoint returned no totals (endpoint={endpoint})")

    async def _execute_query(self, prompt: str) -> Optional[str]:
        """
        Execute a query by calling claude CLI directly.

        This internal method:
        1. Runs `claude -p "prompt"` as a subprocess
        2. Reads stdout and stderr as plain text lines
        3. Streams lines via on_text callback (if provided)
        4. Applies answer extraction heuristics
        5. Returns only the final answer

        Note: This does NOT use acpx or ACP. Output is treated as plain text.
        """
        # Find claude CLI
        claude_path = self._find_claude_cli()

        # Build environment from settings
        env = os.environ.copy()
        
        # Ensure PATH includes common locations for MCP tools
        if "PATH" in env:
            paths_to_add = ["/usr/local/bin", "/usr/bin", "/root/.npm-global/bin"]
            for p in paths_to_add:
                if p not in env["PATH"]:
                    env["PATH"] = f"{p}:{env['PATH']}"

        # Apply any custom environment variables from config
        if "env" in self._settings:
            env.update(self._settings["env"])
            logger.debug(f"Applied custom env vars: {self._settings['env']}")

        # Build command: claude -p "prompt" --dangerously-skip-permissions
        # Using -p for one-shot prompt mode (non-interactive)
        command = [claude_path]

        # Apply model configuration if present in settings (as CLI flag, not env var)
        if "model" in self._settings:
            command.extend(["--model", self._settings["model"]])
            logger.debug(f"Using model from settings: {self._settings['model']}")

        # Resume existing session if available (warm cache, cheaper tokens)
        if self._last_session_id:
            command.extend(["--resume", self._last_session_id])
            logger.info(f"[CLAUDE-AGENT] Resuming session: {self._last_session_id}")

        # Add prompt flag first
        command.extend(["-p", prompt])

        # Add auto-approve flag AFTER prompt (matches working CLI format)
        command.append("--dangerously-skip-permissions")
        logger.debug("Auto-approve enabled: --dangerously-skip-permissions")
        
        # Add stream-json output format for real-time tool call streaming
        command.extend(["--output-format", "stream-json"])
        command.append("--verbose")
        logger.debug("Output format: stream-json with verbose")

        # Check if running as root - need to run as non-root user for --dangerously-skip-permissions
        is_root = os.geteuid() == 0 if hasattr(os, 'geteuid') else False
        
        # Wrap with sudo -u if running as root
        # Use -E to preserve environment and -H to set HOME to target user
        if is_root:
            run_as_user = os.environ.get("CLAUDE_RUN_AS_USER", "dreampilot")
            command = ["sudo", "-E", "-H", "-u", run_as_user, *command]
            logger.info(f"Running as root - wrapped command with sudo -E -H -u {run_as_user}")

        # Log full command (truncate prompt for readability)
        cmd_display = ' '.join(command)
        if len(cmd_display) > 200:
            cmd_display = cmd_display[:200] + '...(truncated)'
        logger.info(f"[CLAUDE-AGENT] Executing: {cmd_display}")
        logger.info(f"[CLAUDE-AGENT] Working directory: {self.repo_path}")

        # Run subprocess with cwd set to repo_path
        process = None
        process_group_id: Optional[int] = None

        try:
            # Create subprocess with larger buffer limit for screenshot data
            # Default limit is 64KB which is too small for base64 screenshots
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
                limit=10 * 1024 * 1024,  # 10MB limit for large JSON lines
                start_new_session=True  # New process group so we can kill entire tree
            )
            self._current_process = process  # Store for cancellation
            process_group_id = process.pid
            logger.debug(f"Subprocess started with PID: {process.pid}")

            # Accumulate plain text lines from stdout (stderr kept separate)
            all_chunks = []
            stderr_lines = []
            query_start_time = datetime.now()
            self._last_token_usage = None  # Reset token usage for new query
            last_progress_time = query_start_time
            result_seen = False
            terminated_after_result = False
            exit_on_result = os.environ.get("CLAUDE_AGENT_EXIT_ON_RESULT", "1").lower() not in {"0", "false", "no"}
            result_exit_grace = float(os.environ.get("CLAUDE_AGENT_RESULT_EXIT_GRACE_SECONDS", "2.0"))
            
            # Read stdout line by line (plain text, not JSON-RPC) with progress updates
            while True:
                try:
                    # Use timeout-based reading for progress updates
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.progress_interval
                    )
                    
                    if not line:
                        break

                    # Decode and strip the line
                    line_text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                    
                    # Skip very long lines (likely screenshot data or large JSON)
                    # These would be base64 encoded images in stream-json format
                    if len(line_text) > 100000:  # 100KB threshold
                        logger.debug(f"[CLAUDE-AGENT] Skipping large line ({len(line_text)} chars)")
                        continue

                    # Skip empty lines
                    if not line_text.strip():
                        continue

                    # Parse stream-json format to extract meaningful content
                    tool_name = None
                    text_content = None
                    result_text = None

                    try:
                        data = json.loads(line_text)
                        msg_type = data.get("type", "")

                        if msg_type == "assistant":
                            content = data.get("message", {}).get("content", [])
                            for block in content:
                                block_type = block.get("type", "")
                                if block_type == "tool_use":
                                    tool_name = block.get("name", "")
                                    logger.debug(f"[CLAUDE-AGENT] Tool call: {tool_name}")
                                elif block_type == "text":
                                    text_content = block.get("text", "").strip()

                        elif msg_type == "result":
                            result_seen = True
                            result_text = data.get("result", "").strip()
                            session_id = data.get("session_id")
                            if session_id:
                                self._last_session_id = session_id
                                logger.info(f"[CLAUDE-AGENT] Session captured from result: {session_id}")
                            if result_text:
                                all_chunks.append(result_text)
                                logger.info(f"[CLAUDE-AGENT] Result: {result_text[:100]}")

                            # Extract token usage from result message
                            token_usage = self._extract_token_usage(data)
                            logger.debug(f"[CLAUDE-AGENT] Raw result message: {json.dumps({k: v for k, v in data.items() if k != 'result'}, ensure_ascii=False)[:500]}")
                            if token_usage:
                                self._last_token_usage = token_usage
                                cost = token_usage.get('cost_usd') or 0
                                logger.info(
                                    f"[CLAUDE-AGENT] Token usage: "
                                    f"input={token_usage.get('input_tokens')}, "
                                    f"output={token_usage.get('output_tokens')}, "
                                    f"cache_read={token_usage.get('cache_read_input_tokens')}, "
                                    f"cache_creation={token_usage.get('cache_creation_input_tokens')}, "
                                    f"reasoning={token_usage.get('reasoning_tokens')}, "
                                    f"total={token_usage.get('total_tokens')}, "
                                    f"cost=${cost:.4f}"
                                )
                            else:
                                logger.warning(f"[CLAUDE-AGENT] No token usage found in result message, raw keys: {list(data.keys())}")

                            if exit_on_result:
                                logger.info("[CLAUDE-AGENT] Final stream-json result received; stopping stdout read loop")
                                break

                        elif msg_type == "system":
                            # Capture session_id from system init message
                            session_id = data.get("session_id")
                            if session_id:
                                self._last_session_id = session_id
                                logger.info(f"[CLAUDE-AGENT] Session started: {session_id}")
                            continue

                    except (json.JSONDecodeError, AttributeError):
                        # Not JSON - plain text line, use as-is
                        text_content = line_text

                    # Send tool name to on_text for keyword mapping
                    if tool_name and self.on_text:
                        logger.debug(f"[CLAUDE-AGENT] Sending tool to on_text: {tool_name}")
                        if asyncio.iscoroutinefunction(self.on_text):
                            await self.on_text(f"TOOL:{tool_name}")
                        else:
                            self.on_text(f"TOOL:{tool_name}")

                    # Send text content to on_text
                    if text_content and self.on_text:
                        logger.debug(f"[CLAUDE-AGENT] Sending text to on_text: {text_content[:80]}")
                        if asyncio.iscoroutinefunction(self.on_text):
                            await self.on_text(text_content)
                        else:
                            self.on_text(text_content)
                    
                    last_progress_time = datetime.now()
                    
                except asyncio.TimeoutError:
                    # Timeout - send progress update via on_progress (NOT on_text - not persisted to DB)
                    elapsed = (datetime.now() - query_start_time).total_seconds()
                    progress_msg = self._get_progress_message(elapsed)
                    logger.info(f"[CLAUDE-AGENT] Progress: {progress_msg}")
                    
                    # Use on_progress callback for UI-only updates (not persisted to database)
                    if self.on_progress:
                        logger.info(f"[CLAUDE-AGENT] Calling on_progress callback")
                        if asyncio.iscoroutinefunction(self.on_progress):
                            await self.on_progress(progress_msg)
                        else:
                            self.on_progress(progress_msg)
                        logger.info(f"[CLAUDE-AGENT] on_progress callback returned")
                    else:
                        logger.debug(f"[CLAUDE-AGENT] No on_progress callback - progress not sent to UI")
                    
                    # Continue reading
                    continue

            if result_seen and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=result_exit_grace)
                    logger.info("[CLAUDE-AGENT] Subprocess exited after final result")
                except asyncio.TimeoutError:
                    terminated_after_result = True
                    pid = process.pid
                    logger.warning(
                        f"[CLAUDE-AGENT] Subprocess still running {result_exit_grace}s after final result; "
                        f"terminating process group {pid}"
                    )
                    try:
                        os.killpg(pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    except Exception as e:
                        logger.warning(f"[CLAUDE-AGENT] Could not SIGTERM process group {pid}: {e}; terminating process")
                        try:
                            process.terminate()
                        except ProcessLookupError:
                            pass

                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"[CLAUDE-AGENT] SIGTERM did not stop process group {pid}; sending SIGKILL")
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        except Exception as e:
                            logger.warning(f"[CLAUDE-AGENT] Could not SIGKILL process group {pid}: {e}; killing process")
                            try:
                                process.kill()
                            except ProcessLookupError:
                                pass
                        await process.wait()

            # Read any stderr output (kept separate from answer chunks)
            stderr_data = await process.stderr.read()
            if stderr_data:
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                for line in stderr_text.splitlines():
                    line = line.strip()
                    if line:
                        stderr_lines.append(line)
                if stderr_lines:
                    logger.info(f"[CLAUDE-AGENT] Received stderr ({len(stderr_lines)} lines): {' '.join(stderr_lines[:5])}")
            else:
                logger.info(f"[CLAUDE-AGENT] No stderr output")

            # Wait for process to complete
            returncode = await process.wait()
            logger.info(f"[CLAUDE-AGENT] Subprocess exited with code: {returncode}")
            logger.info(f"[CLAUDE-AGENT] Total chunks received: {len(all_chunks)}")
            if all_chunks:
                logger.info(f"[CLAUDE-AGENT] Last 3 chunks: {all_chunks[-3:]}")

            # Check for errors (skip if this was a user-initiated cancel)
            if self._cancelled:
                self._cancelled = False  # Reset flag
                logger.info(f"[CLAUDE-AGENT] Query cancelled by user (exit code {returncode})")
                return None
            if returncode != 0 and not (result_seen and terminated_after_result and all_chunks):
                error_msg = f"Claude CLI exited with code {returncode}"
                if stderr_lines:
                    error_msg += f": {' '.join(stderr_lines[-3:])}"
                elif all_chunks:
                    error_msg += f": {' '.join(all_chunks[-3:])}"
                logger.error(f"Query failed: {error_msg}")
                raise RuntimeError(error_msg)

            # No output received
            if not all_chunks:
                logger.error(f"[CLAUDE-AGENT] Query returned no output! returncode={returncode}, stderr={stderr_lines}")
                return None

            # Extract final answer using heuristics
            logger.debug(f"Extracting answer from {len(all_chunks)} chunks")
            answer = self._extract_final_answer(all_chunks)
            logger.info(f"Extracted answer: {answer[:200] if answer else None}{'...' if answer and len(answer) > 200 else ''}")
            return answer

        except asyncio.TimeoutError:
            # Kill process on timeout
            logger.error("Query timeout - killing subprocess")
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            raise

        finally:
            # Ensure process is cleaned up
            self._current_process = None
            if process and process.returncode is None:
                logger.debug("Cleaning up subprocess in finally block")
                pid = process.pid
                try:
                    os.killpg(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except Exception as e:
                    logger.warning(f"[CLAUDE-AGENT] Could not SIGTERM process group {pid} in finally: {e}; killing process")
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass

                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning(f"[CLAUDE-AGENT] SIGTERM did not stop process group {pid} in finally; sending SIGKILL")
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except Exception as e:
                        logger.warning(f"[CLAUDE-AGENT] Could not SIGKILL process group {pid} in finally: {e}; killing process")
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    await process.wait()
            await self._terminate_process_group(process_group_id, "current Claude")
            await self._cleanup_after_query()

    @property
    def is_running(self) -> bool:
        """Check if the agent is currently running."""
        return self._running

    @property
    def last_token_usage(self) -> Optional[dict]:
        """Get token usage from the most recent query."""
        return self._last_token_usage

    @property
    def last_session_id(self) -> Optional[str]:
        """Get session ID from the most recent query (for --resume on next call)."""
        return self._last_session_id


@asynccontextmanager
async def claude_code_agent(
    repo_path: str,
    settings_path: Optional[str] = None,
    on_text: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    claude_path: Optional[str] = None,
) -> AsyncIterator[ClaudeCodeAgent]:
    """
    Convenience function for creating a Claude Code Agent context manager.

    Args:
        repo_path: Path to repository/workspace to work in
        settings_path: Optional path to Claude Code settings
        on_text: Optional callback for streaming text (content - persisted to DB)
        on_progress: Optional callback for progress updates (UI only - NOT persisted to DB)
        claude_path: Optional path to claude CLI

    Example:
        async with claude_code_agent("/path/to/repo") as agent:
            response = await agent.query("Write a hello.py")
            print(response)
    """
    agent = ClaudeCodeAgent(repo_path, settings_path, on_text, on_progress, claude_path)
    await agent.start()
    try:
        yield agent
    finally:
        await agent.stop()


# ============================================================================
# Example Usage
# ============================================================================

async def main() -> None:
    """Example usage of ClaudeCodeAgent."""

    # Example 1: Basic usage with context manager
    print("Example 1: Basic usage")
    print("-" * 50)

    async with ClaudeCodeAgent(".") as agent:
        response = await agent.query("List files in the current directory")
        if response:
            print(response)
        print()

    # Example 2: With streaming callback
    print("\nExample 2: With streaming callback")
    print("-" * 50)

    def stream_callback(text: str) -> None:
        """Called as text arrives from Claude CLI."""
        print(f"[Stream]: {text[:100]}...")  # Print first 100 chars

    async with ClaudeCodeAgent(".", on_text=stream_callback) as agent:
        response = await agent.query("Create a simple README.md with a project description")
        if response:
            print(f"\n[Complete response received, {len(response)} chars]")
        print()

    # Example 3: Using the convenience function
    print("\nExample 3: Using the convenience function")
    print("-" * 50)

    async with claude_code_agent(".") as agent:
        # Run multiple queries in sequence
        for prompt in [
            "What files are in this repo?",
            "Create a hello.py file that prints 'Hello, World'",
        ]:
            print(f"\nQuery: {prompt}")
            response = await agent.query(prompt)
            if response:
                print(f"Response: {response[:200]}...")

    print("\nAll examples completed!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
