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
import sys
import re
import shutil
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
        claude_path: Optional[str] = None,
        progress_interval: float = 30.0,
    ):
        """
        Initialize Claude Code Agent.

        Args:
            repo_path: Path to repository/workspace to work in
            settings_path: Optional path to Claude Code settings (default: ~/.claude/settings.json)
            on_text: Optional callback for streaming text as it arrives (for logging/UI only)
            claude_path: Optional path to claude CLI (default: auto-detect via shutil.which)
            progress_interval: Seconds between progress updates while waiting (default: 30s, env: CLAUDE_PROGRESS_INTERVAL_SECONDS)
        
        Note: Auto-approve is enabled via --dangerously-skip-permissions (runs as non-root via sudo -u)
        """
        self.repo_path = Path(repo_path).resolve()
        self.settings_path = Path(settings_path or Path.home() / ".claude" / "settings.json")
        self.on_text = on_text
        self.claude_path = claude_path
        
        # Progress interval (from env or param, default 30s)
        self.progress_interval = float(os.environ.get("CLAUDE_PROGRESS_INTERVAL_SECONDS", progress_interval))
        logger.info(f"[CLAUDE-AGENT] progress_interval={self.progress_interval}s, on_text={'set' if on_text else 'NOT SET'}")

        # Internal state
        self._running = False

        # Load Claude Code settings
        self._settings = self._load_settings()

        logger.info(f"ClaudeCodeAgent initialized: repo_path={self.repo_path}, settings_path={self.settings_path}")

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

    async def query(self, prompt: str, timeout: float = 300.0) -> Optional[str]:
        """
        Send a query to Claude Code and return the final answer.

        Args:
            prompt: The text prompt to send to Claude Code
            timeout: Maximum time to wait for a response in seconds (default: 5 minutes)

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

        try:
            result = await asyncio.wait_for(
                self._execute_query(prompt),
                timeout=timeout,
            )
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"Query completed in {elapsed:.2f}s: response='{result[:100] if result else None}{'...' if result and len(result) > 100 else ''}'")
            return result
        except asyncio.TimeoutError:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error(f"Query timed out after {elapsed:.2f}s (limit: {timeout}s)")
            raise

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

        # Apply any custom environment variables from config
        if "env" in self._settings:
            env.update(self._settings["env"])
            logger.debug(f"Applied custom env vars: {self._settings['env']}")

        # Build command: claude [--model <model>] -p "prompt"
        # Using -p for one-shot prompt mode (non-interactive)
        command = [claude_path]

        # Apply model configuration if present in settings (as CLI flag, not env var)
        if "model" in self._settings:
            command.extend(["--model", self._settings["model"]])
            logger.debug(f"Using model from settings: {self._settings['model']}")

        # Check if running as root - need to run as non-root user for --dangerously-skip-permissions
        is_root = os.geteuid() == 0 if hasattr(os, 'geteuid') else False
        run_as_user = os.environ.get("CLAUDE_RUN_AS_USER", "dreampilot") if is_root else None
        
        if is_root and run_as_user:
            logger.info(f"Running as root - will execute Claude CLI as user '{run_as_user}'")
        
        # Add auto-approve flag (works when running as non-root via sudo -u)
        command.append("--dangerously-skip-permissions")
        logger.debug("Auto-approve enabled: --dangerously-skip-permissions")

        command.extend(["-p", prompt])

        # Wrap with sudo -u if running as root
        if run_as_user:
            command = ["sudo", "-u", run_as_user, *command]
            logger.debug(f"Wrapped command with sudo -u {run_as_user}")

        logger.debug(f"Executing command: {' '.join(command[:3])}... (prompt truncated)")
        logger.debug(f"Working directory: {self.repo_path}")

        # Run subprocess with cwd set to repo_path
        process = None

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
            )
            logger.debug(f"Subprocess started with PID: {process.pid}")

            # Accumulate plain text lines from stdout (stderr kept separate)
            all_chunks = []
            stderr_lines = []
            query_start_time = datetime.now()
            last_progress_time = query_start_time
            
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

                    # Skip empty lines
                    if not line_text.strip():
                        continue

                    # Accumulate the line
                    all_chunks.append(line_text)
                    logger.debug(f"Received stdout line ({len(line_text)} chars): {line_text[:100]}{'...' if len(line_text) > 100 else ''}")

                    # Stream to callback if provided
                    if self.on_text:
                        logger.info(f"[CLAUDE-AGENT] Calling on_text callback with {len(line_text)} chars")
                        if asyncio.iscoroutinefunction(self.on_text):
                            await self.on_text(line_text)
                        else:
                            self.on_text(line_text)
                        logger.info(f"[CLAUDE-AGENT] on_text callback returned")
                    else:
                        logger.warning(f"[CLAUDE-AGENT] No on_text callback configured!")
                    
                    last_progress_time = datetime.now()
                    
                except asyncio.TimeoutError:
                    # Timeout - send progress update if callback exists
                    elapsed = (datetime.now() - query_start_time).total_seconds()
                    progress_msg = f"⏳ Still working... ({int(elapsed)}s elapsed)"
                    logger.info(f"[CLAUDE-AGENT] Progress timeout: {progress_msg}")
                    
                    if self.on_text:
                        logger.info(f"[CLAUDE-AGENT] Calling on_text with progress message")
                        if asyncio.iscoroutinefunction(self.on_text):
                            await self.on_text(progress_msg)
                        else:
                            self.on_text(progress_msg)
                        logger.info(f"[CLAUDE-AGENT] Progress callback returned")
                    else:
                        logger.warning(f"[CLAUDE-AGENT] No on_text callback - progress not sent!")
                    
                    # Continue reading
                    continue

            # Read any stderr output (kept separate from answer chunks)
            stderr_data = await process.stderr.read()
            if stderr_data:
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                for line in stderr_text.splitlines():
                    line = line.strip()
                    if line:
                        stderr_lines.append(line)
                if stderr_lines:
                    logger.debug(f"Received stderr ({len(stderr_lines)} lines): {' '.join(stderr_lines[:3])}")

            # Wait for process to complete
            returncode = await process.wait()
            logger.debug(f"Subprocess exited with code: {returncode}")

            # Check for errors
            if returncode != 0:
                error_msg = f"Claude CLI exited with code {returncode}"
                if stderr_lines:
                    error_msg += f": {' '.join(stderr_lines[-3:])}"
                elif all_chunks:
                    error_msg += f": {' '.join(all_chunks[-3:])}"
                logger.error(f"Query failed: {error_msg}")
                raise RuntimeError(error_msg)

            # No output received
            if not all_chunks:
                logger.warning("Query returned no output")
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
            if process and process.returncode is None:
                logger.debug("Cleaning up subprocess in finally block")
                process.kill()
                await process.wait()

    @property
    def is_running(self) -> bool:
        """Check if the agent is currently running."""
        return self._running


@asynccontextmanager
async def claude_code_agent(
    repo_path: str,
    settings_path: Optional[str] = None,
    on_text: Optional[Callable[[str], None]] = None,
    claude_path: Optional[str] = None,
) -> AsyncIterator[ClaudeCodeAgent]:
    """
    Convenience function for creating a Claude Code Agent context manager.

    Args:
        repo_path: Path to repository/workspace to work in
        settings_path: Optional path to Claude Code settings
        on_text: Optional callback for streaming text
        claude_path: Optional path to claude CLI

    Example:
        async with claude_code_agent("/path/to/repo") as agent:
            response = await agent.query("Write a hello.py")
            print(response)
    """
    agent = ClaudeCodeAgent(repo_path, settings_path, on_text, claude_path, auto_approve)
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
