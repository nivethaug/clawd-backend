"""
Support Conversation Service — persistence + state transitions for the
live support system (user → AI assistant → human admin, one conversation).

ISOLATION: this module only reads/writes the three support_* tables plus
safe columns of users/projects for display. Nothing else in the codebase
imports it except api/support/. Ownership is ALWAYS enforced by filtering
on the server-resolved user_id — never a client-supplied one.

Status model:
    open → ai_handling → waiting_for_admin → admin_active → resolved
    (resolved can reopen to waiting_for_admin; admin can hand back to AI)
responder_mode ('ai' | 'admin') gates WHO may reply: while 'admin', the
AI responder is paused for that conversation.
"""

import logging
from typing import Any, Dict, List, Optional

from database_adapter import get_db

logger = logging.getLogger("support.conversations")

VALID_STATUSES = {"open", "ai_handling", "waiting_for_admin", "admin_active", "resolved"}
VALID_PRIORITIES = {"low", "normal", "high", "urgent"}


def _row(r) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return dict(r) if not isinstance(r, dict) else r


# ----------------------------------------------------------------------
# Fetch helpers (ownership enforced by caller-supplied, server-resolved ids)
# ----------------------------------------------------------------------

def get_conversation(conversation_id: int, *, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Fetch one conversation. If user_id given, ownership is enforced
    (returns None when the conversation belongs to someone else)."""
    with get_db() as conn:
        if user_id is not None:
            row = conn.execute(
                "SELECT * FROM support_conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM support_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
    return _row(row)


def list_user_conversations(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """The user's conversations with last message + unresolved info."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.*,
                      (SELECT message FROM support_messages m
                        WHERE m.conversation_id = c.id
                        ORDER BY m.id DESC LIMIT 1) AS last_message,
                      (SELECT sender_type FROM support_messages m
                        WHERE m.conversation_id = c.id
                        ORDER BY m.id DESC LIMIT 1) AS last_sender_type,
                      (SELECT COUNT(*) FROM support_messages m
                        WHERE m.conversation_id = c.id
                          AND m.read_at IS NULL
                          AND m.sender_type IN ('admin', 'system')) AS unread
               FROM support_conversations c
               WHERE c.user_id = ?
               ORDER BY c.updated_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [_row(r) for r in rows]


def open_conversation(user_id: int, project_id: Optional[int] = None,
                      category: Optional[str] = None) -> Dict[str, Any]:
    """Open (or reuse) the user's active conversation for this project.

    Reuse rule: if an un-resolved conversation exists for the same user +
    project, continue it — support is one continuous thread, not a new one
    per click. A resolved conversation is never reused.
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM support_conversations
               WHERE user_id = ? AND status <> 'resolved'
                 AND ((project_id IS NULL AND ?::int IS NULL) OR project_id = ?)
               ORDER BY updated_at DESC LIMIT 1""",
            (user_id, project_id, project_id),
        ).fetchone()
        existing = _row(row)
        if existing:
            return existing

        conn.execute(
            """INSERT INTO support_conversations (user_id, project_id, category, status)
               VALUES (?, ?, ?, 'ai_handling')""",
            (user_id, project_id, category),
        )
        conn.commit()
        new_row = conn.execute(
            "SELECT * FROM support_conversations WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    conv = _row(new_row)
    add_message(conv["id"], "system", None,
                "DreamAgent Support Assistant connected. How can we help you today?")
    return conv


# ----------------------------------------------------------------------
# Messages
# ----------------------------------------------------------------------

def add_message(conversation_id: int, sender_type: str, sender_id: Optional[int],
                message: str) -> Dict[str, Any]:
    """Append a message and bump the conversation's updated_at."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO support_messages (conversation_id, sender_type, sender_id, message)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, sender_type, sender_id, message),
        )
        conn.execute(
            "UPDATE support_conversations SET updated_at = NOW() WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM support_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
    return _row(row)


def get_messages(conversation_id: int, after_id: int = 0,
                 limit: int = 200) -> List[Dict[str, Any]]:
    """Messages with id > after_id (reconnect-safe incremental sync)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM support_messages
               WHERE conversation_id = ? AND id > ?
               ORDER BY id ASC LIMIT ?""",
            (conversation_id, after_id, limit),
        ).fetchall()
    return [_row(r) for r in rows]


def mark_read(conversation_id: int, *, reader: str) -> int:
    """Mark messages read. reader='user' clears admin/system messages;
    reader='admin' clears user messages."""
    sender_types = ("admin", "system") if reader == "user" else ("user",)
    placeholders = ", ".join("?" for _ in sender_types)
    with get_db() as conn:
        cur = conn.execute(
            f"""UPDATE support_messages SET read_at = NOW()
                WHERE conversation_id = ? AND read_at IS NULL
                  AND sender_type IN ({placeholders})""",
            (conversation_id, *sender_types),
        )
        conn.commit()
        return cur.rowcount if hasattr(cur, "rowcount") else 0


# ----------------------------------------------------------------------
# State transitions
# ----------------------------------------------------------------------

def _set(conn, conversation_id: int, **fields: Any) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE support_conversations SET {cols}, updated_at = NOW() WHERE id = ?",
        (*fields.values(), conversation_id),
    )


def escalate_to_admin(conversation_id: int, *, reason: str = "") -> None:
    """AI → human handoff. Pauses the AI (responder_mode='admin')."""
    with get_db() as conn:
        _set(conn, conversation_id, status="waiting_for_admin", responder_mode="admin")
        conn.commit()
    note = "Conversation escalated to DreamAgent Support." + (f" Reason: {reason}" if reason else "")
    add_message(conversation_id, "system", None, note)
    logger.info("[SUPPORT] conversation %s escalated to admin (%s)", conversation_id, reason or "unspecified")


def admin_take_over(conversation_id: int, admin_id: int) -> None:
    with get_db() as conn:
        _set(conn, conversation_id, status="admin_active", responder_mode="admin",
             assigned_admin_id=admin_id)
        conn.commit()
    logger.info("[SUPPORT] admin %s took over conversation %s", admin_id, conversation_id)


def admin_reply(conversation_id: int, admin_id: int, message: str) -> Dict[str, Any]:
    with get_db() as conn:
        _set(conn, conversation_id, status="admin_active", responder_mode="admin",
             assigned_admin_id=admin_id)
        conn.commit()
    return add_message(conversation_id, "admin", admin_id, message)


def hand_back_to_ai(conversation_id: int, admin_id: int, note: str = "") -> None:
    """Admin returns the conversation to the AI assistant."""
    with get_db() as conn:
        _set(conn, conversation_id, status="ai_handling", responder_mode="ai")
        conn.commit()
    msg = "Admin handed this conversation back to the AI assistant."
    if note:
        msg += f" Resolution note: {note}"
    add_message(conversation_id, "system", None, msg)
    logger.info("[SUPPORT] admin %s handed conversation %s back to AI", admin_id, conversation_id)


def set_priority(conversation_id: int, priority: str) -> None:
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"invalid priority: {priority}")
    with get_db() as conn:
        _set(conn, conversation_id, priority=priority)
        conn.commit()


def assign_admin(conversation_id: int, admin_id: Optional[int]) -> None:
    with get_db() as conn:
        _set(conn, conversation_id, assigned_admin_id=admin_id)
        conn.commit()


def resolve(conversation_id: int, admin_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE support_conversations SET status = 'resolved', resolved_at = NOW(), updated_at = NOW() WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()
    add_message(conversation_id, "system", None,
                "Conversation marked as resolved. Reply anytime to reopen.")
    logger.info("[SUPPORT] admin %s resolved conversation %s", admin_id, conversation_id)


def reopen(conversation_id: int, *, by_admin: bool) -> None:
    """Reopen a resolved conversation (user reply or admin action)."""
    target = "waiting_for_admin" if by_admin else "ai_handling"
    mode = "admin" if by_admin else "ai"
    with get_db() as conn:
        conn.execute(
            """UPDATE support_conversations
               SET status = ?, responder_mode = ?, resolved_at = NULL, updated_at = NOW()
               WHERE id = ?""",
            (target, mode, conversation_id),
        )
        conn.commit()


def bump_typing(conversation_id: int, who: str) -> None:
    col = "user_typing_at" if who == "user" else "admin_typing_at"
    with get_db() as conn:
        conn.execute(
            f"UPDATE support_conversations SET {col} = NOW() WHERE id = ?",
            (conversation_id,),
        )
        conn.commit()


def set_summary(conversation_id: int, summary: str) -> None:
    with get_db() as conn:
        _set(conn, conversation_id, summary=summary[:200])
        conn.commit()


# ----------------------------------------------------------------------
# Admin inbox views
# ----------------------------------------------------------------------

def admin_inbox(status: Optional[str] = None, page: int = 0, page_size: int = 30,
                ) -> List[Dict[str, Any]]:
    """Admin inbox rows: user info, last message, unread, project, admin."""
    where = "WHERE c.status = ?" if status and status in VALID_STATUSES else ""
    params = (status,) if where else ()
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT c.*,
                       u.email AS user_email, u.name AS user_name,
                       p.name AS project_name,
                       a.email AS admin_email,
                       (SELECT message FROM support_messages m
                         WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_message,
                       (SELECT COUNT(*) FROM support_messages m
                         WHERE m.conversation_id = c.id
                           AND m.read_at IS NULL AND m.sender_type = 'user') AS unread
                FROM support_conversations c
                JOIN users u ON u.id = c.user_id
                LEFT JOIN projects p ON p.id = c.project_id
                LEFT JOIN users a ON a.id = c.assigned_admin_id
                {where}
                ORDER BY
                  CASE c.status WHEN 'waiting_for_admin' THEN 0 WHEN 'admin_active' THEN 1
                       WHEN 'ai_handling' THEN 2 WHEN 'open' THEN 3 ELSE 4 END,
                  c.updated_at DESC
                LIMIT ? OFFSET ?""",
            (*params, page_size, page * page_size),
        ).fetchall()
    return [_row(r) for r in rows]


def admin_unread_count() -> int:
    """Conversations with unread user messages or waiting for an admin."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n FROM support_conversations c
               WHERE c.status = 'waiting_for_admin'
                  OR EXISTS (SELECT 1 FROM support_messages m
                             WHERE m.conversation_id = c.id
                               AND m.read_at IS NULL AND m.sender_type = 'user')"""
        ).fetchone()
    d = _row(row) or {}
    return int(d.get("n", 0))


def admin_add_note(conversation_id: int, admin_id: int, note: str) -> Dict[str, Any]:
    """Internal note — visible to admins only, never shown to users."""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO support_internal_notes (conversation_id, admin_id, note) VALUES (?, ?, ?)",
            (conversation_id, admin_id, note),
        )
        conn.commit()
        row = conn.execute(
            """SELECT n.*, u.email AS admin_email FROM support_internal_notes n
               JOIN users u ON u.id = n.admin_id
               WHERE n.conversation_id = ? ORDER BY n.id DESC LIMIT 1""",
            (conversation_id,),
        ).fetchone()
    return _row(row)


def admin_list_notes(conversation_id: int) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT n.*, u.email AS admin_email FROM support_internal_notes n
               JOIN users u ON u.id = n.admin_id
               WHERE n.conversation_id = ? ORDER BY n.id ASC""",
            (conversation_id,),
        ).fetchall()
    return [_row(r) for r in rows]
