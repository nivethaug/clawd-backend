#!/usr/bin/env python3
"""
Comprehensive AI Chat Endpoint Test Suite
28 test categories covering functionality, security, performance, and edge cases.

Target Server: http://195.200.14.37:8002
Endpoint: POST /api/ai/chat
"""

import argparse
import json
import sys
import time
import random
import concurrent.futures
from typing import Dict, Optional, Any, List, Tuple

import requests
from test_utils_comprehensive import (
    # Validators
    validate_response_schema,
    validate_intent_structure,
    validate_progress_format,
    # Generators
    generate_session_id,
    generate_long_message,
    get_test_messages_basic,
    get_test_messages_tool_execution,
    get_test_messages_ambiguous,
    get_test_messages_natural_language,
    get_test_messages_security,
    get_test_messages_invalid,
    # Data classes
    TestResult,
    TestReport,
    # Logging
    log_test_header,
    log_test_result,
    log_section
)

# Configuration
DEFAULT_BASE_URL = "http://195.200.14.37:8002"
API_PREFIX = "/api/ai"
DEFAULT_TIMEOUT = 30


class AIChatComprehensiveTester:
    """Comprehensive test client for AI chat endpoints."""
    
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
    # BATCH 1: Core Tests (Categories 1-4)
    # ========================================================================
    
    def test_category_1_basic_functionality(self):
        """Test basic conversation and help messages."""
        log_test_header("1: Basic Functionality", "Simple text queries")
        
        messages = get_test_messages_basic()
        session_id = generate_session_id()
        
        for msg in messages:
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                validation = validate_response_schema(response)
                passed = validation.is_valid
                message = f"'{msg[:30]}' → {response.get('type', 'unknown')}"
            else:
                passed = False
                message = f"'{msg[:30]}' → No response"
            
            result = TestResult(
                category="1-Basic",
                test_name=f"basic_{msg[:20]}",
                passed=passed,
                message=message,
                response=response,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    def test_category_2_tool_execution(self):
        """Test tool execution commands."""
        log_test_header("2: Tool Execution", "Start/stop/restart operations")
        
        messages = get_test_messages_tool_execution()
        
        for msg in messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should be execution or selection (if ambiguous)
                valid_types = {"execution", "selection"}
                passed = response.get("type") in valid_types
                message = f"'{msg[:30]}' → {response.get('type')}"
            else:
                passed = False
                message = f"'{msg[:30]}' → No response"
            
            result = TestResult(
                category="2-Tool-Exec",
                test_name=f"tool_{msg[:20]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    def test_category_3_project_resolution(self):
        """Test ambiguous project references trigger selection."""
        log_test_header("3: Project Resolution", "Ambiguous names → selection")
        
        messages = get_test_messages_ambiguous()
        
        for msg in messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should return selection with options, or error if missing params
                # or execution if GLM lists projects
                response_type = response.get("type")
                
                if response_type == "selection":
                    options = response.get("options") or []
                    passed = len(options) > 0
                    message = f"'{msg}' → selection with {len(options)} options"
                elif response_type in {"error", "execution"}:
                    # Error (missing params) or execution (listing projects) is acceptable
                    passed = True
                    message = f"'{msg}' → {response_type} (acceptable)"
                else:
                    passed = False
                    message = f"'{msg}' → {response_type} (unexpected)"
            else:
                passed = False
                message = f"'{msg}' → No response"
            
            result = TestResult(
                category="3-Resolution",
                test_name=f"resolve_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    def test_category_4_no_project_edge_case(self):
        """Test operations with no matching projects."""
        log_test_header("4: No Project Edge Case", "Non-existent project handling")
        
        # Test with non-existent projects
        messages = [
            "start nonexistent-project-xyz",
            "stop fake-project-abc",
            "restart imaginary-project-123"
        ]
        
        for msg in messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                # Should return error or selection with all projects
                valid_types = {"error", "selection", "text"}
                passed = response.get("type") in valid_types
                
                if response.get("type") == "selection":
                    # Should have message about project not found or show all projects
                    options_count = len(response.get("options", []))
                    message_text = response.get("message", "").lower()
                    # Accept: showing all projects (2 real projects)
                    passed = (options_count > 0 or 
                             "not found" in message_text or 
                             "no match" in message_text)
                
                message = f"'{msg[:30]}' → {response.get('type')} (handled gracefully)"
            else:
                passed = False
                message = f"'{msg[:30]}' → No response"
            
            result = TestResult(
                category="4-NoProject",
                test_name=f"noproject_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Test Runners
    # ========================================================================
    
    def run_batch_1(self):
        """Run Batch 1: Core Tests (Categories 1-4)"""
        log_section("BATCH 1: Core Tests (Categories 1-4)")
        
        self.test_category_1_basic_functionality()
        self.test_category_2_tool_execution()
        self.test_category_3_project_resolution()
        self.test_category_4_no_project_edge_case()
    
    def run_quick_tests(self):
        """Run quick test suite (categories 1-14)"""
        log_section("QUICK TEST SUITE (Categories 1-14)")
        
        self.run_batch_1()
        # TODO: Add batches 2-4 when implemented
        
        print("\n⚠️  Only Batch 1 implemented. Run --all for complete test.")
    
    def run_all_tests(self):
        """Run all 28 test categories"""
        log_section("FULL TEST SUITE (All 28 Categories)")
        
        self.run_batch_1()
        # TODO: Add all batches when implemented
        
        print("\n⚠️  Only Batch 1 implemented. Remaining batches coming soon.")
    
    def run_category(self, category: str):
        """Run specific test category"""
        category_map = {
            "1": self.test_category_1_basic_functionality,
            "1-Basic": self.test_category_1_basic_functionality,
            "2": self.test_category_2_tool_execution,
            "2-Tool-Exec": self.test_category_2_tool_execution,
            "3": self.test_category_3_project_resolution,
            "3-Resolution": self.test_category_3_project_resolution,
            "4": self.test_category_4_no_project_edge_case,
            "4-NoProject": self.test_category_4_no_project_edge_case,
        }
        
        if category in category_map:
            category_map[category]()
        else:
            print(f"❌ Unknown category: {category}")
            print(f"Available categories (Batch 1): {list(category_map.keys())}")


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive AI Chat Test Suite"
    )
    
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                       help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--batch1", action="store_true",
                       help="Run Batch 1: Core Tests (Categories 1-4)")
    parser.add_argument("--quick", action="store_true",
                       help="Run quick test (Categories 1-14)")
    parser.add_argument("--all", action="store_true",
                       help="Run all 28 categories")
    parser.add_argument("--category", help="Run specific category")
    parser.add_argument("--output", help="Output JSON report file")
    
    args = parser.parse_args()
    
    # Validate at least one test mode is selected
    if not any([args.batch1, args.quick, args.all, args.category]):
        print("❌ No test mode specified. Use --batch1, --quick, --all, or --category")
        print("\nExamples:")
        print("  python test_ai_chat_comprehensive.py --batch1")
        print("  python test_ai_chat_comprehensive.py --quick")
        print("  python test_ai_chat_comprehensive.py --category 1-Basic")
        sys.exit(1)
    
    # Initialize tester
    print("="*80)
    print("COMPREHENSIVE AI CHAT TEST SUITE")
    print("="*80)
    print(f"Target: {args.base_url}")
    print(f"Endpoint: {API_PREFIX}/chat")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    tester = AIChatComprehensiveTester(args.base_url)
    
    # Run tests based on flags
    if args.batch1:
        tester.run_batch_1()
    elif args.category:
        tester.run_category(args.category)
    elif args.quick:
        tester.run_quick_tests()
    elif args.all:
        tester.run_all_tests()
    
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
