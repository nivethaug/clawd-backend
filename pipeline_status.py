#!/usr/bin/env python3
"""
Pipeline Status Module for DreamPilot

Provides structured status tracking for the project creation pipeline.
Each phase reports its status with detailed error codes when failures occur.

## Pipeline Phases
1. planner - Page planning and template selection
2. scaffold - File scaffolding from template
3. acpx - AI-powered frontend customization
4. router - React Router and navigation updates
5. build - Frontend build (npm run build)
6. deploy - Infrastructure deployment (nginx, PM2)

## Status Values
- pending: Phase not yet started
- running: Phase in progress
- completed: Phase completed successfully
- failed: Phase failed with error code

## Error Codes
Detailed error codes for specific failure scenarios:
- ACPX_TIMEOUT: ACPX execution exceeded time limit
- ACPX_BUILD_FAILED: Build failed after ACPX changes
- SCAFFOLD_FAILED: Page scaffolding failed
- ROUTER_UPDATE_FAILED: Router/navigation update failed
- BUILD_FAILED: Frontend build failed
- DEPLOY_FAILED: Deployment verification failed
- DOMAIN_NOT_RESOLVING: Domain does not resolve
- HTTP_NOT_200: Domain resolves but doesn't return HTTP 200
"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class PipelinePhase(str, Enum):
    """Pipeline phases in execution order."""
    PLANNER = "planner"
    SCAFFOLD = "scaffold"
    ACPX = "acpx"
    ROUTER = "router"
    BUILD = "build"
    DEPLOY = "deploy"


class PhaseStatus(str, Enum):
    """Status values for each phase."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ErrorCode(str, Enum):
    """Detailed error codes for pipeline failures."""
    # Planner errors
    PLANNER_TIMEOUT = "PLANNER_TIMEOUT"
    PLANNER_INVALID_OUTPUT = "PLANNER_INVALID_OUTPUT"
    
    # Scaffold errors
    SCAFFOLD_FAILED = "SCAFFOLD_FAILED"
    SCAFFOLD_MISSING_PAGES = "SCAFFOLD_MISSING_PAGES"
    TEMPLATE_CLONE_FAILED = "TEMPLATE_CLONE_FAILED"
    
    # ACPX errors
    ACPX_TIMEOUT = "ACPX_TIMEOUT"
    ACPX_BUILD_FAILED = "ACPX_BUILD_FAILED"
    ACPX_VALIDATION_FAILED = "ACPX_VALIDATION_FAILED"
    ACPX_PATH_FORBIDDEN = "ACPX_PATH_FORBIDDEN"
    ACPX_FILE_LIMIT_EXCEEDED = "ACPX_FILE_LIMIT_EXCEEDED"
    ACPX_ROLLBACK = "ACPX_ROLLBACK"
    
    # Router errors
    ROUTER_UPDATE_FAILED = "ROUTER_UPDATE_FAILED"
    NAV_UPDATE_FAILED = "NAV_UPDATE_FAILED"
    
    # Build errors
    BUILD_FAILED = "BUILD_FAILED"
    BUILD_TIMEOUT = "BUILD_TIMEOUT"
    BUILD_DIST_MISSING = "BUILD_DIST_MISSING"
    
    # Deploy errors
    DEPLOY_FAILED = "DEPLOY_FAILED"
    NGINX_CONFIG_FAILED = "NGINX_CONFIG_FAILED"
    PM2_START_FAILED = "PM2_START_FAILED"
    DOMAIN_NOT_RESOLVING = "DOMAIN_NOT_RESOLVING"
    HTTP_NOT_200 = "HTTP_NOT_200"
    INDEX_HTML_MISSING = "INDEX_HTML_MISSING"
    
    # General errors
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"


class PipelineStatusTracker:
    """
    Tracks pipeline progress for a project.
    
    Usage:
        tracker = PipelineStatusTracker(project_id, db_connection)
        tracker.start_phase(PipelinePhase.PLANNER)
        # ... do work ...
        tracker.complete_phase(PipelinePhase.PLANNER)
        
        # On failure:
        tracker.fail_phase(PipelinePhase.ACPX, ErrorCode.ACPX_TIMEOUT, "Timed out after 60s")
    """
    
    def __init__(self, project_id: int, db_conn=None):
        """
        Initialize status tracker.
        
        Args:
            project_id: Project ID in database
            db_conn: Database connection (optional, uses get_db() if not provided)
        """
        self.project_id = project_id
        self.db_conn = db_conn
        self._status: Dict[str, Any] = {}
        
    def _get_db(self):
        """Get database connection."""
        if self.db_conn:
            return self.db_conn
        from database_adapter import get_db
        return get_db()
    
    def _load_status(self) -> Dict[str, Any]:
        """Load current pipeline status from database."""
        try:
            with self._get_db() as conn:
                result = conn.execute(
                    "SELECT pipeline_status FROM projects WHERE id = ?",
                    (self.project_id,)
                ).fetchone()
                
                if result:
                    # Handle both dict and tuple results
                    if isinstance(result, dict):
                        status = result.get('pipeline_status', {})
                    else:
                        status = result[0] if result[0] else {}
                    
                    # Parse JSON if string
                    if isinstance(status, str):
                        status = json.loads(status) if status else {}
                    
                    return status
                return {}
        except Exception as e:
            logger.error(f"Failed to load pipeline status: {e}")
            return {}
    
    def _save_status(self, status: Dict[str, Any]) -> bool:
        """Save pipeline status to database."""
        try:
            status_json = json.dumps(status)
            with self._get_db() as conn:
                conn.execute(
                    "UPDATE projects SET pipeline_status = ? WHERE id = ?",
                    (status_json, self.project_id)
                )
                conn.commit()
            logger.debug(f"Saved pipeline status for project {self.project_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save pipeline status: {e}")
            return False
    
    def _save_error_code(self, error_code: Optional[str]) -> bool:
        """Save error code to database."""
        try:
            with self._get_db() as conn:
                conn.execute(
                    "UPDATE projects SET error_code = ? WHERE id = ?",
                    (error_code, self.project_id)
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save error code: {e}")
            return False
    
    def initialize(self) -> None:
        """Initialize all phases to pending status."""
        status = {
            phase.value: {
                "status": PhaseStatus.PENDING.value,
                "started_at": None,
                "completed_at": None,
                "error_code": None,
                "error_message": None,
                "duration_seconds": None
            }
            for phase in PipelinePhase
        }
        status["initialized_at"] = datetime.utcnow().isoformat()
        self._save_status(status)
        self._status = status
        logger.info(f"[Pipeline] Initialized status tracking for project {self.project_id}")
    
    def start_phase(self, phase: PipelinePhase) -> None:
        """
        Mark a phase as running.
        
        Args:
            phase: The pipeline phase to start
        """
        status = self._load_status()
        status[phase.value] = {
            "status": PhaseStatus.RUNNING.value,
            "started_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "error_code": None,
            "error_message": None,
            "duration_seconds": None
        }
        self._save_status(status)
        self._status = status
        logger.info(f"[Pipeline] Phase {phase.value} started for project {self.project_id}")
    
    def complete_phase(self, phase: PipelinePhase, metadata: Dict[str, Any] = None) -> None:
        """
        Mark a phase as completed successfully.
        
        Args:
            phase: The pipeline phase that completed
            metadata: Optional additional metadata to store
        """
        status = self._load_status()
        started_at = status.get(phase.value, {}).get("started_at")
        
        # Calculate duration
        duration = None
        if started_at:
            try:
                start = datetime.fromisoformat(started_at)
                duration = (datetime.utcnow() - start).total_seconds()
            except (ValueError, TypeError):
                pass
        
        phase_status = {
            "status": PhaseStatus.COMPLETED.value,
            "started_at": started_at,
            "completed_at": datetime.utcnow().isoformat(),
            "error_code": None,
            "error_message": None,
            "duration_seconds": duration
        }
        
        # Add metadata if provided
        if metadata:
            phase_status["metadata"] = metadata
        
        status[phase.value] = phase_status
        self._save_status(status)
        self._status = status
        
        # Clear any previous error code
        self._save_error_code(None)
        
        logger.info(f"[Pipeline] Phase {phase.value} completed for project {self.project_id} ({duration:.1f}s)" if duration else f"[Pipeline] Phase {phase.value} completed for project {self.project_id}")
    
    def skip_phase(self, phase: PipelinePhase, reason: str = None) -> None:
        """
        Mark a phase as skipped.
        
        Args:
            phase: The pipeline phase to skip
            reason: Optional reason for skipping
        """
        status = self._load_status()
        status[phase.value] = {
            "status": PhaseStatus.SKIPPED.value,
            "started_at": None,
            "completed_at": datetime.utcnow().isoformat(),
            "error_code": None,
            "error_message": None,
            "duration_seconds": 0,
            "skip_reason": reason
        }
        self._save_status(status)
        self._status = status
        logger.info(f"[Pipeline] Phase {phase.value} skipped for project {self.project_id}: {reason}")
    
    def fail_phase(
        self, 
        phase: PipelinePhase, 
        error_code: ErrorCode, 
        error_message: str = None
    ) -> None:
        """
        Mark a phase as failed with detailed error code.
        
        Args:
            phase: The pipeline phase that failed
            error_code: Specific error code for the failure
            error_message: Human-readable error message
        """
        status = self._load_status()
        started_at = status.get(phase.value, {}).get("started_at")
        
        # Calculate duration
        duration = None
        if started_at:
            try:
                start = datetime.fromisoformat(started_at)
                duration = (datetime.utcnow() - start).total_seconds()
            except (ValueError, TypeError):
                pass
        
        status[phase.value] = {
            "status": PhaseStatus.FAILED.value,
            "started_at": started_at,
            "completed_at": datetime.utcnow().isoformat(),
            "error_code": error_code.value,
            "error_message": error_message,
            "duration_seconds": duration
        }
        self._save_status(status)
        self._status = status
        
        # Save error code to main column for easy querying
        self._save_error_code(error_code.value)
        
        logger.error(f"[Pipeline] Phase {phase.value} FAILED for project {self.project_id}: {error_code.value} - {error_message}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status."""
        return self._load_status()
    
    def get_phase_status(self, phase: PipelinePhase) -> PhaseStatus:
        """Get status of a specific phase."""
        status = self._load_status()
        phase_data = status.get(phase.value, {})
        return PhaseStatus(phase_data.get("status", PhaseStatus.PENDING.value))
    
    def is_phase_complete(self, phase: PipelinePhase) -> bool:
        """Check if a phase is completed (or skipped)."""
        phase_status = self.get_phase_status(phase)
        return phase_status in (PhaseStatus.COMPLETED, PhaseStatus.SKIPPED)
    
    def get_progress_summary(self) -> Dict[str, Any]:
        """
        Get a summary of pipeline progress.
        
        Returns:
            Dict with completion counts and overall status
        """
        status = self._load_status()
        
        completed = 0
        failed = 0
        running = 0
        pending = 0
        skipped = 0
        
        for phase in PipelinePhase:
            phase_data = status.get(phase.value, {})
            phase_status = phase_data.get("status", PhaseStatus.PENDING.value)
            
            if phase_status == PhaseStatus.COMPLETED.value:
                completed += 1
            elif phase_status == PhaseStatus.FAILED.value:
                failed += 1
            elif phase_status == PhaseStatus.RUNNING.value:
                running += 1
            elif phase_status == PhaseStatus.SKIPPED.value:
                skipped += 1
            else:
                pending += 1
        
        total = len(PipelinePhase)
        progress_percent = ((completed + skipped) / total) * 100 if total > 0 else 0
        
        # Determine overall status
        if failed > 0:
            overall = "failed"
        elif running > 0:
            overall = "running"
        elif completed + skipped == total:
            overall = "completed"
        else:
            overall = "pending"
        
        # Get error code if any
        error_code = None
        for phase in PipelinePhase:
            phase_data = status.get(phase.value, {})
            if phase_data.get("status") == PhaseStatus.FAILED.value:
                error_code = phase_data.get("error_code")
                break
        
        return {
            "overall_status": overall,
            "progress_percent": round(progress_percent, 1),
            "phases": {
                "completed": completed,
                "failed": failed,
                "running": running,
                "pending": pending,
                "skipped": skipped,
                "total": total
            },
            "error_code": error_code,
            "current_phase": self._get_current_phase(status)
        }
    
    def _get_current_phase(self, status: Dict[str, Any]) -> Optional[str]:
        """Get the currently running phase, if any."""
        for phase in PipelinePhase:
            phase_data = status.get(phase.value, {})
            if phase_data.get("status") == PhaseStatus.RUNNING.value:
                return phase.value
        return None


def format_status_report(status: Dict[str, Any]) -> str:
    """
    Format pipeline status as human-readable report.
    
    Args:
        status: Pipeline status dict
        
    Returns:
        Formatted string report
    """
    lines = ["📊 Pipeline Status Report", "=" * 40]
    
    for phase in PipelinePhase:
        phase_data = status.get(phase.value, {})
        phase_status = phase_data.get("status", PhaseStatus.PENDING.value)
        
        # Status emoji
        emoji = {
            PhaseStatus.PENDING.value: "⏳",
            PhaseStatus.RUNNING.value: "🔄",
            PhaseStatus.COMPLETED.value: "✅",
            PhaseStatus.FAILED.value: "❌",
            PhaseStatus.SKIPPED.value: "⏭️"
        }.get(phase_status, "❓")
        
        line = f"{emoji} {phase.value.upper()}: {phase_status}"
        
        # Add duration if available
        duration = phase_data.get("duration_seconds")
        if duration is not None:
            line += f" ({duration:.1f}s)"
        
        # Add error info if failed
        if phase_status == PhaseStatus.FAILED.value:
            error_code = phase_data.get("error_code", "UNKNOWN")
            line += f"\n   └─ Error: {error_code}"
            error_msg = phase_data.get("error_message")
            if error_msg:
                line += f" - {error_msg[:100]}"
        
        lines.append(line)
    
    return "\n".join(lines)
