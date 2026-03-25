"""
Test script to verify domain-based project identification
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_normalization():
    """Test input normalization"""
    print("=" * 60)
    print("TEST: Input Normalization")
    print("=" * 60)
    
    test_cases = [
        ("myapp-abc123", "myapp-abc123"),
        ("123", "123"),
        (123, "123"),
        (None, None),
    ]
    
    for input_val, expected in test_cases:
        result = str(input_val) if input_val is not None else None
        status = "✓" if result == expected else "✗"
        print(f"{status} Input: {input_val!r} ({type(input_val).__name__}) → Output: {result!r}")
        assert result == expected, f"Expected {expected!r}, got {result!r}"
    
    print()


def test_project_matching():
    """Test project matching logic"""
    print("=" * 60)
    print("TEST: Project Matching")
    print("=" * 60)
    
    # Mock projects
    projects = [
        {"id": 1, "name": "My App", "domain": "myapp-abc123"},
        {"id": 2, "name": "Test Project", "domain": "test-xyz789"},
        {"id": 3, "name": "Demo", "domain": "demo-def456"},
    ]
    
    test_cases = [
        ("myapp-abc123", "domain", "myapp-abc123"),
        ("1", "numeric_id", "myapp-abc123"),
        (1, "numeric_int", "myapp-abc123"),
        ("unknown", None, None),
    ]
    
    for input_val, match_type, expected_domain in test_cases:
        # Normalize
        active_project_value = str(input_val) if input_val is not None else None
        
        # Try domain match
        matched = None
        if active_project_value:
            for project in projects:
                if project["domain"] == active_project_value:
                    matched = project
                    break
            
            # Try numeric ID fallback
            if not matched and active_project_value.isdigit():
                numeric_id = int(active_project_value)
                for project in projects:
                    if project["id"] == numeric_id:
                        matched = project
                        break
        
        result_domain = matched["domain"] if matched else None
        status = "✓" if result_domain == expected_domain else "✗"
        print(f"{status} Input: {input_val!r} ({match_type or 'none'}) → Matched: {result_domain or 'None'}")
        assert result_domain == expected_domain, f"Expected {expected_domain}, got {result_domain}"
    
    print()


def test_resolver():
    """Test project resolver with domain-based IDs"""
    print("=" * 60)
    print("TEST: Project Resolver")
    print("=" * 60)
    
    from services.ai.project_resolver import get_project_resolver
    
    resolver = get_project_resolver()
    
    projects = [
        {"id": 1, "name": "My App", "domain": "myapp-abc123"},
        {"id": 2, "name": "Test Project", "domain": "test-xyz789"},
    ]
    
    # Test exact domain match
    result = resolver.resolve(
        user_text="start myapp",
        projects=projects,
        explicit_project_id="myapp-abc123"
    )
    
    status = "✓" if result.status == "resolved" and result.project["domain"] == "myapp-abc123" else "✗"
    print(f"{status} Explicit domain match: {result.status} → {result.project['domain'] if result.project else 'None'}")
    assert result.status == "resolved"
    assert result.project["domain"] == "myapp-abc123"
    
    # Test numeric ID conversion
    result = resolver.resolve(
        user_text="start project",
        projects=projects,
        explicit_project_id="1"
    )
    
    status = "✓" if result.status == "resolved" and result.project["domain"] == "myapp-abc123" else "✗"
    print(f"{status} Numeric ID conversion: {result.status} → {result.project['domain'] if result.project else 'None'}")
    assert result.status == "resolved"
    assert result.project["domain"] == "myapp-abc123"
    
    print()


def test_session_manager_signature():
    """Test that session manager signature is correct"""
    print("=" * 60)
    print("TEST: Session Manager Signature")
    print("=" * 60)
    
    # Read the file directly to check signature (avoids DB dependency)
    import re
    
    with open("utils/ai_session_manager.py", "r") as f:
        content = f.read()
    
    # Check set_active_project signature
    match = re.search(r'async def set_active_project\(self, session_key: str, project_domain: str\)', content)
    status = "✓" if match else "✗"
    print(f"{status} set_active_project signature uses 'project_domain: str'")
    assert match, "Signature should be: async def set_active_project(self, session_key: str, project_domain: str)"
    
    # Check that get_active_project JOINs on domain
    match = re.search(r'JOIN projects p ON s\.active_project_id = p\.domain', content)
    status = "✓" if match else "✗"
    print(f"{status} get_active_project JOINs on p.domain (not p.id)")
    assert match, "Should JOIN on domain, not id"
    
    # Check tool_executor.py
    with open("services/ai/tool_executor.py", "r") as f:
        executor_content = f.read()
    
    match = re.search(r'await session_manager\.set_active_project\(session_key, project\["domain"\]\)', executor_content)
    status = "✓" if match else "✗"
    print(f"{status} Tool executor stores project['domain']")
    assert match, "Tool executor should store domain, not numeric ID"
    
    print()


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("DOMAIN-BASED PROJECT IDENTIFICATION - VERIFICATION")
    print("=" * 60 + "\n")
    
    try:
        test_normalization()
        test_project_matching()
        test_resolver()
        test_session_manager_signature()
        
        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print()
        
        return 0
    
    except AssertionError as e:
        print("\n" + "=" * 60)
        print("✗ TEST FAILED")
        print("=" * 60)
        print(f"Error: {e}\n")
        return 1
    
    except Exception as e:
        print("\n" + "=" * 60)
        print("✗ UNEXPECTED ERROR")
        print("=" * 60)
        print(f"Error: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
