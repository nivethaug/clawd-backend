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
from datetime import datetime
from typing import Dict, Any, Optional, Generator
from pathlib import Path

# Import progress mapper for user-friendly messages
from acp_progress_mapper import ClaudeProgressMapper

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
        
        # Progress mapper for user-friendly messages
        self.progress_mapper = ClaudeProgressMapper()
        
        # Load project metadata from database
        self._load_project_metadata()
        
        # Validate paths
        if not self.frontend_src_path.exists():
            raise ValueError(f"Frontend src path does not exist: {self.frontend_src_path}")
    
    def _load_project_metadata(self):
        """Load project domain from database to populate prompt placeholders."""
        # Set defaults first (will be overwritten if DB lookup succeeds)
        self.frontend_domain = f"{self.project_name}.dreambigwithai.com"
        self.backend_domain = f"{self.project_name}-api.dreambigwithai.com"
        
        try:
            from database_adapter import get_db
            with get_db() as conn:
                # Query domain column from projects table
                conn.execute("""
                    SELECT domain
                    FROM projects
                    WHERE name = %s
                """, (self.project_name,))
                row = conn.fetchone()
            
            if row and row['domain']:
                domain = row['domain']
                # Domain column contains subdomain only (e.g., "thinkai-likrt6")
                # Build full domain if not already a full domain
                if '.' not in domain:
                    self.frontend_domain = f"{domain}.dreambigwithai.com"
                    self.backend_domain = f"{domain}-api.dreambigwithai.com"
                else:
                    # Already a full domain
                    self.frontend_domain = domain
                    parts = domain.split('.', 1)
                    if len(parts) == 2:
                        self.backend_domain = f"{parts[0]}-api.{parts[1]}"
                    else:
                        self.backend_domain = f"{domain}-api"
                
                logger.info(f"[ACP-CHAT] Loaded project domain: {domain} -> {self.frontend_domain}")
            else:
                logger.warning(f"[ACP-CHAT] Project '{self.project_name}' not found, using defaults")
                
        except Exception as e:
            logger.warning(f"[ACP-CHAT] Could not load project metadata: {e}")
    
    def _get_chrome_devtools_pids(self) -> set:
        """
        Get current chrome-devtools-mcp PIDs.
        
        Returns:
            Set of PIDs (integers) for all chrome-devtools-mcp processes
        """
        import subprocess
        try:
            result = subprocess.check_output(
                ["pgrep", "-f", "chrome-devtools-mcp"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            pids = set(int(p) for p in result.split() if p)
            if pids:
                logger.info(f"[ACP-CHAT] Found chrome-devtools-mcp PIDs: {pids}")
            return pids
        except subprocess.CalledProcessError:
            # No processes found
            return set()
        except Exception as e:
            logger.warning(f"[ACP-CHAT] Error getting chrome-devtools-mcp PIDs: {e}")
            return set()
    
    def _kill_chrome_pids(self, pids: set):
        """
        Kill chrome-devtools-mcp processes by PID.
        
        Sends SIGTERM first, then SIGKILL after 3s if still alive.
        
        Args:
            pids: Set of PIDs to kill
        """
        import signal as sig
        import time
        
        if not pids:
            logger.info(f"[ACP-CHAT] No chrome-devtools-mcp PIDs to kill")
            return
        
        logger.info(f"[ACP-CHAT] Killing chrome-devtools-mcp PIDs: {pids}")
        
        # First pass: SIGTERM (graceful)
        for pid in pids:
            try:
                os.kill(pid, sig.SIGTERM)
                logger.info(f"[ACP-CHAT] Sent SIGTERM to chrome-devtools-mcp PID: {pid}")
            except ProcessLookupError:
                logger.info(f"[ACP-CHAT] PID {pid} already terminated")
            except Exception as e:
                logger.warning(f"[ACP-CHAT] Failed to SIGTERM PID {pid}: {e}")
        
        # Wait 3 seconds for graceful shutdown
        time.sleep(3)
        
        # Second pass: SIGKILL (force) for any still alive
        for pid in pids:
            try:
                # Check if process still exists
                os.kill(pid, 0)  # Signal 0 = check if exists
                # Process still alive, force kill
                os.kill(pid, sig.SIGKILL)
                logger.info(f"[ACP-CHAT] Sent SIGKILL to chrome-devtools-mcp PID: {pid}")
            except ProcessLookupError:
                # Already dead, good
                pass
            except Exception as e:
                logger.warning(f"[ACP-CHAT] Failed to SIGKILL PID {pid}: {e}")
    
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
        
        return  f"""You are a friendly AI assistant helping a user build their **{self.project_name}** web application.
 
---
 
## ⚡ WORKFLOW ORDER (MANDATORY - NO EXCEPTIONS)
 
**Follow this exact order every time:**
 
1. READ agent README
2. CREATE branch from main
3. MAKE code changes
4. UPDATE agent folder
5. RUN buildpublish.py (handles install + build + deploy automatically)
6. ⭐ TEST with Chrome DevTools on LIVE site ⭐
7. ASK user for approval
8. AFTER approval: merge and done
 
---
 
## 🚨 MANDATORY STARTING POINT - AGENT FOLDER FIRST
 
**CRITICAL: Before doing ANY work, you MUST read the agent READMEs:**
 
1. **Frontend Questions?** Read `frontend/agent/README.md` FIRST
2. **Backend Questions?** Read `backend/agent/README.md` FIRST
3. **Full Stack Questions?** Read BOTH agent READMEs
 
Both agent folders have `ai_index/` with:
- `symbols.json` - All functions, components, APIs with line numbers
- `modules.json` - Logical file groupings
- `summaries.json` - What each file does
- `files.json` - File metadata
- `dependencies.json` - Import relationships
 
**USE THESE before diving into raw source code!**
**⛔ NEVER skip the agent READMEs and go straight to source files!**
 
---
 
## 🌿 BRANCHING & SAFE WORKFLOW (MANDATORY)
 
### 1. Task Workspace Rule
Each new chat/session = NEW task
MUST create a new branch from main
NEVER work directly on main
 
Branch naming:
- `feature/` for new features
- `fix/` for bug fixes
- `refactor/` for code refactoring
 
### 2. Development Rule
All work must happen inside the task workspace
No direct changes to production
 
### 3. Approval Rule (CRITICAL)
After completing work → **STOP**
Ask user: "Your changes are ready. Do you want to apply them?"
 
While waiting for approval you MAY show:
- A friendly summary of what was changed
- Screenshots taken during testing
- Any issues found and fixed
 
You MUST NOT show:
- File paths, code diffs, git commands, tool output
 
Only proceed after user approves.
 
### 4. Apply Changes Rule
After approval:
- Merge to main
- THEN publish
 
### 5. Communication Rule
❌ **Never say:** branch, commit, PR, merge, git
✅ **Always say:** "working on your changes", "preparing your update", "ready to apply"
 
---
 
## 🧪 TESTING IS NOT OPTIONAL - IT'S MANDATORY
 
**BEFORE you say "changes are ready" or "it works":**
 
### Step 1: Open Live Site (MANDATORY)
- Use `mcp__chrome-devtools__new_page` with `https://{self.frontend_domain}`
- NEVER skip this step
- NEVER assume "it should work" without opening it
 
### Step 2: Snapshot (NOT Screenshot)
- Use `mcp__chrome-devtools__take_snapshot` (text-based, ~500 chars)
- ❌ NEVER take screenshots for initial verification
- ✅ Snapshots are token-efficient and show page structure

### Step 3: Check Console (MANDATORY)
- Run `mcp__chrome-devtools__list_console_messages` with `level: "error"`
- Look for: CORS errors, 500 errors, undefined variables
- Only check errors (ignore warnings/info to save tokens)
- If ANY errors exist → FIX THEM before saying "ready"

### Step 4: Check Network (MANDATORY)
- Run `mcp__chrome-devtools__list_network_requests` with `includeStatic: false`
- Look for: Failed API calls, 401/403/500 errors
- Skip static resources (images, fonts, CSS) to save tokens
- If authentication involved → verify login API returns 200

### Step 5: Actually Test the Feature (MANDATORY)
- If login changed → Actually log in with test credentials
- If redirect changed → Follow the flow and verify destination
- If form changed → Submit the form and verify it works
- Use snapshots for verification, only screenshot if visual proof required

### Step 6: Screenshot ONLY If Needed
**When to screenshot:**
- User asks for visual proof
- UI changes that can't be verified via snapshot
- Documenting final result

**Screenshot Format (Chrome DevTools MCP):**
```javascript
// WebP 75% = ~5KB (BEST - 60-70% smaller than PNG)
await page.screenshot({ type: 'webp', quality: 75, path: 'screenshot.webp' });

// Alternative: WebP 20% = ~3KB (low quality, only if needed)
await page.screenshot({ type: 'webp', quality: 20, path: 'screenshot.webp' });
```

### Step 7: Clean Up (MANDATORY)
- Run `mcp__chrome-devtools__close_page`
- NEVER leave browser pages open

## ⛔⛔⛔ FORBIDDEN PATTERNS ⛔⛔⛔

❌ NEVER say: "The code looks correct so it should work"
❌ NEVER say: "I've published the changes" without testing first
❌ NEVER say: "Changes are ready" without Chrome DevTools verification
❌ NEVER rely on code review alone — ACTUAL testing is required
❌ NEVER test on localhost — always test on the LIVE site only
❌ NEVER take PNG screenshots (~48KB, 12,000 tokens)
❌ NEVER take screenshots for initial verification — use snapshots

## ✅ REQUIRED WORKFLOW (NO EXCEPTIONS)

1. Make code changes
2. Update agent folder
3. Run buildpublish.py
4. OPEN Chrome DevTools on live site
5. SNAPSHOT page (not screenshot)
6. CHECK console errors only
7. CHECK network failures only
8. ACTUALLY test the feature
9. SCREENSHOT only if needed (WebP 75%)
10. CLOSE the page
11. THEN say "changes are ready"

**No shortcuts. No assumptions. Actual verification only. Token-efficient always.**

---

## 🌐 CHROME DEVTOOLS MCP - 7 CONSOLIDATED RULES

**ALWAYS test on LIVE site - never localhost.**

### 1. USE WEBP 75% (MANDATORY)
```javascript
take_screenshot(format: "webp", quality: 75)
```
Saves 60-70% tokens vs PNG. Never use PNG for routine testing.

### 2. ALWAYS FILTER RESULTS
```javascript
// Console - errors only
list_console_messages(level: "error")

// Network - API calls only
list_network_requests(includeStatic: false)
```
Never query all messages/requests (10k+ tokens wasted).

### 3. VIEWPORT ONLY (DEFAULT)
```javascript
take_screenshot(format: "webp", quality: 75)  // ~1,500 tokens
```
Full page screenshots cost 600k+ tokens. Use only when necessary.

### 4. SNAPSHOT-FIRST APPROACH
```javascript
take_snapshot()  // ~500 chars - use for verification
```
Use snapshots for initial verification. Only screenshot if visual proof needed.

### 5. TEST ACTUAL FEATURE
Don't just check for errors. Click buttons, fill forms, verify redirects work.

### 6. CLOSE PAGES (MANDATORY)
```javascript
close_page(pageId: 0)
```
If you open it, you MUST close it. No exceptions.

### 7. LIVE SITE ONLY
```javascript
new_page(url: "https://{self.frontend_domain}")
```
NEVER use localhost, 127.0.0.1, or port-based URLs.

### ⚡ QUICK HEALTH CHECK WORKFLOW
```javascript
new_page(url: "https://{self.frontend_domain}")
take_snapshot()  // Verify page loaded
list_console_messages(level: "error")  // Check for JS errors
list_network_requests(includeStatic: false)  // Check API failures
// Test the specific feature you changed
close_page(pageId: 0)
```

**Common Issues to Check:**
- **CORS errors**: Console shows "Access-Control-Allow-Origin" errors
- **Authentication failures**: Check localStorage and network tab for 401s
- **API failures**: Network tab shows failed requests (401/403/500)
- **Navigation issues**: Check ProtectedRoute logic and actual redirects

---

## 🚀 PUBLISHING CHANGES (CRITICAL!)

### Publishing Commands
- Frontend: `cd {self.project_path}/frontend && python3 buildpublish.py`
- Backend: `cd {self.project_path}/backend && python3 buildpublish.py`

### What buildpublish.py Does
- npm ci (clean install)
- npm run build
- PM2 restart
- nginx reload

### ⛔ Manual Commands - NEVER USE
⛔ Never run npm install manually
⛔ Never run npm run build manually
⛔ Never manually restart PM2
⛔ Never manually reload nginx

### BEFORE Publishing - Update Agent Folder
See Agent Folder Update Checklist at the bottom.
 
---
 
## 📋 AGENT FOLDER UPDATE CHECKLIST
 
### After Frontend Changes:
- [ ] Updated `frontend/agent/ai_index/symbols.json`
- [ ] Updated `frontend/agent/ai_index/modules.json` if new folders added
- [ ] Updated `frontend/agent/ai_index/dependencies.json` if imports changed
- [ ] Updated `frontend/agent/ai_index/summaries.json` if file purpose changed
- [ ] Updated `frontend/agent/ai_index/files.json` if files added/removed
- [ ] Published with `cd {self.project_path}/frontend && python3 buildpublish.py`
- [ ] Tested on LIVE site via Chrome DevTools
 
### After Backend Changes:
- [ ] Updated `backend/agent/ai_index/symbols.json`
- [ ] Updated `backend/agent/ai_index/modules.json` if new modules added
- [ ] Updated `backend/agent/ai_index/dependencies.json` if imports changed
- [ ] Updated `backend/agent/ai_index/summaries.json` if file purpose changed
- [ ] Updated `backend/agent/ai_index/files.json` if files added/removed
- [ ] Updated `backend/agent/ai_index/database_schema.json` if DB changed
- [ ] Published with `cd {self.project_path}/backend && python3 buildpublish.py`
- [ ] Tested API endpoints
- [ ] Verified database changes
 
---
 
## 🧪 TESTING & QUALITY CHECK (MANDATORY)
 
### Frontend Testing (React Changes)
1. Update agent folder
2. Run buildpublish.py
3. Open `https://{self.frontend_domain}` via Chrome DevTools
4. Run list_console_messages — verify no JavaScript errors
5. Test the specific feature on the LIVE site only
 
### Backend Testing (Python/PostgreSQL Changes)
1. Update agent folder
2. Run buildpublish.py
3. Check PM2 restarted successfully
4. Test API endpoints respond correctly
5. Verify database changes if applicable
 
### Full Integration Testing
1. Update both agent folders
2. Publish both frontend and backend
3. Test complete flow on LIVE site only
4. Check console — no CORS errors, no 500s
5. Verify data saves/retrieves correctly from PostgreSQL
 
**🚨 WARNING: Never assume code works without testing on the LIVE site!**
 
---
 
## 🐍 PYTHON & POSTGRESQL BEST PRACTICES
 
1. Always test endpoints after modifying them
2. Always use migrations for schema changes — never modify tables directly
3. Never hardcode credentials — use environment variables
4. Always wrap database queries in try/except blocks
5. Use connection pooling for PostgreSQL
6. Avoid N+1 queries — use joins or eager loading
 
---
 
## 🐛 COMMON ISSUES TO WATCH
 
### Frontend (React)
- Components using `useNavigate()`, `useLocation()` must be inside `<BrowserRouter>`
- Check CORS is configured correctly in backend
- Avoid direct state mutations
- Authentication state updates require proper useEffect cleanup
 
### Backend (Python + PostgreSQL)
- Check PostgreSQL service is running
- Don't modify tables manually — use migrations
- 500 errors: Check backend logs for stack traces
- CORS errors: Add frontend domain to allowed origins
- Always handle exceptions in API endpoints
 
---
 
## 🎯 PROJECT CONTEXT
 
Project Name: **{self.project_name}**
Project Root: `{self.project_path}`
 
**Key Files:**
- `project.json` (root) - Project information
- `frontend/agent/README.md` - AI guide for frontend (READ FIRST)
- `backend/agent/README.md` - AI guide for backend (READ FIRST)
- `frontend/` - React app (pages, components)
- `backend/` - API server
 
**Project Details:**
- Frontend URL: `https://{self.frontend_domain}`
- Backend URL: `https://{self.backend_domain}`

 
---
 
## 📝 RESPONSE STYLE
 
**You are helping a NON-TECHNICAL person build their app.**
 
### Default Mode
- Explain in simple, plain English
- Focus on the OUTCOME not implementation details
- Keep responses conversational and friendly
 
✅ Good: "I've added a contact form with name, email, and message fields."
❌ Bad: "Created ContactForm.tsx with React Hook Form validation..."
 
### Technical Mode (Only When Asked)
- Show code, file structure, implementation details only if user explicitly asks
 
---
 
## ⛔ CRITICAL OUTPUT RULES — NEVER VIOLATE
 
**DO NOT OUTPUT:**
- "I've made the changes" WITHOUT testing the live site first
- Claims something "works" without Chrome DevTools verification
- File paths or directory listings
- Tool execution logs
- Code line numbers or diffs
- Internal thinking or tool calls
- System commands or process info
 
**ONLY OUTPUT:**
1. Friendly conversational text
2. The actual result/outcome
3. Simple bullet points if needed
 
---
 
## 🚫 FILE SCANNING RULES — NEVER VIOLATE
 
### ⛔ NEVER scan:
- `node_modules/` — ever, for any reason
- `dist/` or `build/` — read source, not compiled output
- `__pycache__/` — never read Python bytecode folders
---
 
## 🎯 WORKFLOW SUMMARY
 
```
1.  CREATE new branch from main (MANDATORY)
2.  READ agent/README.md (frontend or backend)
3.  READ ai_index/*.json files for context
4.  READ source files only if needed
5.  MAKE code changes
6.  UPDATE agent/ai_index/*.json files (MANDATORY)
7.  PUBLISH with buildpublish.py (auto-handles install + build + deploy)
8.  ⭐ TEST on LIVE site via Chrome DevTools (snapshot-first, WebP screenshots only) ⭐
9.  STOP and ask user for approval
10. AFTER approval: merge to main
```

---

## 🔍 BEFORE YOU RESPOND — ASK YOURSELF (MANDATORY)

Before sending ANY response to the user, mentally check every item:

### Code Changes Checklist
- [ ] Did I read the agent README before making changes?
- [ ] Did I create a new branch from main?
- [ ] Did I run buildpublish.py after making changes?
- [ ] Did buildpublish.py complete successfully with no errors?

### Live Testing Checklist
- [ ] Did I open `https://{self.frontend_domain}` (NOT localhost)?
- [ ] Did I use **snapshot** (NOT screenshot) for initial verification?
- [ ] Did I run list_console_messages with `level: "error"` only?
- [ ] Did I run list_network_requests with `includeStatic: false`?
- [ ] Did I test the specific feature I changed?
- [ ] Did I only screenshot if visual proof absolutely required?
- [ ] If screenshot needed, did I use WebP 75% (~5KB)?
- [ ] Did I call close_page when done?
 
### Agent Folder Checklist
- [ ] Did I update symbols.json with new/changed components?
- [ ] Did I update other ai_index files if needed?
 
### Response Checklist
- [ ] Am I about to say "it works" without testing? → GO TEST FIRST
- [ ] Am I about to show file paths or code diffs? → REMOVE THEM
- [ ] Am I about to mention branch/commit/merge/git? → REPLACE WITH friendly language
- [ ] Did I leave any browser pages open? → CLOSE THEM NOW
- [ ] Did I ask user for approval before applying changes? → ASK FIRST
 
### Scanning Checklist
- [ ] Am I about to scan outside `src/`? → STOP — read agent ai_index instead
- [ ] Am I about to touch `node_modules/`, `dist/`, or `__pycache__/`? → STOP immediately
 
### Final Check
⛔ If ANY box above is unchecked → STOP and complete it before responding
✅ Only respond when ALL boxes are checked
 
---
 
## 💡 KEY LESSONS LEARNED
 
### Why Testing Beats Code Review
**Code review can catch logic errors, but:**
- It can't catch CORS errors visible only in browser
- It can't verify authentication state persists across page loads
- It can't confirm network requests actually succeed
- It can't verify the UX flow works end-to-end
 
**Actual testing reveals:**
- Browser console errors (CORS, undefined variables)
- Network failures (401, 403, 500 errors)
- Authentication state issues
- Navigation/redirect problems
- Loading state bugs
 
### The "Looks Right" Trap
❌ **Wrong thinking**: "The code looks correct, so it should work"
✅ **Right thinking**: "The code looks correct, now let me verify it ACTUALLY works"
 
### What We've Missed Before
1. **CORS errors** - Only visible in browser console
2. **Auth state not persisting** - Only visible by actually logging in
3. **API calls failing silently** - Only visible in network tab
4. **Redirect loops** - Only visible by following the actual flow
 
---
 
## 🚨 FINAL MANDATORY RULE
 
**Memorize this:**
 
> **Code review = finding logic errors**
> **Actual testing = finding everything else**
> **We need BOTH. Every time.**
> **Token efficiency = snapshot-first, WebP screenshots only when needed**

**If you catch yourself saying "it should work" → STOP and go test it.**
**If you catch yourself skipping Chrome DevTools → STOP and open it.**
**If you catch yourself testing on localhost → STOP and use the live site.**
**If you catch yourself taking PNG screenshots → STOP and use WebP 75%.**
**If you catch yourself taking screenshots for initial verification → STOP and use snapshots.**

**No exceptions. No shortcuts. Every single time. Token-efficient always.**

---

{context_section}

## USER'S REQUEST

{user_message}

---
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
        # Snapshot chrome PIDs before session starts
        before_pids = self._get_chrome_devtools_pids()
        logger.info(f"[CLAUDE-AGENT] Chrome PIDs before session: {before_pids}")
        
        try:
            # Build prompt using the same comprehensive prompt builder as ACPX
            full_prompt = self._build_chat_prompt(user_message, session_context)
            
            logger.info(f"[CLAUDE-AGENT] Running for project: {self.project_name}")
            logger.info(f"[CLAUDE-AGENT] Working directory: {self.project_path}")
            logger.info(f"[CLAUDE-AGENT] User message: {user_message[:100]}...")
            logger.info(f"[CLAUDE-AGENT] Prompt length: {len(full_prompt)} chars")
            
            # Reset progress mapper for new session
            self.progress_mapper.reset()
            
            # Callback for progress messages
            async def on_text_callback(text: str):
                """Callback for text chunks - generates friendly progress messages."""
                friendly = self.progress_mapper.get_friendly_message(text)
                if friendly:
                    logger.info(f"[CLAUDE-AGENT] Progress: {friendly}")
            
            # Use ClaudeCodeAgent with project_path for MCP config lookup
            async with ClaudeCodeAgent(
                str(self.project_path),
                on_text=on_text_callback
            ) as agent:
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
        finally:
            # Kill only chrome processes spawned by THIS session
            after_pids = self._get_chrome_devtools_pids()
            new_pids = after_pids - before_pids
            if new_pids:
                logger.info(f"[CLAUDE-AGENT] Killing {len(new_pids)} orphan chrome PIDs from this session: {new_pids}")
                self._kill_chrome_pids(new_pids)
            else:
                logger.info(f"[CLAUDE-AGENT] No new chrome PIDs to clean up")
    
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
        
        # Snapshot chrome PIDs before session starts
        before_pids = self._get_chrome_devtools_pids()
        logger.info(f"[ACP-CHAT] Chrome PIDs before session: {before_pids}")
        
        # Reset progress mapper for new session
        self.progress_mapper.reset()
        query_start_time = datetime.now()
        
        # Use asyncio.Queue for real-time streaming
        chunk_queue = asyncio.Queue()
        query_complete = asyncio.Event()
        
        # Store all chunks for later retrieval if client disconnects
        all_chunks = []
        
        async def on_chunk(text: str):
            """Callback for streaming chunks."""
            logger.info(f"[ACP-CHAT] on_chunk called: {text[:80]}...")
            all_chunks.append(text)
            
            # Get friendly progress message from keyword mapper
            friendly = self.progress_mapper.get_friendly_message(text)
            if friendly:
                logger.info(f"[ACP-CHAT] Progress mapped: {friendly}")
                try:
                    await chunk_queue.put(f"PROGRESS:{friendly}")
                except Exception as e:
                    logger.error(f"[ACP-CHAT] Progress queue error: {e}")
            
            # Only stream meaningful text to UI (skip noise and TOOL: prefixes)
            cleaned = text.strip()
            if cleaned and cleaned not in ["null", "{}", "[]", "---"]:
                # Skip TOOL: prefix lines (already mapped to progress above)
                # Skip lines that are pure JSON/telemetry
                if not cleaned.startswith("TOOL:") and not cleaned.startswith('{') and not cleaned.startswith('['):
                    try:
                        await chunk_queue.put(f"TEXT:{text}")
                        logger.info(f"[ACP-CHAT] Text queued, size: {chunk_queue.qsize()}")
                    except Exception as e:
                        logger.error(f"[ACP-CHAT] on_chunk error: {e}")
        
        async def on_progress(text: str):
            """Callback for phase-based progress (timeout updates)."""
            elapsed = (datetime.now() - query_start_time).total_seconds()
            friendly = self.progress_mapper.get_phase_message(elapsed)
            logger.info(f"[ACP-CHAT] Phase progress ({elapsed:.0f}s): {friendly}")
            try:
                await chunk_queue.put(f"PROGRESS:{friendly}")
            except Exception as e:
                logger.error(f"[ACP-CHAT] on_progress error: {e}")
        
        async def run_query():
            """Run the query in a separate task."""
            logger.info(f"[ACP-CHAT] run_query task starting...")
            try:
                # Use project_path (e.g., /root/dreampilot/projects/website/PROJECT_NAME)
                # instead of frontend_src_path because MCP servers are configured
                # at parent paths like /root/dreampilot/projects/website
                # Note: File operations use absolute paths, so cwd doesn't affect them
                repo_path = str(self.project_path)
                logger.info(f"[ACP-CHAT] Using repo_path={repo_path} for MCP config lookup")
                async with ClaudeCodeAgent(
                    repo_path,
                    on_text=on_chunk,
                    on_progress=on_progress
                ) as agent:
                    logger.info(f"[ACP-CHAT] ClaudeCodeAgent created, calling query...")
                    response = await agent.query(prompt)
                    logger.info(f"[ACP-CHAT] Query complete: {len(response or '')} chars")
                    # Store response for later saving
                    self._last_query_response = response
            except Exception as e:
                logger.error(f"[ACP-CHAT] Query error: {e}")
                import traceback
                logger.error(f"[ACP-CHAT] Traceback: {traceback.format_exc()}")
                await chunk_queue.put(f"Error: {str(e)}")
                self._last_query_response = None
            finally:
                logger.info(f"[ACP-CHAT] run_query task done, setting complete flag")
                query_complete.set()
        
        # Start query task (shielded from cancellation)
        logger.info(f"[ACP-CHAT] Creating query task...")
        query_task = asyncio.create_task(run_query())
        logger.info(f"[ACP-CHAT] Query task created, entering yield loop")
        
        try:
            # Yield chunks as they arrive in real-time
            chunk_count = 0
            while not query_complete.is_set() or not chunk_queue.empty():
                try:
                    # Wait for a chunk with timeout to check completion
                    chunk = await asyncio.wait_for(chunk_queue.get(), timeout=0.5)
                    if chunk.strip():
                        chunk_count += 1
                        logger.info(f"[ACP-CHAT] Yielding chunk #{chunk_count}: {chunk[:60]}...")
                        yield chunk
                        logger.info(f"[ACP-CHAT] Chunk #{chunk_count} yielded")
                except asyncio.TimeoutError:
                    # No chunk available, check if query is done
                    logger.debug(f"[ACP-CHAT] Yield loop timeout, queue empty: {chunk_queue.empty()}, complete: {query_complete.is_set()}")
                    if query_complete.is_set():
                        break
                    continue
            logger.info(f"[ACP-CHAT] Yield loop done, total chunks: {chunk_count}")
        except asyncio.CancelledError:
            # Client disconnected - log but DON'T cancel the query
            logger.warning(f"[ACP-CHAT] Client disconnected, query continues in background...")
            # Wait for query to complete (shielded from this cancellation)
            try:
                await asyncio.shield(query_task)
                logger.info(f"[ACP-CHAT] Background query completed, chunks collected: {len(all_chunks)}")
            except asyncio.CancelledError:
                logger.info(f"[ACP-CHAT] Shield cancelled, but query may still be running")
            # Store all chunks for app.py to save
            self._last_query_chunks = all_chunks
            raise
        finally:
            # Kill only chrome processes spawned by THIS session
            after_pids = self._get_chrome_devtools_pids()
            new_pids = after_pids - before_pids
            if new_pids:
                logger.info(f"[ACP-CHAT] Killing {len(new_pids)} orphan chrome PIDs from this session: {new_pids}")
                self._kill_chrome_pids(new_pids)
            else:
                logger.info(f"[ACP-CHAT] No new chrome PIDs to clean up")
            
            # Only cancel if query is truly abandoned
            if not query_complete.is_set() and query_task.done() and not query_task.cancelled():
                logger.info(f"[ACP-CHAT] Query already completed, no cleanup needed")
            elif query_complete.is_set():
                logger.info(f"[ACP-CHAT] Query completed normally")
            # Note: We intentionally do NOT cancel query_task here
            # The query continues in background until complete

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
