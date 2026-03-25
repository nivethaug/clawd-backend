# Domain-Based Project Identification Migration

**Date:** 2026-03-25  
**Status:** Complete

## Summary

Migrated the backend to use `project.domain` (string) as the primary project identifier instead of numeric database IDs. This ensures consistent handling across the system and eliminates type mismatch errors.

---

## Changes Made

### 1. **API Request Model** (`api/ai_chat.py`)
- Updated `active_project` field to accept `Union[str, int]`
- Added input normalization to convert all values to string
- Implemented domain-first matching with numeric ID fallback

```python
active_project: Optional[Union[str, int]] = Field(None, description="...")
active_project_value = str(request.active_project) if request.active_project else None
```

### 2. **Database Schema** (`database_postgres.py`)
- Changed `ai_sessions.active_project_id` from `INTEGER` to `TEXT`
- Removed foreign key constraint (now stores domain string)
- Updated table creation to use TEXT type

```sql
active_project_id TEXT  -- Was: INTEGER REFERENCES projects(id)
```

### 3. **Session Manager** (`utils/ai_session_manager.py`)
- Updated `set_active_project()` to accept and store domain strings
- Modified `get_active_project()` to JOIN on `p.domain` instead of `p.id`

```python
async def set_active_project(session_key: str, project_domain: str):
    # Store domain, not numeric ID
```

### 4. **Tool Executor** (`services/ai/tool_executor.py`)
- Updated `_execute_set_active_project()` to store domain in session
- Return value now uses domain as `project_id`

```python
await session_manager.set_active_project(session_key, project["domain"])
```

### 5. **Selection API** (`api/ai_selection.py`)
- Simplified to store domain directly (removed DB lookup for numeric ID)

```python
await session_manager.set_active_project(request.session_id, request.selection)
```

### 6. **Documentation** (`docs/ai_chat.md`, `docs/ai_chat_architecture.md`)
- Updated schema examples to show TEXT type
- Added notes explaining domain-based storage

---

## Migration Path

### For Existing Deployments

Run the migration script:

```bash
python migrations/003_ai_sessions_domain_migration.py
```

This script will:
1. Create temporary column `active_project_domain` (TEXT)
2. Migrate existing INTEGER IDs to domain strings
3. Drop old column
4. Rename temp column to `active_project_id`
5. Recreate indexes

### For Fresh Installations

The updated schema in `database_postgres.py` will create the table with TEXT column directly.

---

## Backward Compatibility

### Input Handling
- ✅ Accepts both string domains and numeric IDs
- ✅ Normalizes all inputs to string
- ✅ Attempts domain match first
- ✅ Falls back to numeric ID match if needed
- ✅ Converts numeric matches to domain for storage

### Tool Execution
- ✅ All tools now receive domain strings as `project_id`
- ✅ Session stores domain strings
- ✅ Resolver returns domain strings

### Edge Cases Handled
- Invalid domain → Returns error
- Numeric ID input → Converts to domain
- No match → Returns selection response
- Session with old numeric ID → Will be migrated by script

---

## Testing Checklist

- [ ] Create new project → domain stored correctly
- [ ] Switch project with domain input → works
- [ ] Switch project with numeric ID input → converts to domain
- [ ] Execute tool with active project → uses domain
- [ ] Selection response → returns domain values
- [ ] Session persistence → stores domain
- [ ] Migration script → converts existing sessions

---

## Files Modified

1. `api/ai_chat.py` - Request handling and normalization
2. `api/ai_selection.py` - Selection handling
3. `database_postgres.py` - Schema definition
4. `services/ai/tool_executor.py` - Tool execution
5. `utils/ai_session_manager.py` - Session management
6. `docs/ai_chat.md` - Documentation
7. `docs/ai_chat_architecture.md` - Architecture docs
8. `migrations/003_ai_sessions_domain_migration.py` - Migration script (new)

---

## Benefits

1. **Consistency**: All project references use the same identifier type
2. **Type Safety**: No more int vs string comparison errors
3. **Clarity**: Domain names are more meaningful than numeric IDs
4. **Portability**: Domains are stable across database migrations
5. **Debugging**: Logs show readable domain names

---

## Future Considerations

- All new features should use domain as the primary identifier
- Numeric IDs can still be used for database-internal operations
- API responses should always return domain in `project_id` fields
