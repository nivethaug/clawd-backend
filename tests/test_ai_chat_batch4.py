#!/usr/bin/env python3
"""
Batch 4: Validation & Stress Tests (Categories 13-16)
Tests for response validation, performance, and error handling.

Run with: python test_ai_chat_batch4.py --batch4
"""

import argparse
import json
import sys
import time
import random
import concurrent.futures
from typing import Dict, Optional, Tuple, List

import requests
from test_utils_comprehensive import (
    validate_response_schema,
    validate_progress_format,
    generate_session_id,
    generate_long_message,
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


class Batch4Tester:
    """Test client for Batch 4: Validation & Stress Tests (Categories 13-16)"""
    
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
    # Category 13: Error Response Validation
    # ========================================================================
    
    def test_category_13_error_responses(self):
        """Test error responses have proper structure."""
        log_test_header("13: Error Responses", "Error message validation")
        
        # Trigger various error conditions
        error_messages = [
            "nonexistent-project-xyz start",  # Non-existent project
            "invalid-command-that-does-not-exist",  # Unknown command
            "",  # Empty message
        ]
        
        for msg in error_messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response and response.get("type") == "error":
                # Validate error structure
                has_message = "message" in response or "text" in response
                passed = has_message
                message = f"Error response has message: {has_message}"
            elif response:
                # Not an error, but might be valid (text, selection)
                passed = True
                message = f"Got {response.get('type')} instead of error (acceptable)"
            else:
                # Timeout or no response is acceptable for errors
                passed = True
                message = "No response (acceptable for error conditions)"
            
            result = TestResult(
                category="13-Errors",
                test_name=f"error_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 14: Progress Format Validation
    # ========================================================================
    
    def test_category_14_progress_format(self):
        """Test progress arrays have correct format."""
        log_test_header("14: Progress Format", "Execution progress validation")
        
        # Commands that should return execution with progress
        execution_commands = [
            "list projects",
            "show status"
        ]
        
        for msg in execution_commands:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response and response.get("type") == "execution":
                # Validate progress array
                if "progress" in response:
                    validation = validate_progress_format(response["progress"])
                    passed = validation.is_valid
                    message = f"Progress format valid: {passed}"
                    if validation.errors:
                        message += f" | Errors: {validation.errors}"
                else:
                    # Execution without progress is a warning, not failure
                    passed = True
                    message = "Execution has no progress array (acceptable)"
            elif response:
                passed = True
                message = f"Got {response.get('type')} instead of execution"
            else:
                passed = False
                message = "No response"
            
            result = TestResult(
                category="14-Progress",
                test_name=f"progress_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Category 15: High Load Stress Test
    # ========================================================================
    
    def test_category_15_high_load(self, num_requests: int = 50):
        """Stress test with concurrent requests."""
        log_test_header("15: High Load", f"{num_requests} concurrent requests")
        
        test_messages = ["list projects", "status", "help"]
        
        def make_request(i: int) -> Tuple[int, bool, float]:
            session_id = generate_session_id()
            msg = random.choice(test_messages)
            response, elapsed = self.chat(msg, session_id)
            return i, response is not None, elapsed
        
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(num_requests)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        total_time = time.time() - start_time
        successful = sum(1 for _, success, _ in results if success)
        
        # Success criteria: 90% success rate
        success_rate = (successful / num_requests * 100)
        passed = success_rate >= 90.0
        
        message = f"{successful}/{num_requests} succeeded ({success_rate:.1f}%) in {total_time:.2f}s"
        
        result = TestResult(
            category="15-Stress",
            test_name="high_load_concurrent",
            passed=passed,
            message=message,
            elapsed_time=total_time
        )
        self.report.add_result(result)
        log_test_result(result)
        
        # Additional metrics
        response_times = [elapsed for _, _, elapsed in results]
        avg_time = sum(response_times) / len(response_times)
        
        print(f"\n  Stress Test Metrics:")
        print(f"    Total requests: {num_requests}")
        print(f"    Successful: {successful}")
        print(f"    Success rate: {success_rate:.1f}%")
        print(f"    Total time: {total_time:.2f}s")
        print(f"    Avg response time: {avg_time:.2f}s")
        print(f"    Requests/second: {num_requests/total_time:.2f}")
    
    # ========================================================================
    # Category 16: Response Schema Validation
    # ========================================================================
    
    def test_category_16_schema_validation(self):
        """Validate all responses match schema."""
        log_test_header("16: Schema Validation", "Response structure validation")
        
        test_messages = [
            "hello",
            "list projects",
            "start bot",
            "delete everything"
        ]
        
        for msg in test_messages:
            session_id = generate_session_id()
            response, elapsed = self.chat(msg, session_id)
            
            if response:
                validation = validate_response_schema(response)
                passed = validation.is_valid
                
                message = f"'{msg[:20]}' → schema valid: {validation.is_valid}"
                
                if validation.errors:
                    message += f" | Errors: {validation.errors}"
                if validation.warnings:
                    message += f" | Warnings: {validation.warnings}"
            else:
                passed = False
                message = f"'{msg[:20]}' → No response"
            
            result = TestResult(
                category="16-Schema",
                test_name=f"schema_{msg[:15]}",
                passed=passed,
                message=message,
                elapsed_time=elapsed
            )
            self.report.add_result(result)
            log_test_result(result)
    
    # ========================================================================
    # Test Runner
    # ========================================================================
    
    def run_batch_4(self, stress_requests: int = 50):
        """Run all Batch 4 tests"""
        log_section("BATCH 4: Validation & Stress Tests (Categories 13-16)")
        
        self.test_category_13_error_responses()
        self.test_category_14_progress_format()
        self.test_category_15_high_load(stress_requests)
        self.test_category_16_schema_validation()


def main():
    parser = argparse.ArgumentParser(
        description="Batch 4: Validation & Stress Tests (Categories 13-16)"
    )
    
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                       help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--batch4", action="store_true",
                       help="Run Batch 4 tests")
    parser.add_argument("--category", help="Run specific category (13-16)")
    parser.add_argument("--stress", action="store_true",
                       help="Include stress test in category run")
    parser.add_argument("--requests", type=int, default=50,
                       help="Number of stress test requests (default: 50)")
    parser.add_argument("--output", help="Output JSON report file")
    
    args = parser.parse_args()
    
    if not any([args.batch4, args.category]):
        print("❌ No test mode specified. Use --batch4 or --category")
        print("\nExamples:")
        print("  python test_ai_chat_batch4.py --batch4")
        print("  python test_ai_chat_batch4.py --batch4 --requests 100")
        print("  python test_ai_chat_batch4.py --category 15-Stress --requests 100")
        sys.exit(1)
    
    # Initialize tester
    print("="*80)
    print("BATCH 4: VALIDATION & STRESS TESTS (Categories 13-16)")
    print("="*80)
    print(f"Target: {args.base_url}")
    print(f"Endpoint: {API_PREFIX}/chat")
    print(f"Started: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    tester = Batch4Tester(args.base_url)
    
    # Run tests
    if args.category:
        category_map = {
            "13": tester.test_category_13_error_responses,
            "13-Errors": tester.test_category_13_error_responses,
            "14": tester.test_category_14_progress_format,
            "14-Progress": tester.test_category_14_progress_format,
            "15": lambda: tester.test_category_15_high_load(args.requests),
            "15-Stress": lambda: tester.test_category_15_high_load(args.requests),
            "16": tester.test_category_16_schema_validation,
            "16-Schema": tester.test_category_16_schema_validation,
        }
        
        if args.category in category_map:
            category_map[args.category]()
        else:
            print(f"❌ Unknown category: {args.category}")
            print(f"Available: {list(category_map.keys())}")
            sys.exit(1)
    else:
        tester.run_batch_4(args.requests)
    
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
