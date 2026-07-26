#!/usr/bin/env python3
"""
Web Terminal API Router — WebSocket for interactive shell + REST for quick commands.

Same pattern as /admin/system-metrics — admin-only, stateless, no DB.

WebSocket: WS /ws/terminal/{host}?token=<admin_jwt>
  - Real-time command execution with streaming output
  - Supports Ctrl+C

REST:
  POST /admin/terminal/exec — execute a single command, return output
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from database_postgres import get_db
from utils.auth_helpers import get_user_id_from_token

logger = logging.getLogger("api.terminal")
router = APIRouter()


def _require_admin(authorization: Optional[str]) -> int:
    """Verify admin access from Authorization header."""
    from app import require_admin
    user_id = get_user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_admin(user_id)
    return user_id


def _require_admin_from_token(token: str) -> int:
    """Verify admin access from a token string (for WebSocket)."""
    from app import require_admin
    user_id = get_user_id_from_token(f"Bearer {token}")
    if not user_id:
        raise ValueError("Invalid token")
    require_admin(user_id)
    return user_id


# ─────────────────────────────────────────────────────────────────────
# REST: Quick execute (synchronous)
# ─────────────────────────────────────────────────────────────────────

class ExecRequest(BaseModel):
    command: str
    host: str = "main"  # "main" or "worker"


class ExecResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int


@router.post("/admin/terminal/exec", response_model=ExecResponse)
async def terminal_exec(
    request: ExecRequest,
    authorization: Optional[str] = Header(None),
):
    """Execute a single command and return output (non-streaming)."""
    user_id = _require_admin(authorization)

    from services.web_terminal import execute_local

    if request.host == "worker":
        # SSH to worker — use execute_local with SSH wrapper
        import os
        ssh_host = os.getenv("WORKER_VPS_SSH_HOST", "")
        if not ssh_host:
            raise HTTPException(status_code=400, detail="Worker SSH not configured (set WORKER_VPS_SSH_HOST)")

        ssh_user = os.getenv("WORKER_VPS_SSH_USER", "root")
        ssh_key = os.getenv("WORKER_VPS_SSH_KEY", os.path.expanduser("~/.ssh/id_rsa"))
        wrapped_cmd = f'ssh -i {ssh_key} -o StrictHostKeyChecking=no -o ConnectTimeout=5 {ssh_user}@{ssh_host} "{request.command}"'
        result = execute_local(wrapped_cmd)
    else:
        result = execute_local(request.command)

    return result


# ─────────────────────────────────────────────────────────────────────
# WebSocket: Interactive terminal
# ─────────────────────────────────────────────────────────────────────

@router.websocket("/ws/terminal/{host}")
async def terminal_websocket(websocket: WebSocket, host: str, token: str = Query(...)):
    """WebSocket terminal — real-time command execution with streaming.

    Auth via query param ?token=<admin_jwt>

    Protocol:
      Client → Server: {"command": "docker ps"}
      Server → Client: {"type": "stdout", "data": "..."}
      Server → Client: {"type": "exit", "code": 0, "duration_ms": 500}
      Client → Server: {"action": "ctrl_c"}
      Server → Client: {"type": "killed"}
    """
    try:
        user_id = _require_admin_from_token(token)
    except (ValueError, Exception):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if host not in ("main", "worker"):
        await websocket.close(code=4002, reason="Invalid host. Use 'main' or 'worker'.")
        return

    await websocket.accept()
    logger.info(f"[TERMINAL-WS] Connected: user={user_id} host={host}")

    import asyncio
    from services.web_terminal import StreamingCommand

    current_cmd: Optional[StreamingCommand] = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            # Handle Ctrl+C
            if msg.get("action") == "ctrl_c":
                if current_cmd and current_cmd.is_running:
                    current_cmd.kill()
                    await websocket.send_json({"type": "killed"})
                else:
                    await websocket.send_json({"type": "no_process"})
                continue

            command = msg.get("command", "").strip()
            if not command:
                continue

            # Block dangerous commands
            dangerous = ["rm -rf /", "mkfs", "dd if=", ":(){ :|:& };:"]
            if any(d in command for d in dangerous):
                await websocket.send_json({"type": "error", "message": "Command blocked"})
                continue

            logger.info(f"[TERMINAL-WS] Exec: user={user_id} host={host} cmd={command[:80]}")

            # Create and start command
            current_cmd = StreamingCommand(command, host=host)
            try:
                current_cmd.start()
            except RuntimeError as e:
                await websocket.send_json({"type": "error", "message": str(e)})
                continue

            # Stream output lines
            try:
                loop = asyncio.get_event_loop()
                for chunk in current_cmd.read_stream():
                    await websocket.send_json(chunk)

                # Wait for completion
                result = await loop.run_in_executor(None, current_cmd.wait)
                await websocket.send_json({
                    "type": "exit",
                    "code": result["exit_code"],
                    "duration_ms": result["duration_ms"],
                })
            except WebSocketDisconnect:
                if current_cmd:
                    current_cmd.kill()
                break
            except Exception as e:
                logger.error(f"[TERMINAL-WS] Exec error: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})
                if current_cmd:
                    current_cmd.kill()

    except WebSocketDisconnect:
        logger.info(f"[TERMINAL-WS] Disconnected: user={user_id}")
        if current_cmd:
            current_cmd.kill()
