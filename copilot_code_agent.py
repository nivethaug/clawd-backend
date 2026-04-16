#!/usr/bin/env python3
"""
Copilot Code Agent - A Python wrapper for GitHub Copilot CLI.

This module provides a clean, asynchronous interface to Copilot CLI by running
the `copilot` (or `gh copilot`) command as a subprocess.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

# Configure logger
logger = logging.getLogger(__name__)


def configure_logging(
    level: int = logging.INFO,
    format_string: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    log_file: Optional[str] = None,
) -> None:
    """
    Configure logging for CopilotCodeAgent.

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


class CopilotCodeAgent:
    """
    An async context manager that runs Copilot queries via CLI.

    Example:
        async with CopilotCodeAgent("/path/to/repo") as agent:
            response = await agent.query("Write a hello.py")
            print(response)
    """

    def __init__(
        self,
        repo_path: str,
        settings_path: Optional[str] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        copilot_path: Optional[str] = None,
        progress_interval: float = 30.0,
    ):
        """
        Initialize Copilot Code Agent.

        Args:
            repo_path: Path to repository/workspace to work in
            settings_path: Optional path to Copilot agent settings
                (default: ~/.copilot/settings.json)
            on_text: Optional callback for streaming text as it arrives
            on_progress: Optional callback for progress updates
            copilot_path: Optional explicit path to copilot CLI
            progress_interval: Seconds between progress updates while waiting
        """
        self.repo_path = Path(repo_path).resolve()
        self.settings_path = Path(settings_path or Path.home() / ".copilot" / "settings.json")
        self.on_text = on_text
        self.on_progress = on_progress
        self.copilot_path = copilot_path
        self.progress_interval = float(
            os.environ.get("COPILOT_PROGRESS_INTERVAL_SECONDS", progress_interval)
        )
        logger.info(
            "[COPILOT-AGENT] progress_interval=%ss, on_text=%s, on_progress=%s",
            self.progress_interval,
            "set" if on_text else "NOT SET",
            "set" if on_progress else "NOT SET",
        )

        # Internal state
        self._running = False
        self._current_process: Optional[asyncio.subprocess.Process] = None
        self._command_prefix: Optional[list[str]] = None

        # Load settings
        self._settings = self._load_settings()

        logger.info(
            "CopilotCodeAgent initialized: repo_path=%s, settings_path=%s",
            self.repo_path,
            self.settings_path,
        )

    def _load_settings(self) -> dict[str, Any]:
        """Load Copilot configuration from settings.json."""
        if not self.settings_path.exists():
            logger.debug("Settings file not found: %s", self.settings_path)
            return {}

        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
                logger.info("Loaded settings from %s: %s", self.settings_path, settings)
                return settings
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("Could not load settings from %s: %s", self.settings_path, exc)
            return {}

    def _resolve_copilot_command_prefix(self) -> list[str]:
        """
        Resolve the Copilot CLI command prefix.

        Priority:
        1. Explicit copilot_path
        2. `copilot` executable in PATH
        3. `gh copilot` via GitHub CLI
        """
        if self.copilot_path:
            path = Path(self.copilot_path)
            if path.exists():
                logger.debug("Using explicit copilot_path: %s", self.copilot_path)
                return [self.copilot_path]
            raise RuntimeError(f"Copilot CLI not found at specified path: {self.copilot_path}")

        copilot_path = shutil.which("copilot")
        if copilot_path:
            logger.debug("Found copilot CLI via shutil.which: %s", copilot_path)
            return [copilot_path]

        gh_path = shutil.which("gh")
        if gh_path:
            logger.debug("Found gh CLI via shutil.which: %s", gh_path)
            return [gh_path, "copilot"]

        common_paths = [
            "/usr/local/bin/copilot",
            "/usr/bin/copilot",
            str(Path.home() / ".local" / "bin" / "copilot"),
            str(Path.home() / ".npm-global" / "bin" / "copilot"),
        ]
        for path in common_paths:
            if Path(path).exists():
                logger.debug("Found copilot CLI at fallback path: %s", path)
                return [path]

        raise RuntimeError(
            "Copilot CLI not found. Install Copilot CLI (or gh with copilot extension), "
            "or provide copilot_path."
        )

    def _extract_final_answer(self, all_chunks: list[str]) -> Optional[str]:
        """
        Extract final answer from accumulated chunks using lightweight heuristics.
        """
        full_text = "\n".join(all_chunks).strip()
        if not full_text:
            return None

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

        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        if not lines:
            return None

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
        markdown_syntax = ["```", "``", "---", "***", "___", "##", "###", "####"]

        for line in reversed(lines[-8:]):
            line_lower = line.lower()
            if line_lower.startswith(tuple(reasoning_starters)):
                continue
            if line in markdown_syntax or line.strip() in markdown_syntax:
                continue
            if all(c in "`~!@#$%^&*()_-+={}[]|\\:;\"'<>,.?/" for c in line.strip()):
                continue
            if 30 <= len(line) < 300:
                return line
            if len(line) < 30 and any(c.isalpha() for c in line) and " " in line:
                return line

        for line in reversed(lines):
            if line not in markdown_syntax and any(c.isalpha() for c in line):
                return line

        return lines[-1] if lines else None

    def _get_progress_message(self, elapsed: float) -> str:
        """Generate phase-appropriate progress message."""
        if elapsed < 30:
            return "🔍 Analyzing your request..."
        if elapsed < 120:
            return "✨ Working on your changes..."
        if elapsed < 300:
            return "🔧 Applying fixes and improvements..."
        if elapsed < 600:
            return "⚙️ Processing complex task..."
        return "🎯 Almost there, finalizing..."

    def _build_query_command(self, prompt: str) -> list[str]:
        """
        Build full CLI command for one-shot query execution.

        Settings supported in settings file:
        - model: string
        - subcommand: string or list[str] (default: none)
        - prompt_flag: string (default: "-p")
        - flags: list[str]
        """
        if not self._command_prefix:
            self._command_prefix = self._resolve_copilot_command_prefix()

        command = list(self._command_prefix)

        # Most copilot CLIs accept non-interactive prompt directly via `-p`.
        # Optional subcommand can be injected by settings/env when needed.
        subcommand = self._settings.get("subcommand", os.environ.get("COPILOT_SUBCOMMAND", ""))
        if isinstance(subcommand, str) and subcommand.strip():
            command.extend(subcommand.strip().split())
        elif isinstance(subcommand, list):
            command.extend(str(part) for part in subcommand)

        model = self._settings.get("model")
        if model:
            command.extend(["--model", str(model)])

        flags = self._settings.get("flags", [])
        if isinstance(flags, list):
            command.extend(str(flag) for flag in flags)

        prompt_flag = self._settings.get("prompt_flag", os.environ.get("COPILOT_PROMPT_FLAG", "-p"))
        command.extend([str(prompt_flag), prompt])

        return command

    async def __aenter__(self) -> "CopilotCodeAgent":
        """Start the Copilot Code Agent."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the Copilot Code Agent."""
        await self.stop()

    async def start(self) -> None:
        """Initialize Copilot Code Agent."""
        if self._running:
            logger.debug("Agent already running, skipping start")
            return

        if not self.repo_path.exists():
            logger.error("Repository path does not exist: %s", self.repo_path)
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")

        self._command_prefix = self._resolve_copilot_command_prefix()
        self._running = True
        logger.info("Agent started: repo_path=%s", self.repo_path)

    async def stop(self) -> None:
        """Stop the Copilot Code Agent."""
        self._running = False
        logger.info("Agent stopped")

    async def cancel(self) -> bool:
        """
        Cancel the currently running query by killing the entire process group.

        Returns:
            True if a process was killed, False if no process was running.
        """
        if self._current_process and self._current_process.returncode is None:
            pid = self._current_process.pid
            logger.info("[COPILOT-AGENT] Cancelling query - killing process group (PID: %s)", pid)
            try:
                os.killpg(pid, signal.SIGKILL)
                logger.info("[COPILOT-AGENT] Sent SIGKILL to process group %s", pid)
            except ProcessLookupError:
                logger.info("[COPILOT-AGENT] Process group %s already terminated", pid)
            except PermissionError:
                logger.warning(
                    "[COPILOT-AGENT] Permission denied killing process group %s, "
                    "falling back to single process kill",
                    pid,
                )
                try:
                    self._current_process.kill()
                except Exception:
                    pass
            except Exception as exc:
                logger.warning("[COPILOT-AGENT] Error killing process group: %s", exc)
                try:
                    self._current_process.kill()
                except Exception:
                    pass

            try:
                await asyncio.wait_for(self._current_process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("[COPILOT-AGENT] Process %s did not exit after 5s", pid)
            except Exception:
                pass

            self._current_process = None
            return True

        logger.info("[COPILOT-AGENT] Cancel called but no running process found")
        return False

    async def query(self, prompt: str, timeout: float = 900.0) -> Optional[str]:
        """
        Send a query to Copilot CLI and return the final answer.

        Args:
            prompt: The text prompt to send
            timeout: Maximum time to wait for response in seconds
        """
        if not self._running:
            logger.error("Query called but agent not running")
            raise RuntimeError(
                "CopilotCodeAgent is not running. Call await start() or use as an async context manager."
            )

        logger.info(
            "Starting query: prompt='%s', timeout=%ss",
            f"{prompt[:100]}{'...' if len(prompt) > 100 else ''}",
            timeout,
        )
        start_time = datetime.now()

        try:
            result = await asyncio.wait_for(self._execute_query(prompt), timeout=timeout)
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(
                "Query completed in %.2fs: response='%s%s'",
                elapsed,
                result[:100] if result else None,
                "..." if result and len(result) > 100 else "",
            )
            return result
        except asyncio.TimeoutError:
            elapsed = (datetime.now() - start_time).total_seconds()
            logger.error("Query timed out after %.2fs (limit: %ss)", elapsed, timeout)
            raise

    async def _execute_query(self, prompt: str) -> Optional[str]:
        """
        Execute query by calling Copilot CLI directly.
        """
        command = self._build_query_command(prompt)

        env = os.environ.copy()
        if "PATH" in env:
            paths_to_add = ["/usr/local/bin", "/usr/bin", str(Path.home() / ".npm-global" / "bin")]
            for path in paths_to_add:
                if path not in env["PATH"]:
                    env["PATH"] = f"{path}:{env['PATH']}"

        if "env" in self._settings and isinstance(self._settings["env"], dict):
            env.update({str(k): str(v) for k, v in self._settings["env"].items()})
            logger.debug("Applied custom env vars: %s", self._settings["env"])

        cmd_display = " ".join(command)
        if len(cmd_display) > 240:
            cmd_display = cmd_display[:240] + "...(truncated)"
        logger.info("[COPILOT-AGENT] Executing: %s", cmd_display)
        logger.info("[COPILOT-AGENT] Working directory: %s", self.repo_path)

        process: Optional[asyncio.subprocess.Process] = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
                start_new_session=True,
            )
            self._current_process = process
            logger.debug("Subprocess started with PID: %s", process.pid)

            all_chunks: list[str] = []
            stderr_lines: list[str] = []
            query_start_time = datetime.now()

            while True:
                try:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=self.progress_interval,
                    )
                    if not line:
                        break

                    line_text = line.decode("utf-8", errors="replace").rstrip("\n\r")
                    if not line_text.strip():
                        continue

                    extracted_text = None
                    try:
                        # Some CLIs can emit JSON lines in non-default modes.
                        data = json.loads(line_text)
                        if isinstance(data, dict):
                            for key in ("result", "text", "message"):
                                value = data.get(key)
                                if isinstance(value, str) and value.strip():
                                    extracted_text = value.strip()
                                    break
                    except (json.JSONDecodeError, TypeError):
                        extracted_text = line_text

                    if extracted_text:
                        all_chunks.append(extracted_text)
                        if self.on_text:
                            if asyncio.iscoroutinefunction(self.on_text):
                                await self.on_text(extracted_text)
                            else:
                                self.on_text(extracted_text)

                except asyncio.TimeoutError:
                    elapsed = (datetime.now() - query_start_time).total_seconds()
                    progress_msg = self._get_progress_message(elapsed)
                    logger.info("[COPILOT-AGENT] Progress: %s", progress_msg)
                    if self.on_progress:
                        if asyncio.iscoroutinefunction(self.on_progress):
                            await self.on_progress(progress_msg)
                        else:
                            self.on_progress(progress_msg)
                    continue

            stderr_data = await process.stderr.read()
            if stderr_data:
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                for line in stderr_text.splitlines():
                    line = line.strip()
                    if line:
                        stderr_lines.append(line)
                if stderr_lines:
                    logger.info(
                        "[COPILOT-AGENT] Received stderr (%s lines): %s",
                        len(stderr_lines),
                        " ".join(stderr_lines[:5]),
                    )

            returncode = await process.wait()
            logger.info("[COPILOT-AGENT] Subprocess exited with code: %s", returncode)
            logger.info("[COPILOT-AGENT] Total chunks received: %s", len(all_chunks))

            if returncode != 0:
                error_msg = f"Copilot CLI exited with code {returncode}"
                if stderr_lines:
                    error_msg += f": {' '.join(stderr_lines[-3:])}"
                elif all_chunks:
                    error_msg += f": {' '.join(all_chunks[-3:])}"
                raise RuntimeError(error_msg)

            if not all_chunks:
                logger.error(
                    "[COPILOT-AGENT] Query returned no output! returncode=%s, stderr=%s",
                    returncode,
                    stderr_lines,
                )
                return None

            answer = self._extract_final_answer(all_chunks)
            logger.info(
                "Extracted answer: %s%s",
                answer[:200] if answer else None,
                "..." if answer and len(answer) > 200 else "",
            )
            return answer

        except asyncio.TimeoutError:
            logger.error("Query timeout - killing subprocess")
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            raise
        finally:
            self._current_process = None
            if process and process.returncode is None:
                process.kill()
                await process.wait()

    @property
    def is_running(self) -> bool:
        """Check if the agent is currently running."""
        return self._running


@asynccontextmanager
async def copilot_code_agent(
    repo_path: str,
    settings_path: Optional[str] = None,
    on_text: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    copilot_path: Optional[str] = None,
) -> AsyncIterator[CopilotCodeAgent]:
    """
    Convenience function for creating a Copilot Code Agent context manager.
    """
    agent = CopilotCodeAgent(repo_path, settings_path, on_text, on_progress, copilot_path)
    await agent.start()
    try:
        yield agent
    finally:
        await agent.stop()


async def main() -> None:
    """Example usage of CopilotCodeAgent."""
    async with CopilotCodeAgent(".") as agent:
        response = await agent.query("List files in the current directory")
        if response:
            print(response)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)
