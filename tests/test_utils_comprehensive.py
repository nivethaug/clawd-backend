#!/usr/bin/env python3
"""
Test Utilities for Comprehensive AI Chat Testing

Provides validation helpers, test data generators, and result aggregation.
"""

import json
import time
import uuid
import random
import string
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import statistics


# ============================================================================
# Response Schema Validation
# ============================================================================

VALID_RESPONSE_TYPES = {"text", "execution", "selection", "confirmation", "input_required", "error"}


@dataclass
class ValidationResult:
    """Result of schema validation."""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def add_error(self, error: str):
        self.errors.append(error)
        self.is_valid = False
    
    def add_warning(self, warning: str):
        self.warnings.append(warning)


def validate_response_schema(response: Dict[str, Any]) -> ValidationResult:
    """
    Validate response matches expected schema.
    
    Expected fields:
    - type: required, must be valid enum
    - text: optional, for type='text'
    - progress: optional, for type='execution'
    - message: optional, for type='selection' or 'confirmation'
    - options: optional, for type='selection'
    - intent: optional, for type='confirmation' or 'selection'
    - fields: optional, for type='input_required'
    - details: optional, for type='error'
    """
    result = ValidationResult(is_valid=True)
    
    # Check required field 'type'
    if "type" not in response:
        result.add_error("Missing required field: 'type'")
        return result
    
    # Validate type is valid enum
    response_type = response["type"]
    if response_type not in VALID_RESPONSE_TYPES:
        result.add_error(f"Invalid type '{response_type}'. Must be one of: {VALID_RESPONSE_TYPES}")
    
    # Type-specific validation
    if response_type == "text":
        if "text" not in response:
            result.add_warning("Type is 'text' but no 'text' field provided")
    
    elif response_type == "execution":
        if "progress" not in response:
            result.add_warning("Type is 'execution' but no 'progress' field provided")
        if "text" not in response:
            result.add_warning("Type is 'execution' but no 'text' field provided")
    
    elif response_type == "selection":
        if "options" not in response:
            result.add_error("Type is 'selection' but no 'options' field provided")
        elif not isinstance(response["options"], list):
            result.add_error("'options' must be a list")
        elif len(response["options"]) == 0:
            result.add_warning("'options' list is empty")
        
        if "intent" not in response:
            result.add_warning("Type is 'selection' but no 'intent' field provided")
        
        if "message" not in response:
            result.add_warning("Type is 'selection' but no 'message' field provided")
    
    elif response_type == "confirmation":
        if "intent" not in response:
            result.add_error("Type is 'confirmation' but no 'intent' field provided")
        
        if "message" not in response:
            result.add_warning("Type is 'confirmation' but no 'message' field provided")
    
    elif response_type == "input_required":
        if "fields" not in response:
            result.add_error("Type is 'input_required' but no 'fields' field provided")
        elif not isinstance(response["fields"], list):
            result.add_error("'fields' must be a list")
    
    elif response_type == "error":
        if "text" not in response and "message" not in response:
            result.add_warning("Type is 'error' but no error message provided")
    
    return result


def validate_intent_structure(intent: Dict[str, Any]) -> ValidationResult:
    """Validate intent structure for selection/confirmation."""
    result = ValidationResult(is_valid=True)
    
    if not isinstance(intent, dict):
        result.add_error("Intent must be a dictionary")
        return result
    
    if "tool" not in intent:
        result.add_error("Intent missing 'tool' field")
    
    if "args" not in intent:
        result.add_warning("Intent has no 'args' field")
    
    return result


def validate_progress_format(progress: List[Dict[str, Any]]) -> ValidationResult:
    """Validate progress array format."""
    result = ValidationResult(is_valid=True)
    
    if not isinstance(progress, list):
        result.add_error("Progress must be a list")
        return result
    
    if len(progress) == 0:
        result.add_warning("Progress list is empty")
        return result
    
    for i, step in enumerate(progress):
        if not isinstance(step, dict):
            result.add_error(f"Progress step {i} is not a dictionary")
            continue
        
        if "status" not in step:
            result.add_warning(f"Progress step {i} missing 'status' field")
        
        if "message" not in step:
            result.add_warning(f"Progress step {i} missing 'message' field")
    
    return result


# ============================================================================
# Test Data Generators
# ============================================================================

def generate_session_id() -> str:
    """Generate unique session ID."""
    return f"test-{uuid.uuid4()}"


def generate_random_string(length: int = 10) -> str:
    """Generate random alphanumeric string."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_long_message(length: int = 1000) -> str:
    """Generate very long message for stress testing."""
    words = ["test", "hello", "project", "start", "stop", "bot", "server"]
    message = []
    while len(' '.join(message)) < length:
        message.append(random.choice(words))
    return ' '.join(message)[:length]


def get_test_messages_basic() -> List[str]:
    """Get basic test messages."""
    return [
        "hello",
        "what can you do",
        "list projects",
        "help"
    ]


def get_test_messages_tool_execution() -> List[str]:
    """Get tool execution test messages."""
    return [
        "start ThinkAI",
        "stop AssetBrain",
        "restart thinkai",
        "show status for assetbrain"
    ]


def get_test_messages_ambiguous() -> List[str]:
    """Get ambiguous project references."""
    return [
        "start Think",
        "restart Asset",
        "stop AI",
        "show logs"
    ]


def get_test_messages_natural_language() -> List[str]:
    """Get natural language variations."""
    return [
        "hey can you start my bot pls",
        "i think my trading bot is down fix it",
        "spin up everything",
        "stop all stuff right now",
        "create something like crypto trading bot",
        "what's the status of my projects?",
        "can u help me with my website",
        "I need to restart that thing"
    ]


def get_test_messages_security() -> List[str]:
    """Get security test messages."""
    return [
        "delete project",
        "delete all projects",
        "drop database",
        "shutdown server",
        "rm -rf /",
        "format disk"
    ]


def get_test_messages_invalid() -> List[str]:
    """Get invalid input test messages."""
    return [
        "",
        "asdfghjkl",
        "???",
        "12345",
        "!@#$%^&*()",
        generate_long_message(1000)
    ]


# ============================================================================
# Performance Metrics
# ============================================================================

@dataclass
class PerformanceMetrics:
    """Track performance metrics."""
    response_times: List[float] = field(default_factory=list)
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    
    def add_response(self, elapsed: float, success: bool, timeout: bool = False):
        self.response_times.append(elapsed)
        if timeout:
            self.timeout_count += 1
        elif success:
            self.success_count += 1
        else:
            self.error_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistical summary."""
        if not self.response_times:
            return {
                "total_requests": 0,
                "success_rate": 0,
                "avg_time": 0,
                "min_time": 0,
                "max_time": 0,
                "p50": 0,
                "p95": 0,
                "p99": 0
            }
        
        sorted_times = sorted(self.response_times)
        n = len(sorted_times)
        
        return {
            "total_requests": n,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "timeout_count": self.timeout_count,
            "success_rate": (self.success_count / n * 100) if n > 0 else 0,
            "avg_time": statistics.mean(sorted_times),
            "min_time": sorted_times[0],
            "max_time": sorted_times[-1],
            "p50": sorted_times[int(n * 0.5)] if n > 0 else 0,
            "p95": sorted_times[int(n * 0.95)] if n > 0 else 0,
            "p99": sorted_times[int(n * 0.99)] if n > 0 else 0
        }


# ============================================================================
# Result Aggregation
# ============================================================================

@dataclass
class TestResult:
    """Single test result."""
    category: str
    test_name: str
    passed: bool
    message: str
    response: Optional[Dict[str, Any]] = None
    elapsed_time: Optional[float] = None
    error: Optional[str] = None


@dataclass
class TestReport:
    """Aggregated test report."""
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    results: List[TestResult] = field(default_factory=list)
    metrics: PerformanceMetrics = field(default_factory=PerformanceMetrics)
    
    def add_result(self, result: TestResult):
        self.results.append(result)
        if result.elapsed_time is not None:
            self.metrics.add_response(
                result.elapsed_time,
                result.passed
            )
    
    def finalize(self):
        """Mark test as complete."""
        self.end_time = datetime.now()
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"passed": 0, "failed": 0}
            if r.passed:
                categories[r.category]["passed"] += 1
            else:
                categories[r.category]["failed"] += 1
        
        duration = (self.end_time - self.start_time).total_seconds() if self.end_time else 0
        
        return {
            "total_tests": len(self.results),
            "passed": passed,
            "failed": failed,
            "success_rate": (passed / len(self.results) * 100) if self.results else 0,
            "duration_seconds": duration,
            "categories": categories,
            "metrics": self.metrics.get_stats()
        }
    
    def to_json(self) -> str:
        """Export as JSON."""
        return json.dumps({
            "summary": self.get_summary(),
            "results": [
                {
                    "category": r.category,
                    "test_name": r.test_name,
                    "passed": r.passed,
                    "message": r.message,
                    "elapsed_time": r.elapsed_time,
                    "error": r.error
                }
                for r in self.results
            ]
        }, indent=2, default=str)


# ============================================================================
# Logging Helpers
# ============================================================================

def log_test_header(category: str, description: str):
    """Print test category header."""
    print(f"\n{'='*80}")
    print(f"CATEGORY: {category}")
    print(f"{'='*80}")
    print(f"{description}\n")


def log_test_result(result: TestResult):
    """Print test result."""
    status = "✓ PASS" if result.passed else "✗ FAIL"
    color = "\033[92m" if result.passed else "\033[91m"
    reset = "\033[0m"
    
    print(f"{color}{status}{reset} [{result.category}] {result.test_name}")
    print(f"  {result.message}")
    if result.elapsed_time:
        print(f"  Time: {result.elapsed_time:.2f}s")
    if result.error:
        print(f"  Error: {result.error}")
    print()


def log_section(title: str):
    """Print section divider."""
    print(f"\n{'─'*80}")
    print(f"  {title}")
    print(f"{'─'*80}\n")
