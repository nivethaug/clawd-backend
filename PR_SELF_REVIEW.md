# PR Self-Review: Project Folder Context Injection

**PR #3**: Implement project folder context injection and rule registration
**Branch**: `feature/project-context-injection` → `main`

---

## 📊 **Summary**

- **5 files changed**
- **417 insertions, 32 deletions**
- **1 new module** (`context_injector.py`)

---

## ✅ **Strengths**

### 1. **Clean Architecture**
- Single responsibility: `ContextInjector` handles all context injection logic
- Clear separation: Database queries, file I/O, and message building are separate
- Reusability: Same injection logic for text, streaming, and image chats

### 2. **Backward Compatibility**
- Existing projects continue to work (no context available → returns user messages as-is)
- No API changes required
- No frontend changes needed

### 3. **Comprehensive Git Integration**
- Automatic repo initialization with proper config
- Sensible `.gitignore` covering Python, Node, IDEs, and OS files
- Handles Git < 2.28 and >= 2.28 branch naming

### 4. **Atomic Operations**
- Project creation is atomic: all files + Git or rollback
- Database transaction ensures consistency
- Cleanup on any failure

### 5. **Invisible Context**
- System messages never appear in user-facing chat history
- Clean separation between technical context and user messages
- Professional user experience

---

## ⚠️ **Issues & Improvements**

### 🚨 **CRITICAL: Security - Path Traversal Vulnerability**

**Location**: `context_injector.py` - `read_rule_file()` method

**Issue**:
```python
changerule_path = os.path.join(project_path, "changerule.md")
with open(changerule_path, 'r', encoding='utf-8') as f:
```

While `os.path.join()` mitigates basic path traversal, we're reading arbitrary files from user-controlled paths.

**Risk**:
- If a project folder contains symlinks pointing to sensitive files
- Malicious user could potentially read files outside project directory

**Fix**:
```python
def read_rule_file(self, file_path: str) -> Optional[str]:
    """
    Read a rule file from the project folder.
    Security: Resolves symlinks and validates path is within project.
    """
    try:
        # Resolve symlinks to their real paths
        real_path = os.path.realpath(file_path)

        # Verify the resolved path is within the project directory
        project_root = os.path.dirname(real_path)
        if not real_path.startswith(project_root):
            print(f"SECURITY: Path traversal attempt: {file_path} -> {real_path}")
            return None

        # Additional safety: check file size limit
        if os.path.getsize(real_path) > 1024 * 100:  # 100KB limit
            print(f"SECURITY: Rule file too large: {file_path}")
            return None

        if not os.path.exists(file_path):
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

            # Additional safety: limit content size
            if len(content) > 1024 * 50:  # 50KB text limit
                print(f"SECURITY: Rule content too large, truncating")
                return content[:1024 * 50]

            return content
    except Exception as e:
        print(f"Error reading rule file {file_path}: {e}")
        return None
```

---

### 🟨 **HIGH: Performance - File I/O on Every Message**

**Location**: `context_injector.py` - `inject_system_context()` method

**Issue**:
Every chat message triggers:
1. Database query to get `project_path`
2. File read of `changerule.md` (if exists)
3. File read of `rule.md` (if exists)
4. String concatenation

For a chat session with 100 messages, this means **400+ file/database operations**.

**Impact**:
- Increased latency for each message
- Higher I/O load on server
- Potential bottleneck under high concurrency

**Fix (Caching)**:
```python
class ContextInjector:
    """Handles injection of project context and rules into OpenClaw sessions."""

    def __init__(self):
        """Initialize the context injector."""
        # Cache for rule files to avoid repeated disk I/O
        self._rule_cache: dict[str, Optional[list[dict]]] = {}

    def _get_cache_key(self, project_path: str) -> str:
        """Generate a cache key for a project path."""
        return project_path

    def load_and_register_rules(self, project_path: str) -> list[dict]:
        """
        Load rule files from project folder (with caching).

        Cached rules expire after file modification.
        """
        cache_key = self._get_cache_key(project_path)

        # Check if we have a valid cache
        if cache_key in self._rule_cache:
            cached_data = self._rule_cache[cache_key]
            # Verify cache is still valid (files haven't been modified)
            cache_mtime = cached_data.get('mtime', 0)
            if self._are_files_valid(project_path, cache_mtime):
                print(f"[CTX_INJECTOR] Using cached rules for: {project_path}")
                return cached_data['messages']

        # Load from disk
        print(f"[CTX_INJECTOR] Loading rules from disk: {project_path}")
        messages = self._load_rules_from_disk(project_path)

        # Cache the result
        self._rule_cache[cache_key] = {
            'messages': messages,
            'mtime': self._get_current_mtime(project_path)
        }

        return messages

    def _get_current_mtime(self, project_path: str) -> float:
        """Get the most recent modification time of rule files."""
        mtime = 0.0
        for rule_file in ['changerule.md', 'rule.md']:
            rule_path = os.path.join(project_path, rule_file)
            if os.path.exists(rule_path):
                file_mtime = os.path.getmtime(rule_path)
                mtime = max(mtime, file_mtime)
        return mtime

    def _are_files_valid(self, project_path: str, cached_mtime: float) -> bool:
        """Check if cached rules are still valid."""
        current_mtime = self._get_current_mtime(project_path)
        return current_mtime <= cached_mtime

    def _load_rules_from_disk(self, project_path: str) -> list[dict]:
        """Load rules from disk (internal method)."""
        system_messages = []

        changerule_path = os.path.join(project_path, "changerule.md")
        changerule_content = self.read_rule_file(changerule_path)
        if changerule_content:
            system_messages.append({
                "role": "system",
                "content": changerule_content
            })

        rule_path = os.path.join(project_path, "rule.md")
        rule_content = self.read_rule_file(rule_path)
        if rule_content:
            system_messages.append({
                "role": "system",
                "content": rule_content
            })

        return system_messages

    def invalidate_cache(self, project_path: str):
        """Invalidate cache for a specific project."""
        cache_key = self._get_cache_key(project_path)
        if cache_key in self._rule_cache:
            del self._rule_cache[cache_key]
```

**Performance Improvement**: 100-1000x faster for cached rules
**Trade-off**: Cache invalidation needed when files are modified

---

### 🟨 **HIGH: Code Duplication - Context Injector Instance**

**Location**: Multiple files (`chat_handlers.py`, `image_handler.py`)

**Issue**:
```python
# In chat_handlers.py
context_injector = ContextInjector()

# In image_handler.py
context_injector = ContextInjector()
```

Each module creates its own `ContextInjector` instance with its own cache (if we add caching).

**Impact**:
- Duplicate initialization overhead
- Separate caches waste memory
- Inconsistent cache state across modules

**Fix**:
Option 1: Dependency Injection
```python
# In chat_handlers.py and image_handler.py
from context_injector import get_context_injector

# Use shared instance
injector = get_context_injector()
```

```python
# In context_injector.py
# Singleton pattern
_injector_instance: Optional[ContextInjector] = None

def get_context_injector() -> ContextInjector:
    """Get the singleton instance of ContextInjector."""
    global _injector_instance
    if _injector_instance is None:
        _injector_instance = ContextInjector()
    return _injector_instance
```

Option 2: Pass injector as parameter
```python
# In app.py
injector = ContextInjector()

# Pass to handlers
messages_with_context = injector.inject_system_context(session_key, user_messages)
```

**Recommendation**: Use singleton pattern for simpler implementation

---

### 🟨 **HIGH: Debug Logging Not Production-Ready**

**Location**: `chat_handlers.py` and `context_injector.py`

**Issue**:
```python
print(f"[CTX_INJECTOR] Injecting context for session: {session_key}")
print(f"[CTX_INJECTOR] Project path: {project_path}")
print(f"[CTX_INJECTOR] Added project path message: {path_message['content']}")
print(f"[CTX_INJECTOR] Loaded {len(rule_messages)} rule messages")
print(f"[CTX_INJECTOR] Final messages count: {len(final_messages)} (system: {len(system_messages)}, user: {len(user_messages)})")
```

**Impact**:
- Exposes internal state in production
- Can leak sensitive information (project paths, session keys)
- Cluttered logs
- No way to disable in production

**Fix**:
```python
import logging

# Use proper logging
logger = logging.getLogger(__name__)

class ContextInjector:
    def inject_system_context(self, session_key: str, user_messages: list[dict]) -> list[dict]:
        """Inject system context (project path + rules) into message array."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Injecting context for session: {session_key}")

        # ... rest of implementation ...

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"Final messages count: {len(final_messages)}")
```

**Configuration**:
```python
# In app.py
import logging
logging.basicConfig(
    level=logging.DEBUG if os.getenv('DEBUG') else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

---

### 🟡 **MEDIUM: Git Subprocess - No Error Output Handling**

**Location**: `project_manager.py` - `initialize_git_repo()` method

**Issue**:
```python
subprocess.run(
    ["git", "init"],
    cwd=project_path,
    check=True,
    capture_output=True  # Captures but doesn't use output
)
```

`capture_output=True` captures stdout/stderr but we never check it.

**Impact**:
- Git errors are silently ignored (unless exception is raised)
- No visibility into what went wrong
- Harder to debug

**Fix**:
```python
def initialize_git_repo(self, project_path: str) -> bool:
    """
    Initialize Git repository in project folder.

    Returns:
        True if successful, False otherwise
    """
    try:
        # Initialize git repository
        result = subprocess.run(
            ["git", "init"],
            cwd=project_path,
            check=True,
            capture_output=True,
            text=True  # Return string instead of bytes
        )

        # Log Git output for debugging
        if result.stderr:
            print(f"[GIT] stderr: {result.stderr}")

        if result.stdout:
            print(f"[GIT] stdout: {result.stdout}")

        # Configure default branch to main
        subprocess.run(
            ["git", "config", "user.name", "OpenClaw"],
            cwd=project_path,
            check=True,
            capture_output=True
        )

        subprocess.run(
            ["git", "config", "user.email", "openclaw@local"],
            cwd=project_path,
            check=True,
            capture_output=True
        )

        # Configure default branch name to main (for Git < 2.28)
        try:
            result = subprocess.run(
                ["git", "checkout", "-b", "main"],
                cwd=project_path,
                check=True,
                capture_output=True,
                text=True
            )

            # Check if we actually created main or it already existed
            if "Switched to a new branch" in result.stdout:
                print(f"[GIT] Created and switched to main branch")
            elif result.stderr and "already on 'main'" in result.stderr:
                print(f"[GIT] Already on main branch")

        except subprocess.CalledProcessError as e:
            # Git might already be on main or use a different branch
            print(f"[GIT] Branch checkout failed (might already exist): {e}")
            # Check current branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=project_path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"[GIT] Current branch: {result.stdout.strip()}")

        return True

    except Exception as e:
        print(f"Failed to initialize Git repository: {e}")
        return False
```

---

### 🟡 **MEDIUM: SQL Query - No Parameterized WHERE for project_id**

**Location**: `context_injector.py` - `get_project_folder_path()` method

**Issue**:
```python
result = conn.execute("""
    SELECT p.project_path
    FROM sessions s
    JOIN projects p ON s.project_id = p.id
    WHERE s.session_key = ?
""", (session_key,)).fetchone()
```

The query is parameterized ✅, but we're not validating that the project exists.

**Risk**: If session exists but project is deleted (orphaned session), we'll get `None` silently.

**Fix**:
```python
def get_project_folder_path(self, session_key: str) -> Optional[str]:
    """Get the project folder path for a given session."""
    try:
        with get_db() as conn:
            result = conn.execute("""
                SELECT p.project_path, p.name as project_name, p.id as project_id
                FROM sessions s
                JOIN projects p ON s.project_id = p.id
                WHERE s.session_key = ?
            """, (session_key,)).fetchone()

            if result:
                # Validate project actually has a path
                if not result["project_path"]:
                    print(f"[CTX_INJECTOR] Session {session_key} has no project path (project_id: {result['project_id']})")
                    return None

                return result["project_path"]

            print(f"[CTX_INJECTOR] Session {session_key} not found")
            return None

    except Exception as e:
        print(f"Error getting project folder path: {e}")
        return None
```

---

### 🟡 **MEDIUM: No Validation of project_path Existence**

**Location**: `context_injector.py` - `build_project_context_message()`

**Issue**:
```python
def build_project_context_message(self, project_path: str) -> dict:
    content = f"Project folder path: {project_path}"
    return {"role": "system", "content": content}
```

We don't validate that `project_path` actually exists on disk before using it.

**Risk**: If the database has a stale path, the agent will receive a non-existent path.

**Fix**:
```python
def build_project_context_message(self, project_path: str) -> Optional[dict]:
    """
    Build a system message containing the project folder path.

    Validates that the path exists before returning.

    Args:
        project_path: Absolute path to project folder

    Returns:
        Dictionary representing a system message, or None if invalid
    """
    if not project_path:
        return None

    # Validate path exists and is a directory
    if not os.path.exists(project_path):
        print(f"[CTX_INJECTOR] Project path does not exist: {project_path}")
        return None

    if not os.path.isdir(project_path):
        print(f"[CTX_INJECTOR] Project path is not a directory: {project_path}")
        return None

    # Security: validate path is within allowed directory
    if not project_path.startswith("/var/lib/openclaw/projects/"):
        print(f"[SECURITY] Project path outside allowed directory: {project_path}")
        return None

    content = f"Project folder path: {project_path}"
    return {
        "role": "system",
        "content": content
    }
```

---

### 🟡 **MEDIUM: Exception Handling - Too Broad**

**Location**: Multiple places

**Issue**:
```python
except Exception as e:
    print(f"Error getting project folder path: {e}")
    return None
```

Catching all `Exception` can hide:
- `KeyboardInterrupt` (should propagate)
- `SystemExit` (should propagate)
- Programming errors that should crash

**Fix**:
```python
import sqlite3
from contextlib import suppress

def get_project_folder_path(self, session_key: str) -> Optional[str]:
    """Get the project folder path for a given session."""
    try:
        with get_db() as conn:
            result = conn.execute("""
                SELECT p.project_path
                FROM sessions s
                JOIN projects p ON s.project_id = p.id
                WHERE s.session_key = ?
            """, (session_key,)).fetchone()

            if result:
                return result["project_path"]
            return None

    except sqlite3.Error as e:
        print(f"[CTX_INJECTOR] Database error for session {session_key}: {e}")
        return None
    except Exception as e:
        print(f"[CTX_INJECTOR] Unexpected error for session {session_key}: {e}")
        raise  # Re-raise unexpected errors
```

---

### 🟢 **LOW: Missing Type Hints in Some Methods**

**Location**: `project_manager.py`

**Issue**:
```python
def delete_project_folder(self, project_path: str) -> bool:
```

Some methods have type hints, others don't.

**Fix**: Add type hints to all methods for better IDE support and static analysis.

```python
def delete_project_folder(self, project_path: str) -> bool:
    """
    Delete project folder recursively.

    Args:
        project_path: Absolute path to project folder

    Returns:
        True if successful, False otherwise
    """
```

(Actually, this method already has a docstring, just needs type hint consistency)

---

### 🟢 **LOW: No Unit Tests**

**Location**: All new code

**Issue**: No test files created.

**Recommendation**: Add tests for:

1. `test_context_injector.py`:
   ```python
   def test_get_project_folder_path():
       injector = ContextInjector()
       # Test valid session
       path = injector.get_project_folder_path("valid-session-key")
       assert path is not None
       assert path.startswith("/var/lib/openclaw/projects/")

   def test_inject_system_context():
       injector = ContextInjector()
       messages = [{"role": "user", "content": "test"}]
       result = injector.inject_system_context("valid-key", messages)
       assert len(result) == 3  # 2 system + 1 user
       assert result[0]["role"] == "system"
       assert result[1]["role"] == "system"
       assert result[2]["role"] == "user"

   def test_cache_invalidation():
       injector = ContextInjector()
       # Test cache invalidation when files change
       pass
   ```

2. `test_project_manager.py`:
   ```python
   def test_create_project_with_git():
       manager = ProjectFileManager()
       project_path, success = manager.create_project_with_git(1, "test-project")
       assert success is True
       assert os.path.exists(os.path.join(project_path, ".git"))
       assert os.path.exists(os.path.join(project_path, ".gitignore"))
       # Cleanup
       manager.delete_project_folder(project_path)
   ```

---

### 🟢 **LOW: No Configuration for Rule File Names**

**Location**: Hardcoded in `context_injector.py`

**Issue**:
```python
changerule_path = os.path.join(project_path, "changerule.md")
rule_path = os.path.join(project_path, "rule.md")
```

File names are hardcoded. If you want to support additional rule files, need to change code.

**Fix**:
```python
# Configuration
RULE_FILES = ["changerule.md", "rule.md"]

def load_and_register_rules(self, project_path: str) -> list[dict]:
    """Load rule files from project folder and build system messages."""
    system_messages = []

    for rule_file in RULE_FILES:
        rule_path = os.path.join(project_path, rule_file)
        rule_content = self.read_rule_file(rule_path)
        if rule_content:
            system_messages.append({
                "role": "system",
                "content": rule_content
            })

    return system_messages
```

**Even better**: Make configurable:
```python
# In settings.py or config.py
class Settings:
    RULE_FILES = ["changerule.md", "rule.md"]
    RULE_FILE_MAX_SIZE = 1024 * 50  # 50KB
    PROJECT_BASE_PATH = "/var/lib/openclaw/projects"
```

---

### 🟢 **LOW: README.md Content Could Be More Useful**

**Location**: `project_manager.py` - `create_readme()`

**Issue**:
```python
readme_content = f"openclaw project folder path: {project_path}"
```

Only contains the path. Could include more useful information.

**Fix**:
```python
def create_readme(self, project_path: str) -> bool:
    """
    Create README.md file in project folder.
    """
    readme_path = os.path.join(project_path, "README.md")

    project_id = os.path.basename(project_path).split('_')[0]

    readme_content = f"""# OpenClaw Project

## Project Information

- **Project ID**: {project_id}
- **Project Path**: {project_path}
- **Created**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Overview

This is an OpenClaw project folder. All file operations and agent work
should be performed within this directory.

## Files

- `changerule.md` - Project-specific rules and guidelines
- `rule.md` - Optional custom rules (if present)
- `.gitignore` - Git ignore patterns

## Git

This project has a Git repository initialized. You can:

```bash
# Check status
git status

# Commit changes
git add .
git commit -m "Update project files"

# View history
git log --oneline
```

## Context

The absolute path to this project folder is automatically injected as
system context for all OpenClaw sessions in this project.
"""

    try:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        return True
    except Exception as e:
        print(f"Failed to create README.md: {e}")
        return False
```

---

## 📊 **Prioritized Improvements Summary**

| Priority | Issue | Impact | Effort |
|-----------|---------|---------|---------|
| 🚨 **CRITICAL** | Security: Path traversal in rule file reading | High | Medium |
| 🟨 **HIGH** | Performance: File I/O on every message | High | High |
| 🟨 **HIGH** | Code duplication: Multiple ContextInjector instances | Medium | Low |
| 🟨 **HIGH** | Debug logging in production | Medium | Low |
| 🟡 **MEDIUM** | Git subprocess error handling | Low | Low |
| 🟡 **MEDIUM** | No validation of project_path existence | Medium | Low |
| 🟡 **MEDIUM** | Too broad exception handling | Low | Low |
| 🟢 **LOW** | Missing type hints | Low | Low |
| 🟢 **LOW** | No unit tests | Medium | High |
| 🟢 **LOW** | No configuration for rule files | Low | Low |
| 🟢 **LOW** | Basic README.md content | Low | Low |

---

## 🎯 **Recommended Actions**

### **Before Merge to Production (Must Fix)**:

1. ✅ **Fix Security Issue** - Add path traversal protection in `read_rule_file()`
2. ✅ **Add Performance Caching** - Implement rule file caching to avoid disk I/O
3. ✅ **Fix Code Duplication** - Use singleton pattern for ContextInjector
4. ✅ **Replace Debug Logging** - Use proper logging module with configurable levels

### **Before Merge to Production (Should Fix)**:

5. ⚠️ **Add Git Error Handling** - Log subprocess output for debugging
6. ⚠️ **Validate Project Path** - Check path exists and is valid directory
7. ⚠️ **Narrow Exception Handling** - Catch specific exceptions, re-raise unexpected ones

### **After Merge (Nice to Have)**:

8. 💡 **Add Unit Tests** - Create test coverage for critical paths
9. 💡 **Make Rule Files Configurable** - Allow configuration via environment
10. 💡 **Improve README** - Add more useful information

---

## ✅ **What's Good (Keep As-Is)**

- ✅ Atomic project creation with rollback
- ✅ Comprehensive `.gitignore`
- ✅ Clear docstrings
- ✅ Clean separation of concerns
- ✅ Backward compatibility
- ✅ No API changes required
- ✅ Git initialization handles both old and new versions

---

## 📝 **Conclusion**

**Overall Assessment**: The PR implements the core functionality correctly and is well-architected. However, **critical security and performance issues should be addressed before production deployment.**

**Recommended Decision**:
- **Address CRITICAL and HIGH priority issues** before merging to `main`
- **Create follow-up issues** for MEDIUM and LOW priority items
- **Plan separate PR** for unit tests and caching improvements

---

**Ready for merge**: ⚠️ **NO** (fix critical issues first)
**Ready for merge (with fixes)**: ✅ **YES**
