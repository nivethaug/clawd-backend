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
ACPX_TIMEOUT = 900  # 15 minutes for interactive chat
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
## CONVERSATION HISTORY

{session_context}

---
"""
        
        return f"""You are a friendly AI assistant helping a user build their **{self.project_name}** web application.

{context_section}
## USER'S REQUEST

{user_message}

---

## HOW TO RESPOND

**IMPORTANT: The user is a NON-TECHNICAL person building an app. Adjust your response accordingly:**

1. **Default Mode (Non-Technical)**:
   - Explain what you're doing in simple, plain English
   - Focus on the OUTCOME, not the implementation details
   - Example: "I'll add a contact form to your page" NOT "I'll create a new component with useState hooks"
   - Only show file changes if the user asks to see them
   - Keep responses conversational and friendly

2. **Technical Mode (Only When Asked)**:
   - If user asks "show me the code", "technical details", "file structure", etc.
   - Then you can show folder structure, code snippets, implementation details
   - Start with project.json in the root folder
   - Navigate to frontend/backend folders as needed

## PROJECT CONTEXT

Project Name: **{self.project_name}**
Project Root: {self.frontend_src_path.parent.parent}

**Key Files:**
- `project.json` (root) - Project information
- `frontend/` - React app (pages, components)
- `backend/` - API server (if applicable)

## WHAT YOU CAN DO

- Add features (forms, pages, buttons, etc.)
- Fix issues and bugs
- Improve design and layout
- Add new pages or sections
- Modify existing features

## RESPONSE STYLE

✅ Good: "I've added a nice contact form with name, email, and message fields to your page."
❌ Bad: "Created ContactForm.tsx component with React Hook Form validation..."

✅ Good: "Your app is now working! The login page has email and password fields."
❌ Bad: "Modified src/pages/Login.tsx with controlled inputs and useState..."

**Always prioritize user-friendly language unless they ask for technical details!**

---

## ⛔ CRITICAL OUTPUT RULES - NEVER VIOLATE

**DO NOT OUTPUT ANY OF THE FOLLOWING:**
- File paths or directory listings (e.g., `files: /root/...`, `output: /path/to/file`)
- Tool execution logs (e.g., `input:`, `output:`, `files:`)
- Shell commands (e.g., `ls -la`, `grep`, `ps aux`)
- JSON-RPC or protocol messages (e.g., `{{"jsonrpc":...}}`)
- Code line numbers or diffs
- Internal thinking or tool calls
- Process information or system commands

**ONLY OUTPUT:**
1. Friendly, conversational text explaining what you're doing
2. The actual result/outcome for the user
3. Simple bullet points or numbered lists if needed

**Example:**
❌ WRONG: 
```
files: /root/project/frontend
output:
  /root/project/frontend/package.json
  /root/project/frontend/src/App.tsx
```

✅ CORRECT:
```
I've checked your app and everything looks great! Your NatureStream app has:
- A homepage with beautiful design
- Working navigation
- Contact form ready to use
```
"""

    
    def _is_inline_noise(self, line: str) -> bool:
        """Check if a line is inline telemetry/noise (matching telegram-acpx-devbot)"""
        if not line or not line.strip():
            return True
            
        line_lower = line.lower().strip()
        
        # Skip JSON/telemetry markers
        if line_lower in ['{', '}', '(', ')', '[', ']', 'jsonrpc:', 'error handling notification {']:
            return True
            
        # Skip structured protocol logs
        noise_patterns = [
            'sessionupdate:', 'session/update', 'usage_update', '_errors:',
            '[array]', '[object]', 'invalid params', 'invalid input',
            'error handling notification', 'end_turn', '[done]', '[thinking]',
            '[tool]', '[console]', '[client]', 'client] initialize', 'session/new',
            'initialize (running)', 'session/new (running)', 'code:', 'message:',
            'method:', 'params:', 'data:', 'result:', 'id:', 'cost:', 'size:',
            'used:', 'entry:', 'availablecommands:', 'currentmodeid:',
            'configoptions:', 'title:', 'toolcallid:', 'jsonrpc:'
        ]
        
        return any(pattern in line_lower for pattern in noise_patterns)
    
    def _is_useful_line(self, line: str) -> bool:
        """Check if line contains useful info (whitelist approach)"""
        line_lower = line.lower().strip()
        
        # Whitelist: actual content keywords
        useful_patterns = [
            'creating', 'created', 'writing', 'reading', 'editing', 'updated',
            'deleting', 'removing', 'saving', 'file', 'folder', 'src/',
            '.py', '.js', '.tsx', '.ts', '.css', '.html', '.json',
            'done', 'completed', 'success', 'finished', 'running', 'executing',
            'processing', 'analyzing', 'building', 'installing', 'generating',
            'git', 'commit', 'push', 'pull', 'package', 'npm', 'output:',
            'result:', 'added', 'changed', 'modified', 'hello', 'help',
            'what', 'how', 'can', 'will', 'let me', 'i can', 'you can',
            'features', 'pages', 'components', 'build', 'fix', 'bug',
            'react', 'vite', 'typescript', 'saas', 'application', 'assist',
            'working', 'today', 'would you like'
        ]
        
        return any(pattern in line_lower for pattern in useful_patterns)
    
    def _filter_blocks(self, raw_text: str) -> str:
        """
        Filter out entire JSON/telemetry blocks (from telegram-acpx-devbot)
        
        Uses brace/bracket depth tracking to skip entire JSON blocks.
        """
        lines = raw_text.split('\n')
        clean_lines = []
        skip_block = False
        brace_depth = 0
        bracket_depth = 0
        
        for line in lines:
            stripped = line.strip()
            line_lower = stripped.lower()
            
            # Skip single-character braces
            if stripped in ['{', '}', '[', ']', '(', ')']:
                if stripped == '{':
                    brace_depth += 1
                    if brace_depth == 1:
                        skip_block = True
                elif stripped == '}':
                    if brace_depth > 0:
                        brace_depth -= 1
                        if brace_depth == 0:
                            skip_block = False
                elif stripped == '[':
                    bracket_depth += 1
                    if bracket_depth == 1:
                        skip_block = True
                elif stripped == ']':
                    if bracket_depth > 0:
                        bracket_depth -= 1
                        if bracket_depth == 0:
                            skip_block = False
                continue
            
            # Detect error notification blocks
            if 'error handling notification {' in line_lower:
                skip_block = True
                brace_depth += 1
                continue
            
            # Skip everything in active blocks
            if skip_block or brace_depth > 0 or bracket_depth > 0:
                continue
            
            # Skip inline noise
            if self._is_inline_noise(line):
                continue
            
            # Keep useful lines
            if self._is_useful_line(line):
                clean_lines.append(stripped)
        
        return '\n'.join(clean_lines)
    
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
        
        # Log prompt structure
        logger.info(f"[ACP-CHAT] === PROMPT STRUCTURE ===")
        logger.info(f"[ACP-CHAT] System message: Included")
        logger.info(f"[ACP-CHAT] Conversation history: {'Included (' + str(len(session_context)) + ' chars)' if session_context else 'None'}")
        logger.info(f"[ACP-CHAT] User message: {len(user_message)} chars")
        logger.info(f"[ACP-CHAT] Total prompt: {len(prompt)} chars")
        
        # Log full prompt for debugging (split into multiple lines for readability)
        prompt_lines = prompt.split('\n')
        total_lines = len(prompt_lines)
        logger.info(f"[ACP-CHAT] === PROMPT PREVIEW (first 20 lines) ===")
        for i, line in enumerate(prompt_lines[:20], 1):
            logger.info(f"[ACP-CHAT] {i:2d}| {line}")
        if total_lines > 20:
            remaining = total_lines - 20
            logger.info(f"[ACP-CHAT] ... ({remaining} more lines)")
        logger.info(f"[ACP-CHAT] === END PROMPT PREVIEW ===")
        
        # Build command - use stdbuf for line buffering (matching telegram-acpx-devbot)
        # Direct node execution is more reliable than acpx wrapper
        acpx_path = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"
        
        cmd = [
            "stdbuf", "-oL",  # Line-buffered output for real-time streaming
            "node", acpx_path,
            "claude", "exec",
            "--no-thinking",  # Disable thinking/reasoning output
            str(prompt)
        ]
        
        logger.info(f"[ACP-CHAT] Running ACPX for project: {self.project_name}")
        logger.info(f"[ACP-CHAT] Working directory: {self.frontend_src_path}")
        logger.info(f"[ACP-CHAT] User message: {user_message[:100]}...")
        logger.info(f"[ACP-CHAT] Command: stdbuf -oL node {acpx_path} claude exec <prompt>")
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
            
            # Set environment to disable thinking/reasoning output
            env = os.environ.copy()
            env["CLAUDE_DISABLE_THINKING"] = "1"
            env["DISABLE_THINKING"] = "1"
            env["NO_THINKING"] = "1"
            
            # Run ACPX with timeout (matching telegram-acpx-devbot pattern)
            logger.info(f"[ACP-CHAT] Starting subprocess...")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout (like working bot)
                text=True,
                bufsize=1,  # CRITICAL: Line-buffered for real-time streaming
                cwd=str(self.frontend_src_path),
                universal_newlines=True,
                env=env  # Pass environment with thinking disabled
            )
            
            logger.info(f"[ACP-CHAT] Subprocess started with PID: {process.pid}")
            
            stdout_lines = []
            raw_output = []  # Collect all raw output for block filtering
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
                        raw_output.append(remaining)
                    break
                
                line = line.rstrip('\n\r')
                if line:
                    raw_output.append(line)
                    logger.info(f"[ACP-CHAT] stdout: {line[:100]}")
            
            # Wait for process to complete
            return_code = process.wait() if process.poll() is None else process.returncode
            
            # Apply block-level filtering to raw output
            raw_text = '\n'.join(raw_output)
            stdout_output = self._filter_blocks(raw_text)
            
            logger.info(f"[ACP-CHAT] ACPX completed with return code: {return_code}")
            logger.info(f"[ACP-CHAT] Raw output: {len(raw_text)} chars, filtered: {len(stdout_output)} chars")
            
            if timeout_killed:
                return {
                    "status": "timeout",
                    "success": False,
                    "response": stdout_output or "The operation timed out. Please try with a simpler request.",
                    "error": f"Timeout after {ACPX_TIMEOUT}s"
                }
            
            # Return code -6 (SIGABRT) is from orphan cleanup - treat as success if we have output
            # Return code 0 is normal success
            is_success = (return_code == 0 or return_code == -6) and stdout_output
            
            if not is_success and not stdout_output:
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
    
    def run_acpx_chat_streaming(self, user_message: str, session_context: str = ""):
        """
        Run ACPX chat and yield progress in real-time (generator for SSE streaming).
        
        This method yields progress updates as ACPX produces output, providing
        real-time feedback to users instead of waiting for completion.
        
        Args:
            user_message: User's chat message
            session_context: Previous conversation context
            
        Yields:
            Str strings with filtered progress updates
        """
        prompt = self._build_chat_prompt(user_message, session_context)
        
        # Log prompt structure
        logger.info(f"[ACP-CHAT] === STREAMING MODE ===")
        logger.info(f"[ACP-CHAT] Total prompt: {len(prompt)} chars, timeout: {ACPX_TIMEOUT}s")
        
        # Build command - include --no-thinking flag
        acpx_path = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"
        cmd = ["stdbuf", "-oL", "node", acpx_path, "claude", "exec", "--no-thinking", str(prompt)]
        
        # Set environment to disable thinking/reasoning output
        env = os.environ.copy()
        env["CLAUDE_DISABLE_THINKING"] = "1"
        env["DISABLE_THINKING"] = "1"
        env["NO_THINKING"] = "1"
        
        logger.info(f"[ACP-CHAT] Starting streaming subprocess...")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=str(self.frontend_src_path),
                universal_newlines=True,
                env=env  # Pass environment with thinking disabled
            )
            
            logger.info(f"[ACP-CHAT] Subprocess PID: {process.pid}")
            
            raw_output = []
            start_time = time.time()
            
            # Stream output line by line
            while True:
                line = process.stdout.readline()
                
                # Check timeout
                if time.time() - start_time > ACPX_TIMEOUT:
                    logger.warning(f"[ACP-CHAT] Timeout")
                    process.kill()
                    return
                
                # Process exited
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        raw_output.append(remaining)
                    break
                
                line = line.rstrip('\n\r')
                if line:
                    raw_output.append(line)
                    logger.info(f"[ACP-CHAT] Line: {line[:80]}")
                    
                    # Yield useful lines immediately for real-time feedback
                    if self._is_useful_line(line) and not self._is_inline_noise(line):
                        yield line + "\n"
            
            # Process completed - apply block-level filtering
            raw_text = '\n'.join(raw_output)
            final_output = self._filter_blocks(raw_text)
            
            logger.info(f"[ACP-CHAT] Completed: {len(raw_text)} chars raw → {len(final_output)} chars filtered")
            
            # Kill orphan processes
            self.kill_orphan_processes()
            
            # No need for completion marker - user sees real-time output
                
        except Exception as e:
            logger.error(f"[ACP-CHAT] Stream error: {e}")
            yield f"Error: {str(e)}\n"
            yield f"\n[ERROR] {str(e)}\n"


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
