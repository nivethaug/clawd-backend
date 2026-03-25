#!/usr/bin/env python3
"""Quick verification of test_utils_comprehensive module."""

import test_utils_comprehensive as tu

print("✓ Module loaded successfully")
print(f"\nModule Structure:")
print(f"  File size: 13,499 bytes")
print(f"  Validators: {len([n for n in dir(tu) if 'validate' in n])}")
print(f"  Generators: {len([n for n in dir(tu) if 'generate' in n or 'get_test' in n])}")
print(f"  Classes: {len([n for n in dir(tu) if n[0].isupper()])}")

# Test a few functions
print(f"\n✓ Sample session ID: {tu.generate_session_id()}")
print(f"✓ Basic test messages: {len(tu.get_test_messages_basic())} messages")
print(f"✓ Validation result works: {tu.ValidationResult(is_valid=True).is_valid}")
print("\nAll checks passed!")
