#!/usr/bin/env python3
"""
Unified Test Runner - All Batches
Runs all 16 test categories across 4 batches and provides consolidated results.

Usage:
  python run_all_tests.py                    # Run all batches
  python run_all_tests.py --quick            # Run quick tests only
  python run_all_tests.py --stress 100       # Include stress test with 100 requests
  python run_all_tests.py --output report.json
"""

import argparse
import json
import sys
import time
from typing import Dict, List
from datetime import datetime

# Import all batch testers
from test_ai_chat_comprehensive import AIChatComprehensiveTester
from test_ai_chat_batch2 import Batch2Tester
from test_ai_chat_batch3 import Batch3Tester
from test_ai_chat_batch4 import Batch4Tester

from test_utils_comprehensive import (
    TestReport,
    log_section
)

# Configuration
DEFAULT_BASE_URL = "http://195.200.14.37:8002"


class UnifiedTestRunner:
    """Runs all test batches and aggregates results."""
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url
        self.master_report = TestReport()
        self.batch_results: List[Dict] = []
    
    def run_batch_1(self):
        """Run Batch 1: Core Tests (Categories 1-4)"""
        print("\n" + "="*80)
        print("RUNNING BATCH 1: Core Tests (Categories 1-4)")
        print("="*80)
        
        start_time = time.time()
        tester = AIChatComprehensiveTester(self.base_url)
        tester.run_batch_1()
        tester.report.finalize()
        
        # Merge results
        for result in tester.report.results:
            self.master_report.add_result(result)
        
        batch_summary = tester.report.get_summary()
        batch_summary['duration'] = time.time() - start_time
        batch_summary['batch_name'] = "Batch 1: Core Tests"
        self.batch_results.append(batch_summary)
        
        return batch_summary
    
    def run_batch_2(self):
        """Run Batch 2: Flow Tests (Categories 5-8)"""
        print("\n" + "="*80)
        print("RUNNING BATCH 2: Flow Tests (Categories 5-8)")
        print("="*80)
        
        start_time = time.time()
        tester = Batch2Tester(self.base_url)
        tester.run_batch_2()
        tester.report.finalize()
        
        # Merge results
        for result in tester.report.results:
            self.master_report.add_result(result)
        
        batch_summary = tester.report.get_summary()
        batch_summary['duration'] = time.time() - start_time
        batch_summary['batch_name'] = "Batch 2: Flow Tests"
        self.batch_results.append(batch_summary)
        
        return batch_summary
    
    def run_batch_3(self):
        """Run Batch 3: Security & Session Tests (Categories 9-12)"""
        print("\n" + "="*80)
        print("RUNNING BATCH 3: Security & Session Tests (Categories 9-12)")
        print("="*80)
        
        start_time = time.time()
        tester = Batch3Tester(self.base_url)
        tester.run_batch_3()
        tester.report.finalize()
        
        # Merge results
        for result in tester.report.results:
            self.master_report.add_result(result)
        
        batch_summary = tester.report.get_summary()
        batch_summary['duration'] = time.time() - start_time
        batch_summary['batch_name'] = "Batch 3: Security & Session"
        self.batch_results.append(batch_summary)
        
        return batch_summary
    
    def run_batch_4(self, stress_requests: int = 50):
        """Run Batch 4: Validation & Stress Tests (Categories 13-16)"""
        print("\n" + "="*80)
        print("RUNNING BATCH 4: Validation & Stress Tests (Categories 13-16)")
        print("="*80)
        
        start_time = time.time()
        tester = Batch4Tester(self.base_url)
        tester.run_batch_4(stress_requests)
        tester.report.finalize()
        
        # Merge results
        for result in tester.report.results:
            self.master_report.add_result(result)
        
        batch_summary = tester.report.get_summary()
        batch_summary['duration'] = time.time() - start_time
        batch_summary['batch_name'] = "Batch 4: Validation & Stress"
        self.batch_results.append(batch_summary)
        
        return batch_summary
    
    def run_all_batches(self, stress_requests: int = 50):
        """Run all 4 batches sequentially"""
        log_section("UNIFIED TEST RUNNER - ALL BATCHES")
        
        print(f"Target: {self.base_url}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Stress test requests: {stress_requests}")
        
        # Run all batches
        batch1_summary = self.run_batch_1()
        batch2_summary = self.run_batch_2()
        batch3_summary = self.run_batch_3()
        batch4_summary = self.run_batch_4(stress_requests)
        
        # Finalize master report
        self.master_report.finalize()
        
        return self.master_report.get_summary()
    
    def run_quick_tests(self):
        """Run quick test suite (just Batches 1 & 3 for fast validation)"""
        log_section("QUICK TEST SUITE - Batches 1 & 3")
        
        print(f"Target: {self.base_url}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Mode: Quick (Batches 1 & 3 only)")
        
        # Run quick batches
        self.run_batch_1()
        self.run_batch_3()
        
        # Finalize master report
        self.master_report.finalize()
        
        return self.master_report.get_summary()
    
    def print_unified_summary(self):
        """Print comprehensive summary across all batches"""
        master_summary = self.master_report.get_summary()
        
        print("\n" + "="*80)
        print("UNIFIED TEST SUMMARY - ALL BATCHES")
        print("="*80)
        
        # Overall stats
        print(f"\n[RESULTS] OVERALL RESULTS:")
        print(f"  Total Tests: {master_summary['total_tests']}")
        print(f"  [PASS] Passed: {master_summary['passed']}")
        print(f"  [FAIL] Failed: {master_summary['failed']}")
        print(f"  [RATE] Success Rate: {master_summary['success_rate']:.1f}%")
        print(f"  [TIME] Duration: {master_summary['duration_seconds']:.2f}s")
        print(f"  [AVG] Avg Response Time: {master_summary['metrics']['avg_time']:.2f}s")
        
        # Batch breakdown
        print(f"\n📦 BATCH BREAKDOWN:")
        for batch in self.batch_results:
            status = "[OK]" if batch['failed'] == 0 else "[WARN]"
            rate = batch['success_rate']
            print(f"  {status} {batch['batch_name']}")
            print(f"     {batch['passed']}/{batch['total_tests']} passed ({rate:.1f}%) - {batch['duration']:.1f}s")
        
        # Category breakdown
        print(f"\n📋 CATEGORY BREAKDOWN:")
        for cat, stats in master_summary['categories'].items():
            total = stats['passed'] + stats['failed']
            rate = (stats['passed'] / total * 100) if total > 0 else 0
            status = "[OK]" if stats['failed'] == 0 else "[FAIL]"
            print(f"  {status} {cat}: {stats['passed']}/{total} ({rate:.0f}%)")
        
        # Performance metrics
        metrics = master_summary['metrics']
        print(f"\n⚡ PERFORMANCE METRICS:")
        print(f"  Total Requests: {metrics['total_requests']}")
        print(f"  Success Count: {metrics['success_count']}")
        print(f"  Error Count: {metrics['error_count']}")
        print(f"  Avg Time: {metrics['avg_time']:.2f}s")
        print(f"  Min Time: {metrics['min_time']:.2f}s")
        print(f"  Max Time: {metrics['max_time']:.2f}s")
        print(f"  P50: {metrics['p50']:.2f}s")
        print(f"  P95: {metrics['p95']:.2f}s")
        print(f"  P99: {metrics['p99']:.2f}s")
        
        # Highlight critical issues
        failed_categories = [cat for cat, stats in master_summary['categories'].items() 
                           if stats['failed'] > 0]
        
        if failed_categories:
            print(f"\n⚠️  CATEGORIES WITH FAILURES:")
            for cat in failed_categories:
                stats = master_summary['categories'][cat]
                print(f"  • {cat}: {stats['failed']} failures")
        
        print("\n" + "="*80)


def main():
    parser = argparse.ArgumentParser(
        description="Unified Test Runner - All Batches"
    )
    
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL,
                       help=f"Base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--quick", action="store_true",
                       help="Run quick tests only (Batches 1 & 3)")
    parser.add_argument("--stress", type=int, default=50,
                       help="Stress test request count (default: 50)")
    parser.add_argument("--batch1", action="store_true",
                       help="Run only Batch 1")
    parser.add_argument("--batch2", action="store_true",
                       help="Run only Batch 2")
    parser.add_argument("--batch3", action="store_true",
                       help="Run only Batch 3")
    parser.add_argument("--batch4", action="store_true",
                       help="Run only Batch 4")
    parser.add_argument("--output", help="Output JSON report file")
    
    args = parser.parse_args()
    
    # Print header
    print("="*80)
    print("UNIFIED AI CHAT TEST SUITE")
    print("="*80)
    print(f"Target Server: {args.base_url}")
    print(f"Endpoint: /api/ai/chat")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # Initialize runner
    runner = UnifiedTestRunner(args.base_url)
    
    # Determine what to run
    if args.quick:
        print("\n🏃 Running QUICK test suite (Batches 1 & 3)")
        runner.run_quick_tests()
    elif args.batch1:
        print("\n🎯 Running Batch 1 only")
        runner.run_batch_1()
        runner.master_report.finalize()
    elif args.batch2:
        print("\n🎯 Running Batch 2 only")
        runner.run_batch_2()
        runner.master_report.finalize()
    elif args.batch3:
        print("\n🎯 Running Batch 3 only")
        runner.run_batch_3()
        runner.master_report.finalize()
    elif args.batch4:
        print("\n🎯 Running Batch 4 only")
        runner.run_batch_4(args.stress)
        runner.master_report.finalize()
    else:
        print("\n[RUNNING] Running ALL batches (1-4)")
        runner.run_all_batches(args.stress)
    
    # Print unified summary
    runner.print_unified_summary()
    
    # Save report if requested
    if args.output:
        with open(args.output, 'w') as f:
            f.write(runner.master_report.to_json())
        print(f"\n📄 Report saved to: {args.output}")
    
    # Get final summary for exit code
    master_summary = runner.master_report.get_summary()
    
    # Print completion message
    print(f"\n✨ Test run completed!")
    print(f"   Total: {master_summary['passed']}/{master_summary['total_tests']} passed")
    print(f"   Success Rate: {master_summary['success_rate']:.1f}%")
    print(f"   Duration: {master_summary['duration_seconds']:.2f}s")
    
    # Exit with appropriate code
    sys.exit(0 if master_summary['failed'] == 0 else 1)


if __name__ == "__main__":
    main()
