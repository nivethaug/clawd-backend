# Claude Code Agent Migration Guide

## Overview

**Current:** ACPX (ACP wrapper around Claude CLI)
**Proposed:** ClaudeCodeAgent (Direct Claude CLI)

---

## Current Approach: ACPX

### How it's Called (acp_chat_handler.py)

```python
# Build command
cmd = [
    "stdbuf", "-oL",  # Line-buffered
    "acpx",
    "--format", "text",
    "--approve-all",
    "claude", "exec",
    str(prompt)
]

# Run as subprocess
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
    cwd=str(self.frontend_src_path),
    env=env
)
```

### Pros
✅ Auto-approval of file operations
✅ Text format output
✅ Real-time streaming

### Cons
❌ Extra ACP layer adds complexity
❌ Requires `acpx` CLI installation
❌ Subprocess management overhead
❌ Synchronous blocking calls

---

## Proposed Approach: ClaudeCodeAgent

### How to Call

```python
from claude_code_agent import ClaudeCodeAgent

# Context manager pattern
async with ClaudeCodeAgent(str(self.frontend_src_path)) as agent:
    response = await agent.query(user_message)
    return response
```

### With Streaming

```python
def on_chunk(text: str):
    print(text, end="", flush=True)

async with ClaudeCodeAgent(
    str(self.frontend_src_path),
    on_text=on_chunk
) as agent:
    response = await agent.query(user_message)
```

### With Context

```python
async with ClaudeCodeAgent(str(self.frontend_src_path)) as agent:
    # First query
    await agent.query("Analyze the project structure")
    
    # Second query (maintains context)
    response = await agent.query("Now add a contact form")
```

### Pros
✅ Direct Claude CLI (no ACP wrapper)
✅ Async/await pattern (non-blocking)
✅ Simpler code
✅ No external dependencies (just `claude` CLI)
✅ Context management built-in
✅ Streaming support

### Cons
❌ Requires async refactoring
❌ Different API than current ACPX calls

---

## Migration Steps

### 1. Import ClaudeCodeAgent

```python
from claude_code_agent import ClaudeCodeAgent
```

### 2. Replace `run_acpx_chat()` Method

**Before (ACPX):**
```python
def run_acpx_chat(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
    cmd = ["stdbuf", "-oL", "acpx", "--format", "text", "--approve-all", "claude", "exec", prompt]
    process = subprocess.Popen(cmd, ...)
    # ... read output ...
    return {"status": "success", "response": text}
```

**After (ClaudeCodeAgent):**
```python
async def run_claude_chat(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
    async with ClaudeCodeAgent(str(self.frontend_src_path)) as agent:
        # Build full prompt with context
        full_prompt = f"{session_context}\n\nUser: {user_message}" if session_context else user_message
        
        response = await agent.query(full_prompt)
        
        return {
            "status": "success",
            "success": True,
            "response": response
        }
```

### 3. Update Callers to Async

**Before:**
```python
result = handler.run_acpx_chat(user_message, context)
```

**After:**
```python
result = await handler.run_claude_chat(user_message, context)
```

---

## Implementation Example

### Modified acp_chat_handler.py

```python
from claude_code_agent import ClaudeCodeAgent

class ACPChatHandler:
    def __init__(self, project_path: str, project_name: str):
        # ... existing init ...
        self.claude_agent = None  # Will be created on demand
    
    async def run_claude_chat(self, user_message: str, session_context: str = "") -> Dict[str, Any]:
        """
        Run Claude Code Agent and return response.
        Replaces ACPX with direct Claude CLI.
        """
        try:
            # Build prompt with context
            full_prompt = user_message
            if session_context:
                full_prompt = f"Previous conversation:\n{session_context}\n\nCurrent request: {user_message}"
            
            logger.info(f"[CLAUDE-AGENT] Running for project: {self.project_name}")
            logger.info(f"[CLAUDE-AGENT] Working directory: {self.frontend_src_path}")
            logger.info(f"[CLAUDE-AGENT] User message: {user_message[:100]}...")
            
            # Use ClaudeCodeAgent
            async with ClaudeCodeAgent(str(self.frontend_src_path)) as agent:
                response = await agent.query(full_prompt)
                
                logger.info(f"[CLAUDE-AGENT] Response received ({len(response)} chars)")
                
                return {
                    "status": "success",
                    "success": True,
                    "response": response,
                    "error": None
                }
        
        except Exception as e:
            logger.error(f"[CLAUDE-AGENT] Error: {e}")
            return {
                "status": "error",
                "success": False,
                "response": f"Error: {str(e)}",
                "error": str(e)
            }
```

---

## Comparison Table

| Feature | ACPX | ClaudeCodeAgent |
|---------|------|-----------------|
| **Call Pattern** | Subprocess.Popen | async with agent |
| **Async Support** | ❌ No | ✅ Yes |
| **Dependencies** | acpx CLI | claude CLI |
| **Code Complexity** | High (200+ lines) | Low (20 lines) |
| **Streaming** | Manual parsing | Built-in callback |
| **Context Management** | Manual | Automatic |
| **Error Handling** | Complex | Simple try/except |
| **Performance** | Blocking | Non-blocking |

---

## Testing

### Test Script

```python
import asyncio
from claude_code_agent import ClaudeCodeAgent

async def test_direct_agent():
    project_path = "/root/dreampilot/projects/website/992_naturescape_20260321_065048/frontend/src"
    
    async with ClaudeCodeAgent(project_path) as agent:
        response = await agent.query("What framework is this project using?")
        print(response)

asyncio.run(test_direct_agent())
```

### Run Test

```bash
python test_real_project.py --quick
```

---

## Benefits of Migration

1. **Simpler Code** - 90% reduction in subprocess management code
2. **Better Performance** - Async non-blocking calls
3. **Fewer Dependencies** - No need for `acpx` installation
4. **Better Error Handling** - Python exceptions instead of subprocess exit codes
5. **Easier Testing** - Async test patterns
6. **Maintainability** - Cleaner API, less code to debug

---

## Next Steps

1. ✅ ClaudeCodeAgent already exists and tested
2. ⏳ Add `run_claude_chat()` method to ACPChatHandler
3. ⏳ Update app.py to call async version
4. ⏳ Test with real projects
5. ⏳ Deploy to production

---

## Questions?

- Should we keep ACPX as fallback?
- How to handle streaming in Flask/SSE?
- Need to update preprocessor integration?
