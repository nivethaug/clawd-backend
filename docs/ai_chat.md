# AI Chat System Documentation

## Overview

The AI Chat System is an LLM-powered DevOps interface that allows users to control projects, services, and infrastructure through natural language conversations. It integrates GLM-4.5-Air with direct Python function calls to execute operations safely and efficiently.

## Architecture

```
User Message → GLM LLM → Tool Decision → Core Functions → Response
     ↓            ↓           ↓              ↓              ↓
  Session    Tool Parse   Validation    Execution     Formatted
  Manager    Registry     + Resolver    Executor      Output
```

### Components

1. **GLM Client** (`services/ai/glm_client.py`)
   - Direct API integration with GLM-4.5-Air
   - Tool calling support with JSON Schema definitions
   - Automatic retry logic with timeout handling

2. **Tool Registry** (`services/ai/tool_registry.py`)
   - Defines 9 DevOps tools with JSON Schema
   - Categorizes tools: auto-execute, confirm-required, disabled
   - Validates tool arguments before execution

3. **Tool Executor** (`services/ai/tool_executor.py`)
   - Direct Python function calls (no HTTP)
   - PM2 integration for service control
   - Database queries for project management
   - Log retrieval with filtering

4. **Project Resolver** (`services/ai/project_resolver.py`)
   - Fuzzy matching for project names (0.6 cutoff)
   - Priority: explicit ID → active project → fuzzy match
   - Returns selection options for ambiguous matches

5. **Session Manager** (`utils/ai_session_manager.py`)
   - PostgreSQL-backed session persistence
   - Tracks active project per session
   - Stores pending intents for confirmation flow

6. **Response Formatter** (`utils/ai_response_formatter.py`)
   - Consistent response types across all endpoints
   - Supports: text, execution, selection, confirmation, error

## API Endpoints

### POST /api/ai/chat

Main chat endpoint for natural language interactions.

**Request:**
```json
{
  "session_id": "user-123",
  "message": "Start the myapp project",
  "active_project_id": 5
}
```

**Response Types:**

1. **Text Response** (general conversation)
```json
{
  "type": "text",
  "text": "I can help you manage your projects..."
}
```

2. **Execution Response** (tool executed)
```json
{
  "type": "execution",
  "text": "Started myapp-frontend and myapp-backend",
  "progress": [
    {
      "status": "success",
      "message": "Started myapp-frontend",
      "details": {...}
    }
  ]
}
```

3. **Selection Response** (ambiguous project)
```json
{
  "type": "selection",
  "text": "Which project did you mean?",
  "options": [
    {"value": "myapp", "label": "myapp", "description": "Active project"},
    {"value": "myapp2", "label": "myapp2", "description": "Created 2025-01-15"}
  ],
  "intent": {
    "tool": "start_project",
    "args": {"project_id": null}
  }
}
```

4. **Confirmation Response** (dangerous operation)
```json
{
  "type": "confirmation",
  "text": "Are you sure you want to create a new project?",
  "intent": {
    "tool": "create_project",
    "args": {"name": "new-project"}
  }
}
```

### POST /api/ai/selection

Handle user selection from project options.

**Request:**
```json
{
  "session_id": "user-123",
  "selection": "myapp",
  "intent": {
    "tool": "start_project",
    "args": {"project_id": null}
  }
}
```

**Response:** Same as execution response

### POST /api/ai/confirm

Handle user confirmation/cancel for dangerous operations.

**Request:**
```json
{
  "session_id": "user-123",
  "confirmed": true
}
```

**Response:** Same as execution response

## Available Tools

### Safe Tools (Auto-Execute)

1. **start_project**
   - Starts project frontend and backend services
   - Args: `project_id` (string)
   - PM2 naming: `{domain}-frontend`, `{domain}-backend`

2. **stop_project**
   - Stops project services
   - Args: `project_id` (string)

3. **restart_project**
   - Restarts project services
   - Args: `project_id` (string)

4. **list_projects**
   - Lists all projects with status
   - Args: none

5. **project_status**
   - Gets detailed project status
   - Args: `project_id` (string)

6. **get_logs**
   - Retrieves project logs
   - Args: `project_id` (string), `lines` (number, optional), `filter` (string, optional)

### Confirmation Required

7. **create_project**
   - Creates new project
   - Args: `name` (string), `template_id` (string, optional)

8. **start_all_projects**
   - Starts all active projects
   - Args: none

9. **stop_all_projects**
   - Stops all running projects
   - Args: none

### Disabled

10. **delete_project**
    - Disabled for safety (irreversible)
    - Use dashboard for deletions

## Database Schema

### ai_sessions Table

```sql
CREATE TABLE ai_sessions (
    id SERIAL PRIMARY KEY,
    session_key TEXT UNIQUE NOT NULL,
    active_project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    pending_intent JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Fields:**
- `session_key`: Unique session identifier (e.g., "user-123")
- `active_project_id`: Currently selected project
- `pending_intent`: Stored intent awaiting confirmation (JSONB)

## Environment Variables

Required in `.env`:

```bash
Z_AI_API_KEY=your_glm_api_key
Z_AI_API_BASE=https://api.z.ai/api/coding/paas/v4
Z_AI_MODEL=GLM-4.5-Air
```

## Error Handling

All errors return consistent format:

```json
{
  "type": "error",
  "text": "Error message",
  "details": {
    "error": "Detailed error info",
    "tool": "start_project"
  }
}
```

## Session Flow

1. **Initial Chat**
   - User sends message to `/api/ai/chat`
   - Session created or retrieved from database
   - Active project loaded from session or request

2. **Tool Execution**
   - GLM parses intent and selects tool
   - Tool validated against registry
   - Project resolved (fuzzy match if needed)
   - Tool executed via direct Python call
   - Response formatted and returned

3. **Selection Flow**
   - Ambiguous project match → selection response
   - User selects from options → `/api/ai/selection`
   - Tool executed with selected project

4. **Confirmation Flow**
   - Dangerous operation → confirmation response
   - Intent stored in `pending_intent`
   - User confirms/cancels → `/api/ai/confirm`
   - If confirmed: execute and clear intent
   - If cancelled: clear intent without execution

## PM2 Integration

### Naming Convention

Projects use domain-based naming:
- Frontend: `{domain}-frontend`
- Backend: `{domain}-backend`

Example:
- Project domain: `myapp`
- PM2 processes: `myapp-frontend`, `myapp-backend`

### Operations

All PM2 operations use `apps_service.pm2_action()`:
```python
pm2_action(domain, "start")
pm2_action(domain, "stop")
pm2_action(domain, "restart")
```

## Logging

All components use structured logging:
```
[AI-CHAT] Session user-123: Start myapp project
[AI-EXECUTOR] Executing start_project with domain=myapp
[AI-CHAT] Tool result: success
```

Log levels:
- INFO: Normal operations
- WARNING: Validation issues, retries
- ERROR: Failures, exceptions

## Testing

Run database migration:
```bash
python migrations/003_add_ai_sessions_table.py
```

Test endpoints:
```bash
# Chat
curl -X POST http://localhost:8000/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-1","message":"List all projects"}'

# Selection
curl -X POST http://localhost:8000/api/ai/selection \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-1","selection":"myapp","intent":{"tool":"start_project","args":{}}}'

# Confirm
curl -X POST http://localhost:8000/api/ai/confirm \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-1","confirmed":true}'
```

## Future Enhancements

1. **Additional Tools**
   - Environment variable management
   - Database backups
   - SSL certificate renewal
   - DNS record updates

2. **Context Awareness**
   - Remember previous commands
   - Multi-step workflows
   - Project-specific preferences

3. **Safety Features**
   - Rate limiting
   - Operation audit logs
   - Rollback capabilities

4. **Integration**
   - WebSocket for real-time updates
   - Slack/Discord bot interface
   - CI/CD pipeline triggers

## Troubleshooting

### "No pending operation to confirm"
- Intent expired or already executed
- Start new operation via `/api/ai/chat`

### "Project not found"
- Check project exists in database
- Verify domain field is set
- Use exact domain name or clear name

### "Tool is disabled"
- Operation not allowed via AI chat
- Use dashboard or direct API

### "GLM API timeout"
- Check Z_AI_API_KEY is valid
- Verify network connectivity
- Check API quota/limits

## Related Documentation

- [AI Chat Architecture](./ai_chat_architecture.md)
- [Project Management](./project_creation.md)
- [PM2 Integration](../README.md#pm2-management)
- [Database Schema](../projects_schema.sql)
