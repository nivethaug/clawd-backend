# AI Chat System Architecture

## System Design

The AI Chat System follows a modular, service-oriented architecture with clear separation of concerns.

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Application                     │
│                      (app.py)                                │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
        ▼              ▼              ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐
   │AI Chat  │   │Selection │   │ Confirm  │
   │Endpoint │   │Endpoint  │   │Endpoint  │
   └────┬────┘   └────┬─────┘   └────┬─────┘
        │              │              │
        └──────────────┴──────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
        ▼                             ▼
┌────────────────┐          ┌─────────────────┐
│  GLM Client    │          │ Session Manager │
│ (LLM Interface)│          │ (PostgreSQL)    │
└────────┬───────┘          └─────────────────┘
         │
         │ Tool Calls
         ▼
┌────────────────┐
│ Tool Registry  │
│ (Validation)   │
└────────┬───────┘
         │
         ▼
┌────────────────┐          ┌─────────────────┐
│ Tool Executor  │◄─────────┤Project Resolver │
│ (Direct Calls) │          │(Fuzzy Matching) │
└────────┬───────┘          └─────────────────┘
         │
         │ Python Functions
         ▼
┌─────────────────────────────────────────┐
│        Core Services Layer              │
├─────────────────────────────────────────┤
│ • apps_service (PM2 Control)            │
│ • database_postgres (Project Queries)   │
│ • subprocess (Log Retrieval)            │
└─────────────────────────────────────────┘
```

## Component Details

### API Layer (`api/`)

**ai_chat.py** (~240 lines)
- Main chat endpoint
- Orchestrates entire flow
- Integrates all services
- Returns formatted responses

**ai_selection.py** (~100 lines)
- Handles project selection
- Updates tool arguments
- Executes resolved tools

**ai_confirm.py** (~180 lines)
- Manages confirmation flow
- Retrieves pending intents
- Executes confirmed operations

### Service Layer (`services/ai/`)

**glm_client.py** (~140 lines)
```python
class GLMClient:
    - chat_with_tools(messages, tools)
    - parse_tool_calls(response)
    - _make_request_with_retry()
```

Responsibilities:
- HTTP communication with GLM API
- Tool calling protocol implementation
- Automatic retry with timeout handling
- Response parsing and validation

**tool_registry.py** (~240 lines)
```python
# Tool Categories
TOOLS_AUTO = [...]        # 6 tools
TOOLS_CONFIRM = [...]     # 3 tools
TOOLS_DISABLED = [...]    # 1 tool

# Validation Functions
is_safe_tool(name)
requires_confirmation(name)
is_disabled(name)
validate_tool_args(name, args)
```

Responsibilities:
- Define tool schemas (JSON Schema)
- Categorize tools by safety level
- Validate tool arguments
- Provide tool descriptions for LLM

**tool_executor.py** (~230 lines)
```python
class ToolExecutor:
    - execute(tool_name, args)
    - _execute_start_project(domain)
    - _execute_stop_project(domain)
    - _execute_restart_project(domain)
    - _execute_list_projects()
    - _execute_project_status(domain)
    - _execute_get_logs(domain, lines, filter)
```

Responsibilities:
- Execute tools via direct Python calls
- Integrate with PM2 (apps_service)
- Query PostgreSQL database
- Retrieve and filter logs
- Return structured results

**project_resolver.py** (~170 lines)
```python
class ProjectResolver:
    - resolve(text, projects, active_id)
    - _fuzzy_match(text, projects)
```

Responsibilities:
- Parse project references from text
- Fuzzy matching with 0.6 cutoff
- Priority resolution logic
- Return selection options

### Utility Layer (`utils/`)

**ai_session_manager.py** (~150 lines)
```python
class AISessionManager:
    - get_or_create_session(session_key)
    - set_active_project(session_key, project_id)
    - get_active_project(session_key)
    - set_pending_intent(session_key, intent)
    - get_pending_intent(session_key)
    - clear_pending_intent(session_key)
```

Responsibilities:
- Manage session persistence
- Track active project
- Store pending intents
- Update session timestamps

**ai_response_formatter.py** (~90 lines)
```python
# Response Formatters
text_response(text)
execution_response(text, progress)
selection_response(text, options, intent)
confirmation_response(text, intent)
input_required_response(text)
error_response(message, details)
```

Responsibilities:
- Standardize response format
- Ensure consistent structure
- Type-safe response building

## Data Flow

### 1. Chat Flow

```
User Message
    │
    ▼
Load Session (AISessionManager)
    │
    ▼
Load Projects (database_postgres)
    │
    ▼
Build Messages for GLM
    │
    ▼
Call GLM API (GLMClient)
    │
    ├─► Text Response → Return text_response
    │
    └─► Tool Call
         │
         ▼
       Validate Tool (ToolRegistry)
         │
         ├─► Disabled → Return error_response
         │
         └─► Valid
              │
              ▼
            Resolve Project (ProjectResolver)
              │
              ├─► No Match → Return error_response
              │
              ├─► Single Match → Execute
              │
              └─► Multiple Matches → Return selection_response
```

### 2. Selection Flow

```
User Selection
    │
    ▼
Update Intent Args
    │
    ▼
Execute Tool (ToolExecutor)
    │
    ▼
Return execution_response
```

### 3. Confirmation Flow

```
User Confirmation
    │
    ▼
Retrieve Pending Intent (AISessionManager)
    │
    ├─► None → Return error_response
    │
    └─► Found
         │
         ├─► Confirmed → Execute → Clear Intent → Return execution_response
         │
         └─► Cancelled → Clear Intent → Return text_response
```

## Database Design

### ai_sessions Table

```sql
CREATE TABLE ai_sessions (
    id SERIAL PRIMARY KEY,
    session_key TEXT UNIQUE NOT NULL,
    active_project_id TEXT,
    pending_intent JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Note:** The `active_project_id` field stores the project domain string (e.g., "myapp-abc123") rather than the numeric database ID. This ensures consistent project identification across the system.

**Indexes:**
- `idx_ai_sessions_session_key` on `session_key` (fast lookups)
- `idx_ai_sessions_active_project_id` on `active_project_id` (project queries)

**JSONB Schema (pending_intent):**
```json
{
  "tool": "string",
  "args": {
    "arg1": "value1",
    "arg2": "value2"
  }
}
```

## Integration Points

### External APIs

**GLM API** (api.z.ai)
- Endpoint: `/api/coding/paas/v4/chat/completions`
- Auth: Bearer token
- Model: GLM-4.5-Air
- Features: Tool calling, streaming

### Internal Services

**apps_service.py**
- `pm2_action(domain, action)` - PM2 control
- `get_pm2_processes()` - List processes

**database_postgres.py**
- `get_db()` - Connection context manager
- Projects table queries

**subprocess**
- `pm2 logs` command execution
- Log filtering via grep

## Error Handling Strategy

### 1. API Errors
```python
try:
    # Operation
except HTTPException:
    raise  # Re-raise HTTP exceptions
except Exception as e:
    logger.error(f"Operation failed: {e}")
    return error_response(str(e))
```

### 2. Tool Execution Errors
```python
result = await executor.execute(tool_name, args)
if result["status"] == "error":
    return error_response(result["message"])
```

### 3. GLM API Errors
- Retry logic (1 retry after timeout)
- Fallback to error message
- Logging for debugging

## Performance Considerations

### 1. Database Connections
- Use connection pooling (built into psycopg2)
- Context managers ensure cleanup
- Keep queries simple

### 2. GLM API Calls
- 30s default timeout
- 60s retry timeout
- Async HTTP client (httpx)

### 3. Session Management
- Singleton pattern for managers
- Minimal session data
- Update timestamps only on changes

## Security Considerations

### 1. Tool Validation
- All tools must be in registry
- Disabled tools blocked
- Arguments validated before execution

### 2. Project Access
- Projects filtered by user_id (future)
- No cross-project operations
- Active project tracking

### 3. Confirmation Flow
- Dangerous operations require confirmation
- Intent stored server-side
- Cannot bypass confirmation

## Scalability

### Horizontal Scaling
- Stateless API endpoints
- Session data in PostgreSQL
- No in-memory state

### Vertical Scaling
- Async operations (httpx)
- Database connection pooling
- Efficient queries with indexes

## Monitoring

### Logging
```python
logger.info(f"[AI-CHAT] Session {session_id}: {message}")
logger.warning(f"[AI-EXECUTOR] Tool validation failed: {tool_name}")
logger.error(f"[AI-CHAT] Error: {e}", exc_info=True)
```

### Metrics (Future)
- Request count per endpoint
- Tool execution frequency
- GLM API latency
- Error rates by type

## Testing Strategy

### Unit Tests
- Tool registry validation
- Project resolver matching
- Response formatter output

### Integration Tests
- Full chat flow
- Selection flow
- Confirmation flow

### End-to-End Tests
- Real GLM API calls
- PM2 operations
- Database persistence

## Future Architecture

### 1. WebSocket Support
```
WebSocket Connection
    │
    ▼
Real-time Updates
    │
    ├─► Progress Messages
    ├─► Log Streaming
    └─► Status Changes
```

### 2. Plugin System
```
Tool Plugin Interface
    │
    ├─► register_tools()
    ├─► execute_tool()
    └─► validate_args()
```

### 3. Multi-LLM Support
```
LLM Abstraction Layer
    │
    ├─► GLM Adapter
    ├─► Claude Adapter
    └─► GPT Adapter
```

## Related Documentation

- [AI Chat Usage Guide](./ai_chat.md)
- [Project Management](./project_creation.md)
- [Database Schema](../projects_schema.sql)
