# Type-Based Project Directory Structure - Implementation Summary

## Overview
Successfully implemented type-based project directory structure for the Clawd Backend. Projects are now created inside type-specific subfolders under `/root/dreampilot/projects/`.

## Changes Made

### 1. project_manager.py
**Main implementation file - completely refactored path building logic**

#### Added:
- `TYPE_FOLDER_MAP`: Mapping dictionary for type to folder name conversion
  - website → website
  - telegrambot → telegram
  - discordbot → discord
  - tradingbot → trading
  - scheduler → scheduler
  - custom → custom

- `get_project_type(type_id)`: Fetches project type from database
  - Queries project_types table
  - Returns type string (e.g., 'website', 'telegrambot')
  - Falls back to 'website' if type_id is None or invalid

- `map_type_to_folder(project_type)`: Maps type to folder name
  - Uses TYPE_FOLDER_MAP
  - Falls back to 'website' for unknown types

- `build_type_based_path(project_id, name, type_id)`: Builds full path
  - Generates folder name with timestamp
  - Constructs path: `/root/dreampilot/projects/{type_folder}/{folder_name}`

#### Modified:
- `BASE_PROJECTS_DIR`: Updated from `/var/lib/openclaw/projects` to `/root/dreampilot/projects`
- `create_project_folder()`: Now accepts `type_id` parameter and uses type-based path
- `create_project_with_git()`: Now accepts `type_id` parameter
- `create_project_with_readme()`: Now accepts `type_id` parameter

#### Added Imports:
- `Optional` from typing
- `get_db` from database

### 2. app.py
**Updated to pass type_id to ProjectFileManager**

#### Removed:
- Legacy `BASE_PROJECTS_DIR` constant (no longer used)
- `os.makedirs(BASE_PROJECTS_DIR, exist_ok=True)` (no longer needed)

#### Modified:
- `create_project()` function: Passes `type_id` to `create_project_with_git()`
  - Line 297: `project_folder_path, folder_success = project_manager.create_project_with_git(project_id, request.name, type_id)`

### 3. context_injector.py
**Updated base path for security validation**

#### Modified:
- `PROJECT_BASE_PATH`: Updated from `/var/lib/openclaw/projects` to `/root/dreampilot/projects`
  - This ensures path traversal protection works with new directory structure

## Path Structure Examples

### Before:
```
/var/lib/openclaw/projects/
├── 1_MyWebsite_20260214_011613/
├── 2_MyBot_20260214_012015/
└── 3_DiscordBot_20260214_012345/
```

### After:
```
/root/dreampilot/projects/
├── website/
│   ├── 1_MyWebsite_20260214_011613/
│   └── 7_NullTypeProject_20260214_013516/
├── telegram/
│   └── 2_MyBot_20260214_012015/
├── discord/
│   └── 3_DiscordBot_20260214_012345/
├── trading/
│   └── 4_TradingBot_20260214_013516/
├── scheduler/
│   └── 5_SchedulerApp_20260214_013516/
└── custom/
    └── 6_CustomProject_20260214_013516/
```

## README.md Content

README.md is automatically generated with the correct dynamic path:

```markdown
openclaw project folder path: /root/dreampilot/projects/trading/4_TradingBot_20260214_013516
```

## Database Integration

### Query Used:
```sql
SELECT type FROM project_types WHERE id = ?
```

### Type Mapping:
- type_id 1 → 'website' → folder 'website'
- type_id 2 → 'telegrambot' → folder 'telegram'
- type_id 3 → 'discordbot' → folder 'discord'
- type_id 4 → 'tradingbot' → folder 'trading'
- type_id 5 → 'scheduler' → folder 'scheduler'
- type_id 6 → 'custom' → folder 'custom'

### Fallback Behavior:
- If `type_id` is `None` → defaults to 'website' → folder 'website'
- If `type_id` is invalid (not in DB) → defaults to 'website' → folder 'website'

## Security Considerations

1. **Path Traversal Protection**: Maintained via `context_injector.py` validation
2. **Sanitization**: Project names are sanitized via existing `sanitize_name()` method
3. **Type Validation**: type_id is validated in `app.py` before use
4. **No Path Injection**: All paths are built server-side, no user-controlled segments

## Files Created per Project

All unchanged from previous implementation:
- `README.md` - with dynamic path
- `.gitignore` - standard Python/IDE/OS ignores
- `changerule.md` - project change rules
- `.git/` - initialized Git repository

## Backward Compatibility

- **No API Changes**: The endpoint signature remains the same
- **No Database Schema Changes**: Uses existing `project_types` table
- **No Frontend Impact**: Frontend doesn't need to know about path structure
- **No OpenClaw Modification**: Uses existing file creation logic

## Testing Performed

### Unit Tests:
✅ Type mapping (telegrambot → telegram, etc.)
✅ Path building for all project types
✅ Name sanitization
✅ Database type lookup

### Integration Tests:
✅ Project creation for all 6 types
✅ Null type fallback to website
✅ Invalid type_id fallback to website
✅ All required files created
✅ README.md contains correct path
✅ Git repository initialized

### Regression Tests:
✅ No references to old path in codebase
✅ Path validation updated correctly
✅ No breaking changes to existing APIs

## Git Statistics

```
app.py              |   5 +--
context_injector.py |   2 +-
project_manager.py  | 118 ++++++++++++++++++++++++++++++++++++++++++++--------
4 files changed, 102 insertions(+), 23 deletions(-)
```

## Branch Information

- **Branch**: `feature/type-based-project-dirs`
- **Base**: `main`
- **Status**: Ready for review and merge

## Future Considerations

1. **Migration**: Existing projects in `/var/lib/openclaw/projects/` will need to be migrated if they should be organized by type
2. **Monitoring**: May want to add logging for type fallback cases
3. **Validation**: Consider adding validation that type_folder doesn't contain special characters

## Implementation Checklist

- [x] Update BASE_PROJECTS_DIR in project_manager.py
- [x] Add TYPE_FOLDER_MAP dictionary
- [x] Implement get_project_type() method
- [x] Implement map_type_to_folder() method
- [x] Implement build_type_based_path() method
- [x] Update create_project_folder() to accept type_id
- [x] Update create_project_with_git() to accept type_id
- [x] Update create_project_with_readme() to accept type_id
- [x] Update app.py to pass type_id
- [x] Update context_injector.py PROJECT_BASE_PATH
- [x] Remove unused BASE_PROJECTS_DIR from app.py
- [x] Add Optional import
- [x] Add database import
- [x] Test all 6 project types
- [x] Test null type fallback
- [x] Test invalid type fallback
- [x] Verify README.md content
- [x] Verify all files created
- [x] Remove old path references
- [x] Create feature branch from main

All requirements met! ✅
