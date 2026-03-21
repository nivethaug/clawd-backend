#!/usr/bin/env python3
"""
ACP Chat Handler - Integrates Claude Code Agent for chat-based frontend editing.

This module provides chat mode for frontend editing using Claude CLI directly.
Supports both ClaudeCodeAgent (async) and ACPX (fallback) backends.
"""

import os
import subprocess
import time
import signal
import threading
import logging
import asyncio
from typing import Dict, Any, Optional, Generator
from pathlib import Path

# Try to import ClaudeCodeAgent (preferred backend)
try:
    from claude_code_agent import ClaudeCodeAgent
    CLAUDE_AGENT_AVAILABLE = True
    logger_module = logging.getLogger(__name__)
    logger_module.info("[ACP-CHAT] ClaudeCodeAgent available - will use direct Claude CLI")
except ImportError:
    CLAUDE_AGENT_AVAILABLE = False
    logger_module = logging.getLogger(__name__)
    logger_module.warning("[ACP-CHAT] ClaudeCodeAgent not available - will use ACPX fallback")

logger = logging.getLogger(__name__)

# Configuration
ACPX_TIMEOUT = 900  # 15 minutes for interactive chat
ALLOWED_PROJECTS_BASE = "/root/dreampilot/projects/website"
USE_PREPROCESSOR = os.getenv("ACP_USE_PREPROCESSOR", "false").lower() == "true"  # DISABLED for ClaudeCodeAgent migration testing
USE_CLAUDE_AGENT = os.getenv("ACP_USE_CLAUDE_AGENT", "true").lower() == "true" and CLAUDE_AGENT_AVAILABLE  # Prefer Claude Agent


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
        self.claude_agent = None  # ClaudeCodeAgent instance (created on demand)
        
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
   - **ALWAYS check agent/README.md FIRST before reading source code:**
     - Frontend: Read `frontend/agent/README.md` for navigation guides
     - Backend: Read `backend/agent/README.md` for API guides and database schema
   - The agent READMEs contain AI-friendly guides - use them before diving into source!
   - Only read raw source files if README doesn't answer the question
   - Start with project.json in the root folder
   - Navigate to frontend/backend folders as needed

## PROJECT CONTEXT

Project Name: **{self.project_name}**
Project Root: {self.frontend_src_path.parent.parent}

**Key Files:**
- `project.json` (root) - Project information
- `frontend/agent/README.md` - **AI guide for frontend (READ FIRST for frontend questions)**
- `backend/agent/README.md` - **AI guide for backend (READ FIRST for backend questions)**
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
        """Check if a line is inline telemetry/noise - aggressively filter tool output"""
        if not line or not line.strip():
            return True
            
        line_lower = line.lower().strip()
        stripped = line.strip()
        
        # Skip JSON/telemetry markers
        if line_lower in ['{', '}', '(', ')', '[', ']', 'jsonrpc:', 'error handling notification {']:
            return True
        
        # Skip file paths (absolute paths with /)
        if stripped.startswith('/') and '/' in stripped[1:]:
            return True
        
        # Skip indented file paths (in tool output blocks)
        if stripped.startswith('/root/') or stripped.startswith('/home/'):
            return True
        
        # Skip line number format: "1→", "21→", etc. (common in file reads)
        if stripped and stripped[0].isdigit() and '→' in stripped[:4]:
            return True
        
        # Skip lines that are just continuation markers
        if stripped.startswith('... (') and 'more lines)' in stripped:
            return True
        
        # Skip system-reminder tags
        if '<system-reminder>' in stripped or '</system-reminder>' in stripped:
            return True
        
        # Skip console/code block markers
        if stripped in ['```', '```console', '```json', '```bash']:
            return True
        
        # Skip lines that are ONLY structural (just punctuation)
        if stripped in ['},', '],', '}, {', '], [', '{ },', '[ ],']:
            return True
        
        # Skip shell/terminal output lines
        if stripped.startswith('total ') and stripped[6:].isdigit():
            return True
        if stripped.startswith('drwx') or stripped.startswith('-rw'):
            return True
        if 'shell cwd' in line_lower:
            return True
        if 'unmet dependency' in line_lower:
            return True
        if stripped.startswith('├──') or stripped.startswith('└──'):
            return True
            
        # Skip structured protocol logs and tool output
        noise_patterns = [
            '[acpx]', '[thinking]', '[done]', '[tool]', '[console]', '[client]',
            'sessionupdate:', 'session/update', 'usage_update', '_errors:',
            '[array]', '[object]', 'invalid params', 'invalid input',
            'error handling notification', 'end_turn',
            'client] initialize', 'session/new',
            'initialize (running)', 'session/new (running)',
            'method:', 'params:', 'data:', 'result:', 'id:', 'cost:', 'size:',
            'used:', 'entry:', 'availablecommands:', 'currentmodeid:',
            'configoptions:', 'title:', 'toolcallid:', 'jsonrpc:',
            'session cwd', 'agent needs reconnect',
            'kind:', 'input:', 'output:', 'files:', 'pending)', 'completed)',
            'no files found', 'shell cwd was reset'
        ]
        
        if any(pattern in line_lower for pattern in noise_patterns):
            return True
        
        # Skip lines that start with these keywords (tool output format)
        tool_keywords = ['kind:', 'input:', 'output:', 'files:']
        for kw in tool_keywords:
            if line_lower.startswith(kw):
                return True
        
        return False
    
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
    
    async def run_claude_chat(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
        """
        Run Claude Code Agent and return response (preferred async method).
        
        Args:
            user_message: User's chat message
            session_context: Previous conversation context
            
        Returns:
            Dict with status, response, and any error info
        """
        try:
            # Build prompt with context
            full_prompt = user_message
            if session_context:
                full_prompt = f"Previous conversation:\n{session_context}\n\nCurrent request: {user_message}"
            
            logger.info(f"[CLAUDE-AGENT] Running for project: {self.project_name}")
            logger.info(f"[CLAUDE-AGENT] Working directory: {self.frontend_src_path}")
            logger.info(f"[CLAUDE-AGENT] User message: {user_message[:100]}...")
            logger.info(f"[CLAUDE-AGENT] Prompt length: {len(full_prompt)} chars")
            
            # Use ClaudeCodeAgent
            async with ClaudeCodeAgent(str(self.frontend_src_path)) as agent:
                response = await agent.query(full_prompt)
                
                logger.info(f"[CLAUDE-AGENT] Response received ({len(response)} chars)")
                logger.info(f"[CLAUDE-AGENT] Response preview: {response[:200]}...")
                
                return {
                    "status": "success",
                    "success": True,
                    "response": response,
                    "error": None,
                    "backend": "claude-agent"
                }
        
        except Exception as e:
            logger.error(f"[CLAUDE-AGENT] Error: {e}", exc_info=True)
            return {
                "status": "error",
                "success": False,
                "response": f"Error: {str(e)}",
                "error": str(e),
                "backend": "claude-agent"
            }
    
    def run_acpx_chat(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
        """
        Run ACPX chat and return the response (fallback synchronous method).
        
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
        
        # Build command - use acpx directly with clean output format
        cmd = [
            "stdbuf", "-oL",  # Line-buffered output for real-time streaming
            "acpx",
            "--format", "text",  # Clean text output (top-level option)
            "--approve-all",  # Auto-approve permission requests
            "claude", "exec",
            str(prompt)
        ]
        
        logger.info(f"[ACP-CHAT] Running ACPX for project: {self.project_name}")
        logger.info(f"[ACP-CHAT] Working directory: {self.frontend_src_path}")
        logger.info(f"[ACP-CHAT] User message: {user_message[:100]}...")
        logger.info(f"[ACP-CHAT] Command: acpx claude exec --format text --approve-all <prompt>")
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
    
    async def _preprocess_message(self, user_message: str) -> Optional[str]:
        """
        Preprocess user message with fast LLM.
        
        Returns:
            Direct response if no ACPX needed, None otherwise
        """
        if not USE_PREPROCESSOR:
            return None
        
        try:
            from acp_preprocessor import preprocess_message
            # Pass frontend_src_path for read tool access
            logger.debug(f"[ACP-CHAT] Calling preprocessor with project_path={self.frontend_src_path}")
            result = await preprocess_message(user_message, self.project_name, str(self.frontend_src_path))
            
            logger.info(f"[ACP-CHAT] Preprocessor: intent={result.intent.value}, needs_acpx={result.should_call_acpx}")
            
            # If preprocessor says no ACPX needed, return direct response
            if not result.should_call_acpx and result.direct_response:
                logger.info(f"[ACP-CHAT] Using direct response from preprocessor")
                return result.direct_response
            
            # If we have an enhanced prompt, we'll use it
            if result.enhanced_prompt:
                logger.info(f"[ACP-CHAT] Using enhanced prompt: {result.enhanced_prompt[:100]}...")
                # Store for use in _build_chat_prompt
                self._enhanced_prompt = result.enhanced_prompt
            
            return None
            
        except Exception as e:
            logger.warning(f"[ACP-CHAT] Preprocessor failed: {e}, continuing with ACPX")
            return None
    
    async def run_chat_unified(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
        """
        Unified chat method that chooses best available backend.
        
        Priority:
        1. ClaudeCodeAgent (async, direct Claude CLI) - if available and enabled
        2. ACPX (fallback, synchronous) - if Claude Agent fails or not available
        
        Args:
            user_message: User's chat message
            session_context: Previous conversation context
            
        Returns:
            Dict with status, response, and any error info
        """
        # Try Claude Agent first (if enabled)
        if USE_CLAUDE_AGENT:
            logger.info(f"[ACP-CHAT] Using ClaudeCodeAgent backend (preferred)")
            try:
                result = await self.run_claude_chat(user_message, session_context)
                if result.get("success"):
                    return result
                else:
                    logger.warning(f"[ACP-CHAT] Claude Agent failed, falling back to ACPX: {result.get('error')}")
            except Exception as e:
                logger.warning(f"[ACP-CHAT] Claude Agent exception, falling back to ACPX: {e}")
        
        # Fallback to ACPX (synchronous, but wrapped in async)
        logger.info(f"[ACP-CHAT] Using ACPX backend (fallback)")
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self.run_acpx_chat,
            user_message,
            session_context
        )
        result["backend"] = "acpx"
        return result

    async def run_claude_chat_streaming(self, user_message: str, session_context: str = ""):
        """
        Stream Claude Code Agent response.
        
        Yields text chunks as they arrive from Claude CLI.
        """
        # Check if we have an enhanced prompt from preprocessor
        enhanced = getattr(self, '_enhanced_prompt', None)
        if enhanced:
            prompt = self._build_chat_prompt(enhanced, session_context)
            self._enhanced_prompt = None  # Reset
        else:
            prompt = self._build_chat_prompt(user_message, session_context)
        
        logger.info(f"[ACP-CHAT] === CLAUDE STREAMING MODE ===")
        logger.info(f"[ACP-CHAT] Total prompt: {len(prompt)} chars")
        
        full_response = []
        chunk_queue = []  # Queue for immediate yielding
        
        def on_chunk(text: str):
            """Callback for streaming chunks."""
            full_response.append(text)
            chunk_queue.append(text)
            logger.info(f"[ACP-CHAT] Chunk: {text[:80]}...")
        
        try:
            async with ClaudeCodeAgent(
                str(self.frontend_src_path),
                on_text=on_chunk
            ) as agent:
                response = await agent.query(prompt)
                
                # Yield all collected chunks for SSE streaming
                for chunk in full_response:
                    if chunk.strip():  # Skip empty chunks
                        yield chunk
                
        except Exception as e:
            logger.error(f"[ACP-CHAT] Claude streaming error: {e}")
            yield f"Error: {str(e)}"

    async def run_chat_streaming_unified(self, user_message: str, session_context: str = ""):
        """
        Unified streaming method that chooses best available backend.
        
        Priority:
        1. ClaudeCodeAgent streaming (async) - if available and enabled
        2. ACPX streaming (fallback, sync via executor)
        """
        # Use same logic as run_chat_unified - check USE_CLAUDE_AGENT constant
        if USE_CLAUDE_AGENT:
            logger.info(f"[ACP-CHAT] Using ClaudeCodeAgent streaming backend")
            try:
                async for chunk in self.run_claude_chat_streaming(user_message, session_context):
                    yield chunk
                return
            except Exception as e:
                logger.warning(f"[ACP-CHAT] Claude Agent streaming failed, falling back to ACPX: {e}")
        
        # Fallback to ACPX streaming
        logger.info(f"[ACP-CHAT] Using ACPX streaming backend (fallback)")
        loop = asyncio.get_event_loop()
        stream_gen = self.run_acpx_chat_streaming(user_message, session_context)
        
        # Run sync generator in executor
        def get_chunks():
            return list(stream_gen)
        
        chunks = await loop.run_in_executor(None, get_chunks)
        for chunk in chunks:
            yield chunk

    def run_acpx_chat_streaming(self, user_message: str, session_context: str = ""):
        # Check if we have an enhanced prompt from preprocessor
        enhanced = getattr(self, '_enhanced_prompt', None)
        if enhanced:
            prompt = self._build_chat_prompt(enhanced, session_context)
            self._enhanced_prompt = None  # Reset
        else:
            prompt = self._build_chat_prompt(user_message, session_context)
        
        logger.info(f"[ACP-CHAT] === STREAMING MODE ===")
        logger.info(f"[ACP-CHAT] Total prompt: {len(prompt)} chars, timeout: {ACPX_TIMEOUT}s")

        # Use acpx directly with --format text for clean output
        cmd = [
            "stdbuf", "-oL",
            "acpx",
            "--format", "text",
            "--approve-all",
            "claude", "exec",
            str(prompt)
        ]

        env = os.environ.copy()

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
                env=env
            )

            logger.info(f"[ACP-CHAT] Subprocess PID: {process.pid}")

            raw_output = []
            start_time = time.time()

            # Stateful block tracker — tracks depth across lines
            brace_depth = 0
            bracket_depth = 0
            in_json_block = False

            while True:
                line = process.stdout.readline()

                if time.time() - start_time > ACPX_TIMEOUT:
                    logger.warning(f"[ACP-CHAT] Timeout")
                    process.kill()
                    return

                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        raw_output.append(remaining)
                    break

                line = line.rstrip('\n\r')
                if not line:
                    continue

                raw_output.append(line)
                logger.info(f"[ACP-CHAT] Line: {line[:120]}")  # Log more chars to debug

                stripped = line.strip()
                lower = stripped.lower()

                # ── Detect block entry triggers ──────────────────────────────
                # Covers: "Error handling notification {", "} {", inline JSON starts
                if (
                    'error handling notification' in lower
                    or lower in ('{', '[', '} {', '} [{', '] {')
                    or (lower.endswith('{') and ':' not in lower and len(stripped) <= 6)
                ):
                    in_json_block = True
                    brace_depth += stripped.count('{') - stripped.count('}')
                    bracket_depth += stripped.count('[') - stripped.count(']')
                    continue

                # ── Track depth if already inside a block ────────────────────
                if in_json_block:
                    brace_depth += stripped.count('{') - stripped.count('}')
                    bracket_depth += stripped.count('[') - stripped.count(']')
                    if brace_depth <= 0 and bracket_depth <= 0:
                        in_json_block = False
                        brace_depth = 0
                        bracket_depth = 0
                    continue  # suppress all lines inside block
                # ── Stop at end_turn marker (signals end of response) ──────────
                if 'end_turn' in lower:
                    logger.info(f"[ACP-CHAT] Found end_turn, stopping stream")
                    break
                # ── Standard noise filter for non-block lines ────────────────
                if self._is_inline_noise(line):
                    continue

                # ── Also suppress bare structural punctuation ────────────────
                # Catches orphaned fragments like: "]," "  ]," "  }," etc.
                if stripped in ('}', '{', ']', '[', '},', '],', '} {', '};', '];'):
                    continue

                yield line + "\n"

            logger.info(f"[ACP-CHAT] Completed: {len(raw_output)} lines raw")
            self.kill_orphan_processes()

        except Exception as e:
            logger.error(f"[ACP-CHAT] Stream error: {e}")
            yield f"Error: {str(e)}\n"


async def check_preprocessor(user_message: str, project_name: str, project_path: str = None) -> Optional[str]:
    """
    Check if preprocessor can handle the message without ACPX.
    
    Args:
        user_message: User's chat message
        project_name: Name of the project
        project_path: Optional path to project root for reading context
        
    Returns:
        Direct response if preprocessor can handle it, None if ACPX needed
    """
    if not USE_PREPROCESSOR:
        return None
    
    try:
        from acp_preprocessor import preprocess_message
        result = await preprocess_message(user_message, project_name, project_path)
        
        if not result.should_call_acpx and result.direct_response:
            logger.info(f"[ACP-PRE] Direct response for: {user_message[:50]}...")
            return result.direct_response
        
        return None
        
    except Exception as e:
        logger.warning(f"[ACP-PRE] Preprocessor check failed: {e}")
        return None


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
