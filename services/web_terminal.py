#!/usr/bin/env python3
"""
Web Terminal command execution engine.

Executes shell commands locally (main VPS) or remotely (worker VPS via SSH).
Streams stdout/stderr in real-time for WebSocket consumption.

Security:
  - Admin-only (caller must verify before calling)
  - 30s default timeout (configurable)
  - Output capped at 1MB per command
  - No command filtering — admin is trusted
"""

import os
import sys
import time
import signal
import logging
import subprocess
import threading
from typing import Optional, Tuple

logger = logging.getLogger("services.web_terminal")

COMMAND_TIMEOUT = int(os.getenv("TERMINAL_COMMAND_TIMEOUT", "30"))
MAX_OUTPUT_BYTES = 1024 * 1024  # 1MB cap per command


def execute_local(command: str, timeout: int = COMMAND_TIMEOUT) -> dict:
    """Execute a command locally and return output + exit code.

    Blocking — use from a thread or async wrapper.
    Returns: {"stdout": str, "stderr": str, "exit_code": int, "duration_ms": int}
    """
    start = time.time()
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable="/bin/bash",
        )
        duration_ms = int((time.time() - start) * 1000)

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Cap output
        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... [output truncated at 1MB]"
        if len(stderr) > MAX_OUTPUT_BYTES:
            stderr = stderr[:MAX_OUTPUT_BYTES] + "\n... [output truncated at 1MB]"

        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": 124,
            "duration_ms": duration_ms,
        }
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "duration_ms": duration_ms,
        }


class StreamingCommand:
    """Execute a command with real-time stdout/stderr streaming.

    Usage:
        cmd = StreamingCommand("docker ps")
        cmd.start()
        for chunk in cmd.read_stream():
            yield chunk  # {"type": "stdout"|"stderr", "data": str}
        result = cmd.wait()  # {"exit_code": int, "duration_ms": int}
    """

    def __init__(self, command: str, host: str = "main", timeout: int = COMMAND_TIMEOUT):
        self.command = command
        self.host = host
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self._start_time: float = 0
        self._output_buffer = []
        self._total_bytes = 0
        self._killed = False

    def start(self):
        """Start the command."""
        self._start_time = time.time()

        if self.host == "worker":
            # SSH to worker VPS
            ssh_host = os.getenv("WORKER_VPS_SSH_HOST", "")
            ssh_user = os.getenv("WORKER_VPS_SSH_USER", "root")
            ssh_key = os.getenv("WORKER_VPS_SSH_KEY", os.path.expanduser("~/.ssh/id_rsa"))

            if not ssh_host:
                raise RuntimeError("Worker SSH not configured (set WORKER_VPS_SSH_HOST)")

            full_cmd = [
                "ssh", "-i", ssh_key,
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                f"{ssh_user}@{ssh_host}",
                self.command,
            ]
        else:
            full_cmd = ["/bin/bash", "-c", self.command]

        self.process = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env={**os.environ, "TERM": "xterm-256color", "FORCE_COLOR": "1"},
        )

    def read_stream(self):
        """Generator yielding output chunks as they arrive.

        Yields: {"type": "stdout", "data": str}
        """
        if not self.process:
            return

        try:
            for line in self.process.stdout:
                if self._killed:
                    break
                if self._total_bytes + len(line) > MAX_OUTPUT_BYTES:
                    yield {"type": "stdout", "data": "\n... [output truncated at 1MB]\n"}
                    break

                self._output_buffer.append(line)
                self._total_bytes += len(line)
                yield {"type": "stdout", "data": line}
        except Exception as e:
            yield {"type": "stderr", "data": f"Read error: {e}\n"}

    def wait(self) -> dict:
        """Wait for the process to complete. Returns exit info."""
        if not self.process:
            return {"exit_code": 1, "duration_ms": 0}

        try:
            self.process.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            return {"exit_code": 124, "duration_ms": int((time.time() - self._start_time) * 1000)}

        duration_ms = int((time.time() - self._start_time) * 1000)
        return {
            "exit_code": self.process.returncode if not self._killed else 130,
            "duration_ms": duration_ms,
        }

    def kill(self):
        """Send SIGINT (Ctrl+C) to the process."""
        self._killed = True
        if self.process and self.process.poll() is None:
            try:
                self.process.send_signal(signal.SIGINT)
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
            except Exception:
                pass

    @property
    def full_output(self) -> str:
        """Get the complete output as a single string."""
        return "".join(self._output_buffer)

    @property
    def is_running(self) -> bool:
        if not self.process:
            return False
        return self.process.poll() is None


# ─────────────────────────────────────────────────────────────────────
# Session tracking (max 3 concurrent per user)
# ─────────────────────────────────────────────────────────────────────

_active_sessions: dict = {}  # user_id → list of StreamingCommand
_session_lock = threading.Lock()


def start_session(user_id: int, command: str, host: str = "main") -> Optional[StreamingCommand]:
    """Start a new command session for a user. Returns None if max sessions reached."""
    with _session_lock:
        # Clean up finished sessions
        if user_id in _active_sessions:
            _active_sessions[user_id] = [
                s for s in _active_sessions[user_id] if s.is_running
            ]
            if len(_active_sessions[user_id]) >= 3:
                return None
        else:
            _active_sessions[user_id] = []

        cmd = StreamingCommand(command, host=host)
        cmd.start()
        _active_sessions[user_id].append(cmd)
        return cmd


def kill_user_session(user_id: int) -> bool:
    """Kill all running commands for a user (Ctrl+C)."""
    with _session_lock:
        killed = False
        if user_id in _active_sessions:
            for cmd in _active_sessions[user_id]:
                if cmd.is_running:
                    cmd.kill()
                    killed = True
        return killed
