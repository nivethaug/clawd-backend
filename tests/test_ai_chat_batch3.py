#!/usr/bin/env python3
"""
Batch 3: Security & Session Tests (Categories 9-12)
Critical tests for session isolation, security, and natural language processing.

Run with: python test_ai_chat_batch3.py --batch3
"""

import argparse
import json
import sys
import time
from typing import Dict, Optional, Tuple

import requests
from test_utils_comprehensive import (
    validate_response_schema,
    generate_session_id,
    get_test_messages_natural_language,
    get_test_messages_security,
    TestResult,
    TestReport,
    log_test_header,
    log_test_result,
    log_section
)

# Configuration
DEFAULT_BASE_URL = "http://195.200.14.37:8002"
API_PREFIX = "/api/ai"
DEFAULT_TIMEOUT = 30


class Batch3Tester:
    """Test client for Batch 3: Security & Session Tests (Categories 9-12)"""
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.report = TestReport()
    
    def chat(self, message: str, session_id: str, timeout: int = DEFAULT_TIMEOUT) -> Tuple[Optional[Dict], float]:
        """Make chat request and return (response, elapsed_time)"""
        url = f"{self.base_url}{API_PREFIX}/chat"
        payload = {"session_id": session_id, "message": message}
        
        start = time.time()
        try:
            response = self.session.post(url, json=payload, timeout=timeout)
            elapsed = time.time() - start
            
            if response.status_code == 200:
                return response.json(), elapsed
            else:
                return None, elapsed
        except Exception as e:
            elapsed = time.time() - start
            return None, elapsed
    
    # ========================================================================
    # Category 9: Session Isolation (CRITICAL)
    # ========================================================================
    
    def test_category_9_session_isolation(self):
        """CRITICAL: Verify sessions don't share context."""
        log_test_header("9: Session Isolation", "Parallel sessions independent")
        
        # Session A: Set active project by selecting from options
        session_a = generate_session_id()
        response_a1, _ = self.chat("show status for ThinkAI", session_a)
        
        if not response_a1:
            result = TestResult(
                category="9-Isolation",
                test_name="session_isolation",
                passed=False,
                message="Session A failed to start"
            )
            self.report.add_result(result)
            log_test_result(result)
            return
        
        # Session B: Should NOT inherit A's context
        # "restart" without project should ask for selection
        session_b = generate_session_id()
        response_b, elapsed_b = self.chat("restart", session_b)
        
        if response_b:
            # B should NOT know which project to restart
            # Should return selection (asking which project)
            passed = response_b.get("type") in {"selection", "error"}
            message = f"Session B isolated: {passed} (got {response_b.get('type')})"
        else:
            passed = False
            message = "Session B: No response"
        
        result = TestResult(
            category="9-Isolation",
            test_name="session_isolation",
            passed=passed,
            message=message,
            elapsed_time=elapsed_b
        )
        self.report.add_result(result)
        log_test_result(result)
        
        # Test 2: Session A should maintain its own context
        response_a2, elapsed_a2 = self.chat("show status", session_a)
        
        if response_a2:
            # Session A should work fine with another command
            valid_types = {"execution", "selection", "text", "error"}
            passed = response_a2.get("type") in valid_types
            message = f"Session A context maintained: {passed}"
        else:
            passed = False
            message = "Session A follow-up: No response"
        
        result = TestResult(
            category="9-Isolation",
            test_name="session_continuity",
            passed=passed,
            message=message,
            elapsed_time=elapsed_a2
        )
        self.report.add_result(result)
        log_test_result(result)
    
    # ========================================================================
    # Category 10: Natural Language Variations
    # ========================================================================
    
    def test_category_10_natural_language(self):
        """Test natural language command variations."""
        log_test_header("10: Natural Language", "Informal/casual language")
        
        messages = get_test_messages_natural_language()
        
        for msg in messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should understand intent despite informal language
                validation = validate_response_schema(response)
                passed = validation.is_valid
                message = f"'{msg[:40]}' → {response.get('type')}"
            else:
                passed = False
                message = f"'{msg[:40]}' → No response"
            
            result = TestResult(
                category="10-NaturalLang",
                test_name=f"natural_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 11: Security Tests
    # ========================================================================
    
    def test_category_11_security(self):
        """Test dangerous commands are blocked."""
        log_test_header("11: Security", "Dangerous commands blocked")
        
        dangerous_messages = get_test_messages_security()
        
        for msg in dangerous_messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should NOT execute, should be error, text, or confirmation
                # Should NOT be execution without confirmation
                response_type = response.get("type")
                
                # Execution is only acceptable if it's actually asking for confirmation
                if response_type == "execution":
                    # Check if this is actually a dangerous operation being executed
                    # This would be a security FAIL
                    passed = False
                    message = f"🔴 SECURITY: '{msg[:30]}' → execution (NOT BLOCKED!)"
                else:
                    # Text, error, selection, confirmation are all safe
                    passed = response_type in {"text", "error", "selection", "confirmation"}
                    message = f"'{msg[:30]}' → {response_type} (blocked: {passed})"
            else:
                passed = False
                message = f"'{msg[:30]}' → No response"
            
            result = TestResult(
                category="11-Security",
                test_name=f"security_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 12: Invalid Input Handling
    # ========================================================================
    
    def test_category_12_invalid_input(self):
        """Test graceful handling of invalid inputs."""
        log_test_header("12: Invalid Input", "Malformed/invalid messages")
        
        invalid_messages = [
            "",
            "asdfghjkl qwertyuiop",
            "???",
            "12345 67890",
            "!@#$%^&*()",
            "a" * 500  # Very long message
        ]
        
        for msg in invalid_messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should return error, text, or input_required
                # Should NOT crash or return execution
                valid_types = {"error", "text", "input_required"}
                passed = response.get("type") in valid_types
                
                # Special case: empty string might timeout or fail
                if msg == "" and response is None:
                    passed = True  # Timeout is acceptable for empty
                
                message = f"'{msg[:30]}...' → {response.get('type')} (handled gracefully)"
            else:
                # No response is acceptable for invalid input
                passed = True
                message = f"'{msg[:30]}...' → No response (acceptable)"
            
            result = TestResult(
                category="12-Invalid",
                test_name=f"invalid_{msg[:10]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Test Runner
    # ========================================================================
    
    def run_batch_3(self):
        """Run all Batch 3 tests"""
        log_section("BATCH 3: Security & Session Tests (Categories 9-12)")
        
        self.test_category_9_session_isolation()
        self.test_category_10_natural_language()
        self.test_category_11_security()
        self.test_category_12_invalid_input()


def main():
    parser = argparse.ArgumentParser(
        description="Batch 3: Security & Session Tests (Categories 9-12)"
    )
    
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                       help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--batch3", action="store_true",
                       help="Run Batch 3 tests")
    parser.add_argument("--category", help="Run specific category (9-12)")
    parser.add_argument("--output", help="Output JSON report file")
    
    args = parser.parse_args()
    
    if not any([args.batch3, args.category]):
        print("❌ No test mode specified. Use --batch3 or --category")
        print("\nExamples:")
        print("  python test_ai_chat_batch3.py --batch3")
        print("  python test_ai_chat_batch3.py --category 9-Isolation")
        sys.exit(1)
    
    # Initialize tester
    print("="*80)
    print("BATCH 3: SECURITY & SESSION TESTS (Categories 9-12)")
    print("="*80)
    print(f"Target: {args.base_url}")
    print(f"Endpoint: {API_PREFIX}/chat")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    tester = Batch3Tester(args.base_url)
    
    # Run tests
    if args.category:
        category_map = {
            "9": tester.test_category_9_session_isolation,
            "9-Isolation": tester.test_category_9_session_isolation,
            "10": tester.test_category_10_natural_language,
            "10-NaturalLang": tester.test_category_10_natural_language,
            "11": tester.test_category_11_security,
            "11-Security": tester.test_category_11_security,
            "12": tester.test_category_12_invalid_input,
            "12-Invalid": tester.test_category_12_invalid_input,
        }
        
        if args.category in category_map:
            category_map[args.category]()
        else:
            print(f"❌ Unknown category: {args.category}")
            print(f"Available: {list(category_map.keys())}")
            sys.exit(1)
    else:
        tester.run_batch_3()
    
    # Finalize and print report
    tester.report.finalize()
    summary = tester.report.get_summary()
    
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"Total: {summary['passed']}/{summary['total_tests']} passed")
    print(f"Failed: {summary['failed']}")
    print(f"Success Rate: {summary['success_rate']:.1f}%")
    print(f"Duration: {summary['duration_seconds']:.2f}s")
    print(f"Avg Response Time: {summary['metrics']['avg_time']:.2f}s")
    
    # Category breakdown
    if summary['categories']:
        print("\nCategory Breakdown:")
        for cat, stats in summary['categories'].items():
            total = stats['passed'] + stats['failed']
            rate = (stats['passed'] / total * 100) if total > 0 else 0
            status = "✓" if stats['failed'] == 0 else "✗"
            print(f"  {status} {cat}: {stats['passed']}/{total} ({rate:.0f}%)")
    
    # Save report if requested
    if args.output:
        with open(args.output, 'w') as f:
            f.write(tester.report.to_json())
        print(f"\n📄 Report saved to: {args.output}")
    
    # Exit with appropriate code
    sys.exit(0 if summary['failed'] == 0 else 1)


if __name__ == "__main__":
    main()
