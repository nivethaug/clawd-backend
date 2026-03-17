# Frontend Template Fix - lovable-tagger

## Issue
Frontend builds were failing with the error:
```
Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'lovable-tagger'
```

## Root Cause
The `vite.config.ts` file in templates imports `lovable-tagger`:
```typescript
import { componentTagger } from "lovable-tagger";
```

But the package was not included in `package.json`.

## Fix Applied
Added `lovable-tagger` to devDependencies in:
- `/root/clawd-backend/templates/blank-template/frontend/package.json`

## Status
✅ Local blank-template updated

## Remote Templates (GitHub)
The following templates are from GitHub and still need updates:
- `saas` - https://github.com/billionairebyalgo-byte/core-saas-hub
- `crm` - https://github.com/billionairebyalgo-byte/flow-crm
- `finance` - https://github.com/billionairebyalgo-byte/finflow-ui
- `billing` - https://github.com/billionairebyalgo-byte/billing-hub
- `social` - https://github.com/billionairebyalgo-byte/social-media-hub
- `analytics` - https://github.com/billionairebyalgo-byte/insight-dashboard
- `portfolio` - https://github.com/billionairebyalgo-byte/apex-portfolio

### Action Required
Update each GitHub template's `frontend/package.json` to include:
```json
{
  "devDependencies": {
    "lovable-tagger": "^0.0.1",
    ...
  }
}
```

## Alternative: Post-Install Script
Add a post-install script in the build process to automatically install lovable-tagger if missing:
```python
# In infrastructure_manager.py during frontend build
if not package_json.get("devDependencies", {}).get("lovable-tagger"):
    subprocess.run(["npm", "install", "--save-dev", "lovable-tagger"], ...)
```

## Testing
Verified fix on project 701 (PandaDoc Clone):
```bash
npm install --save-dev lovable-tagger
npm run build
✓ built in 3.55s
```
