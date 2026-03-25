#!/usr/bin/env python3
"""Test if the prompt builder works without f-string errors"""

import sys

# Test the f-string directly
frontend_domain = "test.dreambigwithai.com"
backend_domain = "api.test.dreambigwithai.com"
project_path = "/tmp/test"

# This is the problematic f-string from the code
try:
    prompt = f"""
**Screenshot Format (Chrome DevTools MCP):**
```javascript
// WebP 75% = ~5KB (BEST - 60-70% smaller than PNG)
await page.screenshot({{ type: 'webp', quality: 75, path: 'screenshot.webp' }});

// Alternative: WebP 20% = ~3KB (low quality, only if needed)
await page.screenshot({{ type: 'webp', quality: 20, path: 'screenshot.webp' }});
```

Frontend URL: https://{frontend_domain}
Backend URL: https://{backend_domain}
Project Root: {project_path}
"""
    print("✅ SUCCESS: F-string formatted without errors!")
    print(f"Prompt length: {len(prompt)} characters")
    print("\n--- Prompt Preview ---")
    print(prompt[:500])
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
