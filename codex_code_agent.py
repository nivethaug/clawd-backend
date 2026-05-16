#!/usr/bin/env python3
"""
Codex Code Agent - A Python wrapper for the Codex CLI.

This module mirrors ClaudeCodeAgent's async interface, but runs `codex exec`
as a subprocess. It does not use ACP. It supports streaming JSONL output for
callbacks and reads Codex's `--output-last-message` file for the final answer.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional


logger = logging.getLogger(__name__)


def configure_logging(
    level: int = logging.INFO,
    format_string: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    log_file: Optional[str] = None,
) -> None:
    """Configure logging for CodexCodeAgent."""
    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler()

    handler.setFormatter(logging.Formatter(format_string))
    logger.addHandler(handler)
    logger.setLevel(level)


class CodexCodeAgent:
    """
    Async context manager that runs Codex queries through the Codex CLI.

    Example:
        async with CodexCodeAgent("/path/to/repo") as agent:
            response = await agent.query("Write a hello.py")
            print(response)
    """

    def __init__(
        self,
        repo_path: str,
        settings_path: Optional[str] = None,
        on_text: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        codex_path: Optional[str] = None,
        progress_interval: float = 30.0,
        resume_session_id: Optional[str] = None,
    ):
        """
        Initialize Codex Code Agent.

        Args:
            repo_path: Path to repository/workspace to work in.
            settings_path: Optional settings JSON path, default ~/.codex/settings.json.
            on_text: Optional callback for streamed text/tool markers.
            on_progress: Optional callback for UI-only progress messages.
            codex_path: Optional explicit path to codex CLI.
            progress_interval: Seconds between progress updates while waiting.
            resume_session_id: Reserved for interface parity; Codex exec is one-shot.
        """
        self.repo_path = Path(repo_path).resolve()
        self.settings_path = Path(settings_path or Path.home() / ".codex" / "settings.json")
        self.on_text = on_text
        self.on_progress = on_progress
        self.codex_path = codex_path
        self.progress_interval = float(
            os.environ.get("CODEX_PROGRESS_INTERVAL_SECONDS", progress_interval)
        )

        self._running = False
        self._current_process: Optional[asyncio.subprocess.Process] = None
        self._last_token_usage: Optional[dict] = None
        self._last_session_id: Optional[str] = resume_session_id
        self._settings = self._load_settings()

        logger.info(
            "[CODEX-AGENT] initialized: repo_path=%s, settings_path=%s, "
            "progress_interval=%ss, on_text=%s, on_progress=%s",
            self.repo_path,
            self.settings_path,
            self.progress_interval,
            "set" if on_text else "NOT SET",
            "set" if on_progress else "NOT SET",
        )

    def _load_settings(self) -> dict[str, Any]:
        """Load Codex agent settings from JSON when present."""
        if not self.settings_path.exists():
            logger.debug("Settings file not found: %s", self.settings_path)
            return {}

        try:
            with open(self.settings_path, "r", encoding="utf-8") as handle:
                settings = json.load(handle)
                logger.info("Loaded settings from %s: %s", self.settings_path, settings)
                return settings
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("Could not load settings from %s: %s", self.settings_path, exc)
            return {}

    def _find_codex_cli(self) -> str:
        """Find the codex CLI executable."""
        if self.codex_path:
            if Path(self.codex_path).exists():
                logger.debug("Using explicit codex_path: %s", self.codex_path)
                return self.codex_path
            raise RuntimeError(f"Codex CLI not found at specified path: {self.codex_path}")

        codex_path = shutil.which("codex")
        if codex_path:
            logger.debug("Found codex CLI via shutil.which: %s", codex_path)
            return codex_path

        common_paths = [
            "/usr/local/bin/codex",
            "/usr/bin/codex",
            str(Path.home() / ".local" / "bin" / "codex"),
            str(Path.home() / ".npm-global" / "bin" / "codex"),
        ]
        for path in common_paths:
            if Path(path).exists():
                logger.debug("Found codex CLI at fallback path: %s", path)
                return path

        raise RuntimeError(
            "Codex CLI not found. Install Codex CLI or provide codex_path."
        )

    def _get_progress_message(self, elapsed: float) -> str:
        """Generate phase-appropriate progress message."""
        if elapsed < 30:
            return "Analyzing your request..."
        if elapsed < 120:
            return "Working on your changes..."
        if elapsed < 300:
            return "Applying fixes and improvements..."
        if elapsed < 600:
            return "Processing complex task..."
        return "Almost there, finalizing..."

    def _extract_final_answer(self, all_chunks: list[str]) -> Optional[str]:
        """Fallback extraction when output-last-message is unavailable."""
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

        markdown_syntax = {"```", "``", "---", "***", "___", "##", "###", "####"}
        for line in reversed(lines):
            if line not in markdown_syntax and any(char.isalpha() for char in line):
                return line

        return lines[-1] if lines else None

    def _extract_token_usage(self, data: dict[str, Any]) -> Optional[dict]:
        """Extract token usage from a Codex JSON event when available."""
        usage = data.get("usage")
        if not isinstance(usage, dict):
            usage = data.get("token_usage")
        if not isinstance(usage, dict):
            return None

        input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "cost_usd": usage.get("cost_usd"),
        }

    def _build_query_command(self, prompt: str, output_file: str) -> list[str]:
        """Build a `codex exec` command for one-shot query execution."""
        codex_path = self._find_codex_cli()
        command = [codex_path, "exec"]

        profile = self._settings.get("profile") or os.environ.get("CODEX_PROFILE")
        if profile:
            command.extend(["--profile", str(profile)])

        model = self._settings.get("model") or os.environ.get("CODEX_MODEL")
        if model:
            command.extend(["--model", str(model)])

        sandbox = self._settings.get(
            "sandbox",
            os.environ.get("CODEX_SANDBOX", "danger-full-access"),
        )
        if sandbox:
            command.extend(["--sandbox", str(sandbox)])

        if self._settings.get("bypass_approvals_and_sandbox") or (
            os.environ.get("CODEX_BYPASS_APPROVALS_AND_SANDBOX", "").lower()
            in ("1", "true", "yes", "on")
        ):
            command.append("--dangerously-bypass-approvals-and-sandbox")

        if self._settings.get("search") or (
            os.environ.get("CODEX_SEARCH", "").lower() in ("1", "true", "yes", "on")
        ):
            command.append("--search")

        flags = self._settings.get("flags", [])
        if isinstance(flags, list):
            command.extend(str(flag) for flag in flags)

        config_overrides = self._settings.get("config", [])
        if isinstance(config_overrides, dict):
            for key, value in config_overrides.items():
                command.extend(["--config", f"{key}={json.dumps(value)}"])
        elif isinstance(config_overrides, list):
            for override in config_overrides:
                command.extend(["--config", str(override)])

        approval = self._settings.get(
            "approval_policy",
            self._settings.get(
                "ask_for_approval",
                os.environ.get("CODEX_APPROVAL_POLICY", "never"),
            ),
        )
        if approval:
            command.extend(["--config", f"approval_policy={json.dumps(str(approval))}"])

        command.extend([
            "--cd",
            str(self.repo_path),
            "--skip-git-repo-check",
            "--json",
            "--output-last-message",
            output_file,
            prompt,
        ])
        return command

    def _extract_text_from_event(self, data: dict[str, Any]) -> Optional[str]:
        """Extract useful assistant text from a Codex JSONL event."""
        for key in ("text", "delta", "message", "content", "result", "output", "last_message"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = self._extract_text_from_event(value)
                if nested:
                    return nested
            if isinstance(value, list):
                parts: list[str] = []
                for item in value:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        nested = self._extract_text_from_event(item)
                        if nested:
                            parts.append(nested)
                if parts:
                    return "\n".join(parts).strip()
        return None

    def _extract_tool_name_from_event(self, data: dict[str, Any]) -> Optional[str]:
        """Extract a tool/command marker from a Codex JSONL event."""
        event_type = str(data.get("type") or data.get("event") or "").lower()
        if not any(marker in event_type for marker in ("tool", "exec", "command", "patch")):
            return None

        for key in ("tool_name", "tool", "name", "command"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().split()[0]
        return event_type or None

    async def __aenter__(self) -> "CodexCodeAgent":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self) -> None:
        """Initialize Codex Code Agent."""
        if self._running:
            logger.debug("Agent already running, skipping start")
            return
        if not self.repo_path.exists():
            logger.error("Repository path does not exist: %s", self.repo_path)
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")

        self._find_codex_cli()
        self._running = True
        logger.info("Agent started: repo_path=%s", self.repo_path)

    async def stop(self) -> None:
        """Stop Codex Code Agent."""
        self._running = False
        logger.info("Agent stopped")

    async def cancel(self) -> bool:
        """Cancel the currently running query by killing the process group."""
        if self._current_process and self._current_process.returncode is None:
            pid = self._current_process.pid
            logger.info("[CODEX-AGENT] Cancelling query - killing process group (PID: %s)", pid)
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                logger.info("[CODEX-AGENT] Process group %s already terminated", pid)
            except Exception as exc:
                logger.warning("[CODEX-AGENT] Error killing process group: %s", exc)
                try:
                    self._current_process.kill()
                except Exception:
                    pass

            try:
                await asyncio.wait_for(self._current_process.wait(), timeout=5.0)
            except Exception:
                pass

            self._current_process = None
            return True

        logger.info("[CODEX-AGENT] Cancel called but no running process found")
        return False

    async def query(self, prompt: str, timeout: float = 900.0) -> Optional[str]:
        """Send a query to Codex and return the final answer."""
        if not self._running:
            logger.error("Query called but agent not running")
            raise RuntimeError(
                "CodexCodeAgent is not running. Call await start() or use as an async context manager."
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
        output_file_handle = tempfile.NamedTemporaryFile(
            prefix="codex-last-message-",
            suffix=".txt",
            delete=False,
        )
        output_file = output_file_handle.name
        output_file_handle.close()

        command = self._build_query_command(prompt, output_file)
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
        if len(cmd_display) > 260:
            cmd_display = cmd_display[:260] + "...(truncated)"
        logger.info("[CODEX-AGENT] Executing: %s", cmd_display)
        logger.info("[CODEX-AGENT] Working directory: %s", self.repo_path)

        process: Optional[asyncio.subprocess.Process] = None
        all_chunks: list[str] = []
        stderr_lines: list[str] = []
        self._last_token_usage = None

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.repo_path),
                env=env,
                start_new_session=True,
                limit=10 * 1024 * 1024,
            )
            self._current_process = process
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
                        data = json.loads(line_text)
                        if isinstance(data, dict):
                            token_usage = self._extract_token_usage(data)
                            if token_usage:
                                self._last_token_usage = token_usage

                            session_id = data.get("session_id") or data.get("conversation_id")
                            if isinstance(session_id, str) and session_id:
                                self._last_session_id = session_id

                            tool_name = self._extract_tool_name_from_event(data)
                            if tool_name and self.on_text:
                                if asyncio.iscoroutinefunction(self.on_text):
                                    await self.on_text(f"TOOL:{tool_name}")
                                else:
                                    self.on_text(f"TOOL:{tool_name}")

                            extracted_text = self._extract_text_from_event(data)
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
                    logger.info("[CODEX-AGENT] Progress: %s", progress_msg)
                    if self.on_progress:
                        if asyncio.iscoroutinefunction(self.on_progress):
                            await self.on_progress(progress_msg)
                        else:
                            self.on_progress(progress_msg)
                    continue

            stderr_data = await process.stderr.read()
            if stderr_data:
                stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                stderr_lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]
                if stderr_lines:
                    logger.info(
                        "[CODEX-AGENT] Received stderr (%s lines): %s",
                        len(stderr_lines),
                        " ".join(stderr_lines[:5]),
                    )

            returncode = await process.wait()
            logger.info("[CODEX-AGENT] Subprocess exited with code: %s", returncode)

            if returncode != 0:
                error_msg = f"Codex CLI exited with code {returncode}"
                if stderr_lines:
                    error_msg += f": {' '.join(stderr_lines[-3:])}"
                elif all_chunks:
                    error_msg += f": {' '.join(all_chunks[-3:])}"
                raise RuntimeError(error_msg)

            final_answer = None
            output_path = Path(output_file)
            if output_path.exists():
                final_answer = output_path.read_text(encoding="utf-8", errors="replace").strip()

            if not final_answer:
                final_answer = self._extract_final_answer(all_chunks)

            if not final_answer:
                logger.error("[CODEX-AGENT] Query returned no final answer")
                return None

            logger.info(
                "Extracted answer: %s%s",
                final_answer[:200],
                "..." if len(final_answer) > 200 else "",
            )
            return final_answer

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
            try:
                Path(output_file).unlink(missing_ok=True)
            except Exception:
                pass

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_token_usage(self) -> Optional[dict]:
        return self._last_token_usage

    @property
    def last_session_id(self) -> Optional[str]:
        return self._last_session_id


@asynccontextmanager
async def codex_code_agent(
    repo_path: str,
    settings_path: Optional[str] = None,
    on_text: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    codex_path: Optional[str] = None,
) -> AsyncIterator[CodexCodeAgent]:
    """Convenience function for creating a Codex Code Agent context manager."""
    agent = CodexCodeAgent(repo_path, settings_path, on_text, on_progress, codex_path)
    await agent.start()
    try:
        yield agent
    finally:
        await agent.stop()


async def main() -> None:
    """Example usage of CodexCodeAgent."""
    async with CodexCodeAgent(".") as agent:
        response = await agent.query("Give a one-sentence summary of this repository.")
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
