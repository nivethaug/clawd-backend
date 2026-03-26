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

**ai_selection.py** (~150 lines)
- Handles project selection
- Updates tool arguments
- Executes resolved tools
- LLM summarization for natural language responses

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

## Two-Step LLM Flow

### Overview

The system uses a two-step LLM interaction pattern for tool execution:

1. **Step 1: Tool Execution** - LLM decides to call a tool → Backend executes it
2. **Step 2: Summarization** - Backend sends tool result back to LLM → LLM generates natural language response

### Why Two Steps?

**Problem:** Raw tool outputs are JSON objects that aren't user-friendly
```json
{
  "status": "success",
  "domain": "thinkai-likrt6",
  "pm2_process": "thinkai-likrt6",
  "uptime": 3600
}
```

**Solution:** LLM converts to natural language
```
"Your ThinkAI project is running smoothly and has been up for 1 hour."
```

### Implementation

**In `api/ai_chat.py` (lines 543-590):**
```python
# After tool execution
messages.append({
    "role": "assistant",
    "content": None,
    "tool_calls": [{ ... }]  # Original tool call
})

messages.append({
    "role": "tool",
    "tool_call_id": "call_1",
    "name": tool_name,
    "content": json.dumps(result, cls=DateTimeEncoder)  # Tool result
})

# Second LLM call
final_response = await glm_client.chat_with_tools(
    messages=messages,
    tools=tools,
    tool_choice="none",  # Force text response, no more tools
    temperature=0.3,
    max_tokens=500
)

final_text = glm_client.get_text_response(final_response)
```

**In `api/ai_selection.py` (lines 89-129):**
- Same pattern for selection responses
- Ensures consistent UX across all flows

### Benefits

1. **User-Friendly Responses** - Natural language instead of JSON
2. **Contextual Understanding** - LLM can explain what happened
3. **Error Handling** - Friendly error messages
4. **Consistency** - All responses follow same pattern

### Response Type Determination

After LLM summarization, the system determines the response type:

```python
action_tools = ["start_project", "stop_project", "restart_project", "delete_project"]

if tool_name in action_tools:
    # Action tools: return execution response with progress
    return execution_response(progress=[result], text=final_text)
else:
    # Info/context tools: return plain text
    return text_response(final_text)
```

### Selection Response Bypass

**Important:** Selection responses bypass LLM summarization to preserve structure:

```python
# In api/ai_chat.py (lines 517-525)
if result.get("type") == "selection" or result.get("status") == "selection":
    logger.info(f"[AI-CHAT] Selection response, returning structured data")
    await session_manager.update_last_used(request.session_id)
    return result  # Return immediately, no LLM processing
```

This ensures the frontend receives the structured data needed to render selection UI.

## Frontend Integration

### Component Hierarchy

```
Chat.tsx (Page)
    │
    ├─► ActiveProjectBadge (Shows current project)
    │
    ├─► ChatQuickActions (Quick action buttons)
    │
    ├─► ClawdbotMessageList
    │     │
    │     └─► ClawdbotMessageBubble (Per message)
    │           │
    │           ├─► ChatTextBlock (type: "text")
    │           ├─► ChatSelectionBlock (type: "selection")
    │           ├─► ChatExecutionBlock (type: "execution")
    │           └─► ChatErrorBlock (type: "error")
    │
    └─► ClawdbotChatInput (Message input)
```

### Response Type Handling

**Text Response**
```typescript
{
  type: "text",
  text: "Your project is running smoothly."
}
```
→ Rendered as plain text with markdown support

**Selection Response**
```typescript
{
  type: "selection",
  message: "Which project?",
  options: [
    { label: "ThinkAI (thinkai-likrt6)", value: "thinkai-likrt6" },
    { label: "AssetBrain (assetbrain-kfpa4x)", value: "assetbrain-kfpa4x" }
  ],
  intent: { tool: "set_active_project", args: {} }
}
```
→ Rendered as radio buttons in `ChatSelectionBlock`

**Execution Response**
```typescript
{
  type: "execution",
  text: "Project started successfully!",
  progress: [
    { status: "success", message: "Started PM2 process" }
  ]
}
```
→ Rendered with progress indicators and action buttons

### State Management (useAIChat Hook)

```typescript
const {
  messages,           // AIChatMessage[]
  isLoading,          // boolean
  sendMessage,        // (msg: string, activeProject?: string) => void
  handleSelection,    // (value: string) => void
  handleConfirmation, // (confirmed: boolean) => void
  activeProjectName,  // string | null
  setActiveProject,   // (project) => void
} = useAIChat();
```

### API Client Functions

**Send Chat Message**
```typescript
// src/lib/aiChatApi.ts
export async function postChatMessage(
  sessionId: string,
  message: string,
  activeProject?: string
): Promise<AIChatResponse>
```

**Submit Selection**
```typescript
export async function postSelection(
  sessionId: string,
  selection: string,
  intent: { tool: string; args: Record<string, unknown> }
): Promise<AIChatResponse>
```

**Submit Confirmation**
```typescript
export async function postConfirm(
  sessionId: string,
  confirmed: boolean
): Promise<AIChatResponse>
```

## Data Flow

### 1. Chat Flow

```
Frontend Message (ClawdbotChatInput)
    │
    ▼
POST /api/chat
{
  message: "switch project",
  session_id: "uuid",
  active_project: "thinkai-likrt6"
}
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
              │                      │
              │                      ▼
              │                   Build Conversation with Tool Result
              │                      │
              │                      ▼
              │                   Call GLM API (LLM Summarization)
              │                      │
              │                      ▼
              │                   Return Natural Language Response
              │
              └─► Multiple Matches → Return selection_response
                                        {
                                          type: "selection",
                                          options: [...],
                                          intent: {...}
                                        }
```

### 2. Selection Flow

```
Frontend Selection (ChatSelectionBlock)
    │
    ▼
POST /api/selection
{
  session_id: "uuid",
  selection: "thinkai-likrt6",
  intent: { tool: "set_active_project", args: {} }
}
    │
    ▼
Update Intent Args with selection
    │
    ▼
Update Session (set_active_project)
    │
    ▼
Execute Tool (ToolExecutor)
    │
    ▼
Build Conversation with Tool Result
    │
    ▼
Call GLM API (LLM Summarization)
    │
    ▼
Return Natural Language Response
{
  type: "execution" | "text",
  text: "I've switched to ThinkAI for you!",
  progress: [...]
}
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
