#!/usr/bin/env python3
"""
ACP Chat Handler - Integrates ACPX for chat-based frontend editing.

This module provides chat mode for ACP (Agentic Code Protocol) that allows
users to edit frontend files through natural language conversation.
"""

import os
import subprocess
import time
import signal
import threading
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Configuration
ACPX_TIMEOUT = 120  # 2 minutes for chat responses (reduced from 5 min for faster feedback)
ALLOWED_PROJECTS_BASE = "/root/dreampilot/projects/website"


class ACPChatHandler:
    """Handles ACP chat mode for frontend editing."""
    
    def __init__(self, project_path: str, project_name: str = "Unknown"):
        """
        Initialize ACP chat handler.
        
        Args:
            project_path: Path to the project root
            project_name: Name of the project
        """
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.frontend_path = self.project_path / "frontend"
        self.frontend_src_path = self.frontend_path / "src"
        
        # Validate paths
        if not self.frontend_src_path.exists():
            raise ValueError(f"Frontend src path does not exist: {self.frontend_src_path}")
    
    def _build_chat_prompt(self, user_message: str, session_context: str = "") -> str:
        """
        Build a chat prompt for ACPX.
        
        Args:
            user_message: User's chat message
            session_context: Previous conversation context
            
        Returns:
            Prompt string for ACPX
        """
        context_section = ""
        if session_context:
            context_section = f"""
## CONVERSATION CONTEXT

{session_context}

---
"""
        
        return f"""You are an AI assistant helping with a React + Vite + TypeScript SaaS application.

Project Name: {self.project_name}
Project Path: {self.frontend_src_path}
{context_section}
## USER REQUEST

{user_message}

---

## RULES

**You can:**
- Read any file in the project
- Edit files in `src/pages/`, `src/components/`, `src/layout/`, `src/features/`
- Create new components or pages as needed
- Run `npm run build` to verify changes

**Never do:**
- Install new npm packages or modify `package.json`
- Run `npm install`, `npm add`, or `npm update`
- Modify files in `src/components/ui/` (use them, don't change them)
- Modify `vite.config.*`, `tsconfig.json`, or any backend/env files
- Change project architecture

**Available UI components** (from `src/components/ui/`):
Button, Card, Input, Label, Select, Textarea, Dialog, Sheet, Dropdown, Popover, Table, Badge, Avatar, Separator — and more.

**Icons:** `import {{ IconName }} from 'lucide-react'`

---

## RESPONSE FORMAT

1. First, briefly explain what you're going to do
2. Make the necessary file changes
3. Verify the changes work (run build if needed)
4. Summarize what was done

Be concise but thorough. Focus on the user's specific request.
"""
    
    def run_acpx_chat(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
        """
        Run ACPX chat and return the response.
        
        Args:
            user_message: User's chat message
            session_context: Previous conversation context
            
        Returns:
            Dict with status, response, and any error info
        """
        prompt = self._build_chat_prompt(user_message, session_context)
        
        # Build command - use stdbuf for line buffering (matching telegram-acpx-devbot)
        # Direct node execution is more reliable than acpx wrapper
        acpx_path = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"
        
        cmd = [
            "stdbuf", "-oL",  # Line-buffered output for real-time streaming
            "node", acpx_path,
            "claude", "exec",
            str(prompt)
        ]
        
        logger.info(f"[ACP-CHAT] Running ACPX for project: {self.project_name}")
        logger.info(f"[ACP-CHAT] Working directory: {self.frontend_src_path}")
        logger.info(f"[ACP-CHAT] User message: {user_message[:100]}...")
        logger.info(f"[ACP-CHAT] Command: acpx --format quiet claude exec <prompt>")
        logger.info(f"[ACP-CHAT] Prompt length: {len(prompt)} chars")
        
        try:
            # Check if acpx exists
            acpx_check = subprocess.run(
                ["which", "acpx"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if acpx_check.returncode != 0:
                logger.error(f"[ACP-CHAT] acpx not found in PATH")
                return {
                    "status": "error",
                    "success": False,
                    "response": "Error: acpx command not found. Please install ACPX first.",
                    "error": "acpx not found in PATH"
                }
            logger.info(f"[ACP-CHAT] acpx found at: {acpx_check.stdout.strip()}")
            
            # Run ACPX with timeout (matching telegram-acpx-devbot pattern)
            logger.info(f"[ACP-CHAT] Starting subprocess...")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout (like working bot)
                text=True,
                bufsize=1,  # CRITICAL: Line-buffered for real-time streaming
                cwd=str(self.frontend_src_path),
                universal_newlines=True
            )
            
            logger.info(f"[ACP-CHAT] Subprocess started with PID: {process.pid}")
            
            stdout_lines = []
            start_time = time.time()
            timeout_killed = False
            
            # Stream output line by line (matching telegram-acpx-devbot pattern)
            while True:
                line = process.stdout.readline()
                
                # Check for timeout
                elapsed = time.time() - start_time
                if elapsed > ACPX_TIMEOUT:
                    logger.warning(f"[ACP-CHAT] Timeout after {elapsed:.1f}s")
                    try:
                        process.terminate()
                        time.sleep(2)
                        if process.poll() is None:
                            process.kill()
                    except (ProcessLookupError, OSError):
                        pass
                    timeout_killed = True
                    break
                
                # Check if process has exited
                if process.poll() is not None:
                    # Read any remaining output
                    remaining = process.stdout.read()
                    if remaining:
                        stdout_lines.append(remaining)
                    break
                
                line = line.rstrip('\n\r')
                if line:
                    stdout_lines.append(line + '\n')
                    logger.info(f"[ACP-CHAT] stdout: {line[:100]}")
            
            # Wait for process to complete
            return_code = process.wait() if process.poll() is None else process.returncode
            
            # Collect output
            stdout_output = ''.join(stdout_lines)
            logger.info(f"[ACP-CHAT] ACPX completed with return code: {return_code}")
            logger.info(f"[ACP-CHAT] stdout length: {len(stdout_output)} chars")
            
            if timeout_killed:
                return {
                    "status": "timeout",
                    "success": False,
                    "response": stdout_output or "The operation timed out. Please try with a simpler request.",
                    "error": f"Timeout after {ACPX_TIMEOUT}s"
                }
            
            if return_code != 0 and not stdout_output:
                return {
                    "status": "error",
                    "success": False,
                    "response": f"ACPX failed with code {return_code}",
                    "error": "No output received"
                }
            
            return {
                "status": "success",
                "success": True,
                "response": stdout_output or "Operation completed successfully."
            }
            
        except Exception as e:
            logger.error(f"[ACP-CHAT] Exception: {e}")
            return {
                "status": "error",
                "success": False,
                "response": f"Error running ACPX: {str(e)}",
                "error": str(e)
            }
    
    def kill_orphan_processes(self):
        """Kill any orphan ACPX processes for this project."""
        try:
            # Find and kill claude-agent-acp processes
            result = subprocess.run(
                ["pgrep", "-f", "claude-agent-acp"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid:
                        try:
                            os.kill(int(pid), signal.SIGKILL)
                            logger.info(f"[ACP-CHAT] Killed orphan process: {pid}")
                        except (ProcessLookupError, OSError):
                            pass
        except Exception as e:
            logger.warning(f"[ACP-CHAT] Failed to kill orphan processes: {e}")


def get_acp_chat_handler(session_key: str, project_path: str = None) -> Optional[ACPChatHandler]:
    """
    Get or create an ACP chat handler for a session.
    
    Args:
        session_key: Session key for context
        project_path: Optional project path (will be inferred if not provided)
        
    Returns:
        ACPChatHandler instance or None if not available
    """
    from database_adapter import get_db
    
    # Get project path from session if not provided
    if not project_path:
        with get_db() as conn:
            session = conn.execute(
                """SELECT s.project_id, p.project_path, p.name 
                   FROM sessions s 
                   JOIN projects p ON s.project_id = p.id 
                   WHERE s.session_key = ?""",
                (session_key,)
            ).fetchone()
            
            if not session:
                return None
            
            project_path = session['project_path']
            project_name = session['name']
    else:
        project_name = Path(project_path).name
    
    if not project_path:
        return None
    
    # Validate project path
    frontend_src = Path(project_path) / "frontend" / "src"
    if not frontend_src.exists():
        logger.warning(f"[ACP-CHAT] Frontend src not found: {frontend_src}")
        return None
    
    return ACPChatHandler(project_path, project_name)
