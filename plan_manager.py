"""
Plan Manager — Handles plan file CRUD and session-plan lookups.
Plan files are temporary approval artifacts. The ai_index files are the
permanent source of truth.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from database_postgres import get_db

logger = logging.getLogger(__name__)


class PlanManager:

    @staticmethod
    def find_active_plan(session_id: int, project_id: int) -> Optional[str]:
        """
        Check if a plan file already exists for this session.
        Returns the plan file content if found, None otherwise.
        Checks DB first, then verifies file exists on disk.
        """
        with get_db() as conn:
            row = conn.execute(
                "SELECT file_path FROM plans WHERE session_id = %s AND project_id = %s AND status != 'completed'",
                (session_id, project_id)
            ).fetchone()
            if row and Path(row['file_path']).exists():
                return Path(row['file_path']).read_text(encoding='utf-8')
        return None

    @staticmethod
    def create_plan_dir(project_path: str) -> Path:
        plans_dir = Path(project_path) / "plans"
        plans_dir.mkdir(exist_ok=True)
        return plans_dir

    @staticmethod
    def save_plan_file(project_path: str, content: str) -> str:
        """Save plan file to disk. Called ONLY after user approval."""
        plans_dir = PlanManager.create_plan_dir(project_path)
        filename = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        file_path = plans_dir / filename
        file_path.write_text(content, encoding='utf-8')
        logger.info(f"[PLAN] Saved plan file: {file_path}")
        return str(file_path)

    @staticmethod
    def save_plan_metadata(session_id: int, project_id: int, file_path: str, title: Optional[str] = None) -> int:
        """Insert plan record into DB. Returns the plan ID."""
        with get_db() as conn:
            cur = conn.execute(
                """INSERT INTO plans (session_id, project_id, file_path, title, status, approved_at)
                   VALUES (%s, %s, %s, %s, 'approved', CURRENT_TIMESTAMP)
                   RETURNING id""",
                (session_id, project_id, file_path, title)
            )
            plan_id = cur.fetchone()['id']
            conn.commit()
            logger.info(f"[PLAN] Created plan record id={plan_id} for session={session_id}")
            return plan_id

    @staticmethod
    def get_plans_for_project(project_id: int) -> list:
        """Get all plans for a project."""
        with get_db() as conn:
            rows = conn.execute(
                """SELECT id, session_id, file_path, title, status, created_at, approved_at, executed_at
                   FROM plans WHERE project_id = %s ORDER BY created_at DESC""",
                (project_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    @staticmethod
    def get_plan_content(plan_id: int) -> Optional[str]:
        """Get plan file content by plan ID."""
        with get_db() as conn:
            row = conn.execute(
                "SELECT file_path FROM plans WHERE id = %s",
                (plan_id,)
            ).fetchone()
            if row and Path(row['file_path']).exists():
                return Path(row['file_path']).read_text(encoding='utf-8')
        return None

    @staticmethod
    def update_plan_status(plan_id: int, status: str):
        """Update plan status."""
        with get_db() as conn:
            if status == 'completed':
                conn.execute(
                    "UPDATE plans SET status = %s, executed_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (status, plan_id)
                )
            else:
                conn.execute(
                    "UPDATE plans SET status = %s WHERE id = %s",
                    (status, plan_id)
                )
            conn.commit()

    @staticmethod
    def delete_plan(session_id: int, project_id: int):
        """
        Delete plan file from disk and remove DB record.
        Called after Dream Mode completes execution and ai_index is updated.
        """
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, file_path FROM plans WHERE session_id = %s AND project_id = %s",
                (session_id, project_id)
            ).fetchall()
            for row in rows:
                file_path = Path(row['file_path'])
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"[PLAN] Deleted plan file: {file_path}")
                conn.execute("DELETE FROM plans WHERE id = %s", (row['id'],))
            conn.commit()
