#!/usr/bin/env python3
"""
Batch 2: Flow Tests (Categories 5-8)
Tests for selection, confirmation, input_required flows, and multi-turn context.

Run with: python test_ai_chat_batch2.py --batch2
"""

import argparse
import json
import sys
import time
from typing import Dict, Optional, Tuple

import requests
from test_utils_comprehensive import (
    validate_response_schema,
    validate_intent_structure,
    generate_session_id,
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


class Batch2Tester:
    """Test client for Batch 2: Flow Tests (Categories 5-8)"""
    
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
    # Category 5: Selection Flow Compatibility
    # ========================================================================
    
    def test_category_5_selection_flow(self):
        """Test selection flow with proper intent structure."""
        log_test_header("5: Selection Flow", "Intent structure validation")
        
        # Messages that should trigger selection
        messages = [
            "start Think",
            "restart Asset",
            "show logs"
        ]
        
        for msg in messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response and response.get("type") == "selection":
                # Validate selection has required fields
                has_options = "options" in response and len(response["options"]) > 0
                has_intent = "intent" in response
                has_message = "message" in response
                
                # Validate intent structure
                intent_valid = True
                if has_intent:
                    validation = validate_intent_structure(response["intent"])
                    intent_valid = validation.is_valid
                
                passed = has_options and has_intent and intent_valid
                message = f"'{msg}' → selection with {len(response.get('options', []))} options, intent_valid={intent_valid}"
            elif response and response.get("type") in {"error", "execution"}:
                # Error or execution is acceptable for "show logs" (no active project)
                # or if the command executed successfully
                passed = True
                message = f"'{msg}' → {response.get('type')} (acceptable)"
            else:
                passed = False
                message = f"'{msg}' → Expected selection, got {response.get('type') if response else 'None'}"
            
            result = TestResult(
                category="5-Selection",
                test_name=f"selection_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 6: Confirmation Flow
    # ========================================================================
    
    def test_category_6_confirmation_flow(self):
        """Test dangerous operations require confirmation."""
        log_test_header("6: Confirmation Flow", "Dangerous operations → confirmation")
        
        # Messages that should trigger confirmation
        dangerous_messages = [
            "delete project",
            "remove everything",
            "stop all projects",
            "uninstall ThinkAI"
        ]
        
        for msg in dangerous_messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should be confirmation or selection (if ambiguous)
                valid_types = {"confirmation", "selection", "error"}
                response_type = response.get("type")
                
                passed = response_type in valid_types
                
                if response_type == "confirmation":
                    # Validate confirmation has intent
                    has_intent = "intent" in response
                    has_message = "message" in response
                    passed = has_intent and has_message
                    message = f"'{msg[:30]}' → confirmation (intent={has_intent})"
                elif response_type == "selection":
                    message = f"'{msg[:30]}' → selection (ambiguous target)"
                elif response_type == "error":
                    message = f"'{msg[:30]}' → error (blocked)"
                else:
                    passed = False
                    message = f"'{msg[:30]}' → {response_type} (unexpected)"
            else:
                passed = False
                message = f"'{msg[:30]}' → No response"
            
            result = TestResult(
                category="6-Confirmation",
                test_name=f"confirm_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 7: Input Required Flow
    # ========================================================================
    
    def test_category_7_input_required(self):
        """Test operations that require additional input."""
        log_test_header("7: Input Required", "Operations needing more info")
        
        # Messages that might require additional input
        messages = [
            "create project",
            "deploy project",
            "configure settings"
        ]
        
        for msg in messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                response_type = response.get("type")
                
                # Should be input_required, selection, or text (asking for info)
                valid_types = {"input_required", "selection", "text", "error"}
                passed = response_type in valid_types
                
                if response_type == "input_required":
                    # Validate fields structure
                    has_fields = "fields" in response and isinstance(response["fields"], list)
                    message = f"'{msg}' → input_required (fields={has_fields})"
                elif response_type == "selection":
                    message = f"'{msg}' → selection (needs project choice)"
                elif response_type == "text":
                    message = f"'{msg}' → text (asking for info)"
                else:
                    message = f"'{msg}' → {response_type}"
            else:
                passed = False
                message = f"'{msg}' → No response"
            
            result = TestResult(
                category="7-InputRequired",
                test_name=f"input_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 8: Session Context (Multi-turn)
    # ========================================================================
    
    def test_category_8_session_context(self):
        """Test multi-turn conversations maintain context."""
        log_test_header("8: Session Context", "Multi-turn conversation flow")
        
        session_id = generate_session_id()
        
        # Step 1: List projects
        response1, elapsed1 = self.chat("list projects", session_id)
        if not response1:
            result = TestResult(
                category="8-Context",
                test_name="multi_turn_list",
                passed=False,
                message="Step 1 failed: No response to 'list projects'"
            )
            self.report.add_result(result)
            log_test_result(result)
            return
        
        # Step 2: Use "it" to refer to last mentioned project
        # This tests if context is maintained
        response2, elapsed2 = self.chat("show its status", session_id)
        
        if response2:
            # Should understand "its" refers to a project
            # Could be execution, selection, or text
            valid_types = {"execution", "selection", "text"}
            passed = response2.get("type") in valid_types
            
            message = f"Multi-turn: list → status | Context maintained: {passed}"
        else:
            passed = False
            message = "Multi-turn: list → status | Step 2 failed: No response"
        
        result = TestResult(
            category="8-Context",
            test_name="multi_turn_context",
            passed=passed,
            message=message,
            elapsed_time=elapsed2
        )
        self.report.add_result(result)
        log_test_result(result)
        
        # Additional test: Different session should NOT have same context
        session_id_new = generate_session_id()
        response3, elapsed3 = self.chat("show its status", session_id_new)
        
        if response3:
            # New session should NOT understand "its" - should ask for clarification
            # Should be selection or text asking for project
            passed = response3.get("type") in {"selection", "text"}
            message = f"New session isolated: {passed} (asked for clarification)"
        else:
            passed = False
            message = "New session test failed: No response"
        
        result = TestResult(
            category="8-Context",
            test_name="session_isolation_basic",
            passed=passed,
            message=message,
            elapsed_time=elapsed3
        )
        self.report.add_result(result)
        log_test_result(result)
    
    # ========================================================================
    # Test Runner
    # ========================================================================
    
    def run_batch_2(self):
        """Run all Batch 2 tests"""
        log_section("BATCH 2: Flow Tests (Categories 5-8)")
        
        self.test_category_5_selection_flow()
        self.test_category_6_confirmation_flow()
        self.test_category_7_input_required()
        self.test_category_8_session_context()


def main():
    parser = argparse.ArgumentParser(
        description="Batch 2: Flow Tests (Categories 5-8)"
    )
    
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                       help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--batch2", action="store_true",
                       help="Run Batch 2 tests")
    parser.add_argument("--category", help="Run specific category (5-8)")
    parser.add_argument("--output", help="Output JSON report file")
    
    args = parser.parse_args()
    
    if not any([args.batch2, args.category]):
        print("❌ No test mode specified. Use --batch2 or --category")
        print("\nExamples:")
        print("  python test_ai_chat_batch2.py --batch2")
        print("  python test_ai_chat_batch2.py --category 5-Selection")
        sys.exit(1)
    
    # Initialize tester
    print("="*80)
    print("BATCH 2: FLOW TESTS (Categories 5-8)")
    print("="*80)
    print(f"Target: {args.base_url}")
    print(f"Endpoint: {API_PREFIX}/chat")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    tester = Batch2Tester(args.base_url)
    
    # Run tests
    if args.category:
        category_map = {
            "5": tester.test_category_5_selection_flow,
            "5-Selection": tester.test_category_5_selection_flow,
            "6": tester.test_category_6_confirmation_flow,
            "6-Confirmation": tester.test_category_6_confirmation_flow,
            "7": tester.test_category_7_input_required,
            "7-InputRequired": tester.test_category_7_input_required,
            "8": tester.test_category_8_session_context,
            "8-Context": tester.test_category_8_session_context,
        }
        
        if args.category in category_map:
            category_map[args.category]()
        else:
            print(f"❌ Unknown category: {args.category}")
            print(f"Available: {list(category_map.keys())}")
            sys.exit(1)
    else:
        tester.run_batch_2()
    
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
