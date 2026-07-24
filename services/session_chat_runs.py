"""
Durable session chat run storage and execution helpers.

Session chat used to keep the running Claude handler and streamed chunks only
inside the FastAPI process. This module persists run state and chunks so the API
can restart while a separate worker continues the Claude edit.
"""

import asyncio
import json
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from database_postgres import get_db, get_connection_pool
from services.session_lock_service import SessionLockService
from services.sentry_config import capture_exception

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
ACTIVE_STATUSES = {"queued", "running", "cancel_requested"}


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def create_run(
    *,
    session_id: int,
    session_key: str,
    project_id: int,
    user_id: Optional[int],
    channel: str,
    mode: str,
    user_message: str,
    session_context: str,
    billing_user_id: Optional[int],
    reserved_charges: Optional[List[Dict[str, Any]]] = None,
    image_attachment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    run_uuid = str(uuid.uuid4())
    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO session_chat_runs (
                run_uuid, session_id, session_key, project_id, user_id, channel,
                mode, user_message, session_context, billing_user_id,
                reserved_charges, image_attachment, status, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, 'queued', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id, run_uuid, status
            """,
            (
                run_uuid,
                session_id,
                session_key,
                project_id,
                user_id,
                (channel or "webchat")[:50],
                mode or "dream",
                user_message,
                session_context or "",
                billing_user_id,
                json.dumps(reserved_charges or []),
                json.dumps(image_attachment) if image_attachment else None,
            ),
        ).fetchone()
        conn.commit()
    logger.info("[SESSION-RUN] queued run id=%s session=%s channel=%s", _row_value(row, "id"), session_id, channel)
    return {"id": _row_value(row, "id"), "run_uuid": _row_value(row, "run_uuid", 1), "status": _row_value(row, "status", 2)}


def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT r.*, s.label AS session_label, p.name AS project_name, p.project_path
            FROM session_chat_runs r
            JOIN sessions s ON s.id = r.session_id
            JOIN projects p ON p.id = r.project_id
            WHERE r.id = %s
            """,
            (run_id,),
        ).fetchone()
    return dict(row) if row else None


def get_latest_run_for_session(session_key: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_chat_runs
            WHERE session_key = %s
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (session_key,),
        ).fetchone()
    return dict(row) if row else None


def get_active_run_for_session(session_key: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_chat_runs
            WHERE session_key = %s AND status IN ('queued', 'running', 'cancel_requested')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (session_key,),
        ).fetchone()
    return dict(row) if row else None


def append_chunk(run_id: int, chunk_type: str, content: str) -> int:
    content = content or ""
    if not content:
        return -1
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM session_chat_chunks WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        seq = int(_row_value(row, "next_seq") or 0)
        conn.execute(
            """
            INSERT INTO session_chat_chunks (run_id, seq, chunk_type, content, created_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (run_id, seq, chunk_type or "text", content),
        )
        conn.execute(
            "UPDATE session_chat_runs SET updated_at = CURRENT_TIMESTAMP, heartbeat_at = CURRENT_TIMESTAMP WHERE id = %s",
            (run_id,),
        )
        conn.commit()
    return seq


def get_chunks(run_id: int, after: int = 0) -> Dict[str, Any]:
    with get_db() as conn:
        run = conn.execute("SELECT status FROM session_chat_runs WHERE id = %s", (run_id,)).fetchone()
        rows = conn.execute(
            """
            SELECT seq, chunk_type, content FROM session_chat_chunks
            WHERE run_id = %s AND seq >= %s
            ORDER BY seq ASC
            """,
            (run_id, after),
        ).fetchall()
        total_row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS total FROM session_chat_chunks WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    status = _row_value(run, "status") if run else None
    return {
        "chunks": [dict(row) for row in rows],
        "total": int(_row_value(total_row, "total") or 0),
        "status": status,
        "active": status in ACTIVE_STATUSES,
    }


def mark_cancel_requested(session_key: str) -> Optional[Dict[str, Any]]:
    run = get_active_run_for_session(session_key)
    if not run:
        return None
    if run.get("status") == "queued":
        with get_db() as conn:
            conn.execute(
                """
                UPDATE session_chat_runs
                SET status = 'cancelled',
                    cancel_requested_at = CURRENT_TIMESTAMP,
                    completed_at = CURRENT_TIMESTAMP,
                    error = 'Session chat was cancelled before it started.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'queued'
                """,
                (run["id"],),
            )
            conn.commit()
        try:
            SessionLockService.release_processing(int(run["session_id"]))
        except Exception as e:
            logger.warning("[SESSION-RUN] failed to release processing after queued cancel: %s", e)
        return run
    with get_db() as conn:
        conn.execute(
            """
            UPDATE session_chat_runs
            SET status = 'cancel_requested', cancel_requested_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status IN ('queued', 'running')
            """,
            (run["id"],),
        )
        conn.commit()
    return run


def is_cancel_requested(run_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT status FROM session_chat_runs WHERE id = %s", (run_id,)).fetchone()
    return _row_value(row, "status") == "cancel_requested"


def claim_next_run(worker_id: str) -> Optional[Dict[str, Any]]:
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM session_chat_runs
                WHERE status = 'queued'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            run_id = row["id"] if isinstance(row, dict) else row[0]
            cur.execute(
                """
                UPDATE session_chat_runs
                SET status = 'running',
                    worker_id = %s,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    heartbeat_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, run_id),
            )
            run = cur.fetchone()
            conn.commit()
            return dict(run) if run else None
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def update_heartbeat(run_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE session_chat_runs SET heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (run_id,),
        )
        conn.commit()


def mark_completed(run_id: int, assistant_message_id: Optional[int], token_usage: Optional[dict], has_writes: bool) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE session_chat_runs
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                assistant_message_id = %s,
                token_usage = %s::jsonb,
                has_writes = %s
            WHERE id = %s
            """,
            (assistant_message_id, json.dumps(token_usage) if token_usage else None, bool(has_writes), run_id),
        )
        conn.commit()


def mark_failed(run_id: int, status: str, error: str) -> None:
    final_status = status if status in {"failed", "cancelled", "interrupted"} else "failed"
    with get_db() as conn:
        conn.execute(
            """
            UPDATE session_chat_runs
            SET status = %s, error = %s, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (final_status, error[:2000], run_id),
        )
        conn.commit()


def recover_stale_runs(stale_after_minutes: int = 20) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=stale_after_minutes)
    recovered = 0
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, billing_user_id, reserved_charges, token_usage
            FROM session_chat_runs
            WHERE status IN ('running', 'cancel_requested')
              AND (heartbeat_at IS NULL OR heartbeat_at < %s)
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            run_id = _row_value(row, "id")
            session_id = _row_value(row, "session_id", 1)
            billing_user_id = _row_value(row, "billing_user_id", 2)
            reserved_charges = _json_loads(_row_value(row, "reserved_charges", 3), [])
            token_usage = _json_loads(_row_value(row, "token_usage", 4), None)
            message = "Session chat was interrupted because the worker stopped before this run finished."
            conn.execute(
                """
                UPDATE session_chat_runs
                SET status = 'interrupted',
                    error = %s,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (message, run_id),
            )
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                (session_id, "assistant", message),
            )
            recovered += 1
            if billing_user_id and reserved_charges and not token_usage:
                try:
                    from services.external_session_chat import refund_session_chat_credits

                    refund_session_chat_credits(billing_user_id, reserved_charges, "Worker")
                except Exception as e:
                    logger.warning("[SESSION-RUN] failed to refund stale run %s: %s", run_id, e)
            try:
                SessionLockService.release_processing(int(session_id))
            except Exception as e:
                logger.warning("[SESSION-RUN] failed to release stale processing for session %s: %s", session_id, e)
        conn.commit()
    if recovered:
        logger.warning("[SESSION-RUN] recovered %s stale running session chat runs", recovered)
    return recovered


async def execute_run(run_id: int) -> Dict[str, Any]:
    run = get_run(run_id)
    if not run:
        return {"status": "error", "message": "Run not found"}

    session_id = int(run["session_id"])
    project_id = int(run["project_id"])
    session_key = run["session_key"]
    channel_label = str(run.get("channel") or "worker").title()
    handler = None
    assistant_saved = False
    assistant_message_id = None
    image_attachment = _json_loads(run.get("image_attachment"), None)
    reserved_charges = _json_loads(run.get("reserved_charges"), [])
    billing_user_id = run.get("billing_user_id")

    try:
        if is_cancel_requested(run_id):
            raise asyncio.CancelledError()

        from acp_chat_handler import get_acp_chat_handler
        from services.external_session_chat import (
            finalize_session_token_usage,
            refund_session_chat_credits,
            auto_commit_selected_session_change,
        )

        handler = get_acp_chat_handler(session_key)
        if not handler:
            raise RuntimeError("Could not initialize the project session chat handler.")

        handler.set_session_id(session_id)
        if (run.get("mode") or "dream") == "plan":
            handler._plan_mode = True
            try:
                from plan_manager import PlanManager

                existing_plan = PlanManager.find_active_plan(session_id, project_id)
                if existing_plan:
                    handler.set_existing_plan(existing_plan)
            except Exception as e:
                logger.warning("[SESSION-RUN] plan context lookup failed: %s", e)

        chunks_for_response: List[str] = []

        # Heartbeat the run periodically so recover_stale_runs (20-min default)
        # doesn't mark it 'interrupted' while Claude is still working. Long
        # tool-use phases (file edits, build runs, MCP calls) can go many
        # minutes without emitting a chunk, which would otherwise let the
        # heartbeat age out and trigger a false recovery on the next worker
        # startup. We bump on every chunk AND on a time-based floor.
        import time as _time
        _last_heartbeat = 0.0
        _HEARTBEAT_INTERVAL = 15.0  # seconds

        async for chunk in handler.run_chat_streaming_unified(run.get("user_message") or "", run.get("session_context") or ""):
            if is_cancel_requested(run_id):
                raise asyncio.CancelledError()
            text = str(chunk or "")
            if not text:
                continue
            chunk_type = "progress" if text.startswith("PROGRESS:") else "text"
            append_chunk(run_id, chunk_type, text)
            chunks_for_response.append(text)

            # Bump heartbeat on chunk + on time floor (covers long no-chunk gaps).
            now = _time.monotonic()
            if now - _last_heartbeat >= _HEARTBEAT_INTERVAL:
                try:
                    update_heartbeat(run_id)
                    _last_heartbeat = now
                except Exception as hb_err:
                    logger.warning("[SESSION-RUN] heartbeat update failed (non-fatal): %s", hb_err)

        final_response = getattr(handler, "_last_query_response", None)
        if final_response:
            assistant_content = str(final_response).strip()
        else:
            # Use the shared chunk filter from app.py so TOOL: / PROGRESS: /
            # JSON noise doesn't leak into the saved assistant message.
            # Local import to avoid a circular import at module load time.
            from app import _clean_chat_chunks
            real_chunks = _clean_chat_chunks(chunks_for_response)
            assistant_content = "\n".join(real_chunks).strip()

        if not assistant_content:
            assistant_content = "Session chat completed, but no response text was returned."

        token_usage_json = finalize_session_token_usage(
            handler=handler,
            project_id=project_id,
            session_id=session_id,
            billing_user_id=billing_user_id,
            precharged_amount=sum(abs(c.get("amount", 0)) for c in reserved_charges),
            channel_label=channel_label,
        )
        token_usage = _json_loads(token_usage_json, None)
        has_writes = bool((token_usage or {}).get("has_writes"))

        with get_db() as conn:
            if token_usage_json:
                row = conn.execute(
                    "INSERT INTO messages (session_id, role, content, token_usage) VALUES (%s, %s, %s, %s) RETURNING id",
                    (session_id, "assistant", assistant_content, token_usage_json),
                ).fetchone()
            else:
                row = conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s) RETURNING id",
                    (session_id, "assistant", assistant_content),
                ).fetchone()
            assistant_message_id = _row_value(row, "id")
            conn.execute("UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s", (session_id,))
            conn.commit()
        assistant_saved = True

        await auto_commit_selected_session_change(project_id, session_id, handler, channel_label)
        mark_completed(run_id, assistant_message_id, token_usage, has_writes)
        return {"status": "success", "message": assistant_content}

    except asyncio.CancelledError:
        if not assistant_saved and billing_user_id and reserved_charges:
            try:
                from services.external_session_chat import refund_session_chat_credits

                refund_session_chat_credits(billing_user_id, reserved_charges, channel_label)
            except Exception as e:
                logger.warning("[SESSION-RUN] failed to refund cancelled run %s: %s", run_id, e)
        mark_failed(run_id, "cancelled", "Session chat was cancelled.")
        append_chunk(run_id, "text", "Session chat was cancelled.")
        return {"status": "cancelled", "message": "Session chat was cancelled."}
    except Exception as e:
        logger.error("[SESSION-RUN] run %s failed: %s", run_id, e, exc_info=True)
        capture_exception(
            e,
            tags={
                "service": "session-chat-worker",
                "run_id": run_id,
                "session_id": session_id,
                "project_id": project_id,
                "channel": run.get("channel"),
            },
            context={
                "mode": run.get("mode"),
                "has_image": bool(image_attachment),
            },
        )
        if not assistant_saved:
            try:
                from services.external_session_chat import refund_session_chat_credits

                refund_session_chat_credits(billing_user_id, reserved_charges, channel_label)
            except Exception:
                pass
        error_message = f"Session chat failed: {str(e)}"
        mark_failed(run_id, "failed", error_message)
        append_chunk(run_id, "text", error_message)
        try:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                    (session_id, "assistant", error_message),
                )
                conn.commit()
        except Exception:
            pass
        return {"status": "error", "message": error_message}
    finally:
        if image_attachment:
            try:
                from app import cleanup_chat_image_attachment

                cleanup_chat_image_attachment(image_attachment, "[SESSION-RUN]")
            except Exception as cleanup_error:
                logger.warning("[SESSION-RUN] image cleanup failed: %s", cleanup_error)
        if handler:
            try:
                handler.kill_orphan_processes()
            except Exception as cleanup_error:
                logger.warning("[SESSION-RUN] handler cleanup failed: %s", cleanup_error)
        SessionLockService.release_processing(session_id)


async def wait_for_run(run_id: int, poll_seconds: float = 2.0, timeout_seconds: float = 1800.0) -> Dict[str, Any]:
    """Wait for a run to complete. If no separate worker claims it within
    a few seconds, execute it inline (self-healing fallback).

    This allows the worker-api process to handle Telegram/Discord session
    chat WITHOUT requiring a separate session_chat_worker PM2 process.
    """
    start = datetime.utcnow()
    _inline_executed = False

    while (datetime.utcnow() - start).total_seconds() < timeout_seconds:
        run = get_run(run_id)
        if not run:
            return {"status": "error", "message": "Session run disappeared."}
        status = run.get("status")
        if status in TERMINAL_STATUSES:
            if status == "completed":
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT content FROM messages WHERE id = %s",
                        (run.get("assistant_message_id"),),
                    ).fetchone()
                return {"status": "success", "message": _row_value(row, "content") or "Session chat completed."}
            return {"status": status, "message": run.get("error") or f"Session chat {status}."}

        # Self-healing: if the run is still queued after 3 seconds, no
        # separate worker is running. Proxy it to the worker-api (which
        # has Docker + project files) for execution.
        if status == "queued" and not _inline_executed:
            elapsed = (datetime.utcnow() - start).total_seconds()
            if elapsed > 3:
                logger.info("[SESSION-RUN] No worker claimed run %s after %.1fs — proxying to worker-api", run_id, elapsed)
                _inline_executed = True
                try:
                    # Try proxying to worker-api first (it has Docker + files)
                    worker_url = os.getenv("WORKER_VPS_URL", "")
                    if worker_url:
                        import httpx
                        logger.info("[SESSION-RUN] Proxying run %s to %s/internal/chat-execute", run_id, worker_url)
                        async with httpx.AsyncClient(timeout=1800) as client:
                            resp = await client.post(
                                f"{worker_url}/internal/chat-execute",
                                json={"run_id": run_id},
                                timeout=1800,
                            )
                            if resp.status_code == 200:
                                logger.info("[SESSION-RUN] Worker-api executed run %s", run_id)
                            else:
                                logger.error("[SESSION-RUN] Worker-api returned %s: %s", resp.status_code, resp.text[:200])
                    else:
                        # No worker-api URL — execute inline (local dev)
                        logger.info("[SESSION-RUN] No worker-api URL — executing inline")
                        wid = f"{socket.gethostname()}:{os.getpid()}-inline"
                        with get_db() as conn:
                            conn.execute(
                                "UPDATE session_chat_runs SET status = 'running', worker_id = %s, started_at = NOW() WHERE id = %s AND status = 'queued'",
                                (wid, run_id),
                            )
                            conn.commit()
                        await execute_run(run_id)
                except Exception as e:
                    logger.error("[SESSION-RUN] Inline execution failed for run %s: %s", run_id, e, exc_info=True)
                    # Mark as failed so wait loop doesn't spin forever
                    try:
                        with get_db() as conn:
                            conn.execute(
                                "UPDATE session_chat_runs SET status = 'failed', error = %s, completed_at = NOW() WHERE id = %s",
                                (str(e)[:500], run_id),
                            )
                            conn.commit()
                    except Exception:
                        pass
                    return {"status": "error", "message": f"Session chat failed: {e}"}

        await asyncio.sleep(poll_seconds)

    return {"status": "timeout", "message": "Session chat is still running. Check the session again shortly."}


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"
