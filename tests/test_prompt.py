#!/usr/bin/env python3
"""Test prompt building for f-string errors"""

import sys
sys.path.insert(0, 'clawd-backend')

# Mock the dependencies
class MockPath:
    def __init__(self, path):
        self.path = path
    
    def __truediv__(self, other):
        return MockPath(f"{self.path}/{other}")
    
    def exists(self):
        return True
    
    def __str__(self):
        return self.path

# Test building the prompt
try:
    from acp_chat_handler import ACPChatHandler
    
    # Create handler with mock path
    handler = ACPChatHandler.__new__(ACPChatHandler)
    handler.project_path = MockPath("/test/project")
    handler.project_name = "test-project"
    handler.frontend_path = MockPath("/test/project/frontend")
    handler.frontend_src_path = MockPath("/test/project/frontend/src")
    handler.frontend_domain = "test.dreambigwithai.com"
    handler.backend_domain = "test-api.dreambigwithai.com"
    handler.claude_agent = None
    handler.progress_mapper = None
    
    # Build prompt
    prompt = handler._build_chat_prompt("Test message", "")
    print(f"✅ Prompt built successfully! Length: {len(prompt)} chars")
    
    # Check for unescaped braces
    import re
    # Find single { that aren't doubled
    issues = re.findall(r'(?<!\{)\{(?!\{)(?![\w\s}]*\})', prompt)
    if issues:
        print(f"❌ Found unescaped braces: {len(issues)} instances")
        # Show context
        lines = prompt.split('\n')
        for i, line in enumerate(lines, 1):
            if '{' in line and '{{' not in line and not any(x in line for x in ['{self.', '{session_', '{user_']):
                print(f"  Line {i}: {line[:80]}")
    else:
        print("✅ No unescaped braces found!")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
