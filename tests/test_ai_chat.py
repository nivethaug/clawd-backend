#!/usr/bin/env python3
"""
AI Chat Endpoint Tester

Test all AI chat endpoints with comprehensive scenarios.
Can run from anywhere with configurable base URL.

Usage:
    test_ai_chat chat "list my projects"
    test_ai_chat chat "start project testapp"
    test_ai_chat selection --session-id "user-123" --intent '{"tool":"start_project","args":{"project_id":"testapp"}}'
    test_ai_chat confirm --session-id "user-123" --action "confirm"
    test_ai_chat test-all
"""

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Dict, Optional, Any

import requests

# Configuration
DEFAULT_BASE_URL = "http://195.200.14.37:8002"
API_PREFIX = "/api/ai"
DEFAULT_TIMEOUT = 30


def log(level: str, message: str, color: bool = True) -> None:
    """Print formatted log message with colors."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    if color:
        colors = {
            "SUCCESS": "\033[92m",  # Green
            "ERROR": "\033[91m",    # Red
            "INFO": "\033[94m",     # Blue
            "TEST": "\033[95m",     # Magenta
            "RESPONSE": "\033[93m", # Yellow
            "RESET": "\033[0m"
        }
        color_code = colors.get(level, colors["RESET"])
        reset = colors["RESET"]
        print(f"{color_code}[{level}]{reset} {timestamp} - {message}")
    else:
        print(f"[{level}] {timestamp} - {message}")


def log_success(message: str) -> None:
    log("SUCCESS", message)


def log_error(message: str) -> None:
    log("ERROR", message)


def log_info(message: str) -> None:
    log("INFO", message)


def log_test(message: str) -> None:
    log("TEST", message)


def log_response(message: str) -> None:
    log("RESPONSE", message)


def pretty_json(data: Any) -> str:
    """Format JSON with indentation."""
    return json.dumps(data, indent=2, ensure_ascii=False)


class AIChatTester:
    """Test client for AI chat endpoints."""
    
    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
    
    def test_health(self) -> bool:
        """Test if server is reachable."""
        try:
            response = self.session.get(
                f"{self.base_url}/health",
                timeout=5
            )
            if response.status_code == 200:
                log_success(f"Server healthy: {self.base_url}")
                return True
            else:
                log_error(f"Server unhealthy: HTTP {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Server unreachable: {e}")
            return False
    
    def test_list_projects(self) -> bool:
        """Test /projects endpoint to get test data."""
        try:
            response = self.session.get(
                f"{self.base_url}/projects",
                timeout=10
            )
            if response.status_code == 200:
                projects = response.json()
                log_success(f"Found {len(projects)} projects")
                if projects:
                    log_info(f"Sample project: {projects[0].get('name')} (ID: {projects[0].get('id')})")
                return True
            else:
                log_error(f"Failed to list projects: HTTP {response.status_code}")
                return False
        except Exception as e:
            log_error(f"Failed to list projects: {e}")
            return False
    
    def chat(
        self,
        message: str,
        session_id: str = "test-session",
        active_project_id: Optional[int] = None,
        timeout: int = DEFAULT_TIMEOUT
    ) -> Optional[Dict]:
        """
        Test /api/ai/chat endpoint.
        
        Returns response dict or None on error.
        """
        url = f"{self.base_url}{API_PREFIX}/chat"
        
        payload = {
            "session_id": session_id,
            "message": message
        }
        
        if active_project_id:
            payload["active_project_id"] = active_project_id
        
        log_test(f"POST {url}")
        log_info(f"Message: {message}")
        log_info(f"Session: {session_id}")
        
        try:
            start = time.time()
            response = self.session.post(
                url,
                json=payload,
                timeout=timeout
            )
            elapsed = time.time() - start
            
            if response.status_code == 200:
                data = response.json()
                log_success(f"Response received ({elapsed:.2f}s)")
                log_response(pretty_json(data))
                return data
            else:
                log_error(f"Request failed: HTTP {response.status_code}")
                log_error(response.text)
                return None
                
        except requests.Timeout:
            log_error(f"Request timed out after {timeout}s")
            return None
        except Exception as e:
            log_error(f"Request failed: {e}")
            return None
    
    def selection(
        self,
        session_id: str,
        selection: str,
        intent: Dict[str, Any],
        timeout: int = DEFAULT_TIMEOUT
    ) -> Optional[Dict]:
        """
        Test /api/ai/selection endpoint.
        
        Args:
            selection: Selected project domain (string)
        
        Returns response dict or None on error.
        """
        url = f"{self.base_url}{API_PREFIX}/selection"
        
        payload = {
            "session_id": session_id,
            "selection": selection,
            "intent": intent
        }
        
        log_test(f"POST {url}")
        log_info(f"Selection: {selection}")
        log_info(f"Intent: {pretty_json(intent)}")
        
        try:
            start = time.time()
            response = self.session.post(
                url,
                json=payload,
                timeout=timeout
            )
            elapsed = time.time() - start
            
            if response.status_code == 200:
                data = response.json()
                log_success(f"Selection processed ({elapsed:.2f}s)")
                log_response(pretty_json(data))
                return data
            else:
                log_error(f"Request failed: HTTP {response.status_code}")
                log_error(response.text)
                return None
                
        except Exception as e:
            log_error(f"Request failed: {e}")
            return None
    
    def confirm(
        self,
        session_id: str,
        confirmed: bool,
        timeout: int = DEFAULT_TIMEOUT
    ) -> Optional[Dict]:
        """
        Test /api/ai/confirm endpoint.
        
        Args:
            confirmed: True to confirm, False to cancel
        
        Returns response dict or None on error.
        """
        url = f"{self.base_url}{API_PREFIX}/confirm"
        
        payload = {
            "session_id": session_id,
            "confirmed": confirmed
        }
        
        log_test(f"POST {url}")
        log_info(f"Confirmed: {confirmed}")
        
        try:
            start = time.time()
            response = self.session.post(
                url,
                json=payload,
                timeout=timeout
            )
            elapsed = time.time() - start
            
            if response.status_code == 200:
                data = response.json()
                log_success(f"Confirmation processed ({elapsed:.2f}s)")
                log_response(pretty_json(data))
                return data
            else:
                log_error(f"Request failed: HTTP {response.status_code}")
                log_error(response.text)
                return None
                
        except Exception as e:
            log_error(f"Request failed: {e}")
            return None
    
    def run_all_tests(self) -> Dict[str, bool]:
        """Run comprehensive test suite."""
        results = {}
        
        print()
        print("=" * 70)
        print(" AI CHAT ENDPOINT TEST SUITE")
        print("=" * 70)
        print()
        
        # Test 1: Server health
        log_test("TEST 1: Server Health Check")
        results["health"] = self.test_health()
        print()
        
        # Test 2: List projects
        log_test("TEST 2: List Projects (for test data)")
        results["list_projects"] = self.test_list_projects()
        print()
        
        # Test 3: Basic text conversation
        log_test("TEST 3: Basic Text Conversation")
        response = self.chat(
            message="hello, what can you help me with?",
            session_id="test-basic"
        )
        results["chat_text"] = response is not None and response.get("type") == "text"
        print()
        
        # Test 4: List projects via AI
        log_test("TEST 4: List Projects via AI")
        response = self.chat(
            message="show me all my projects",
            session_id="test-list"
        )
        results["chat_list"] = response is not None and response.get("type") == "execution"
        print()
        
        # Test 5: Non-existent project name (should trigger selection)
        log_test("TEST 5: Non-existent Project Name (Selection Flow)")
        response = self.chat(
            message="show logs for project myproject",  # Realistic name that doesn't exist
            session_id="test-selection-5"
        )
        results["chat_selection"] = response is not None and response.get("type") == "selection"
        print()
        
        # Test 6: Project status with active project
        log_test("TEST 6: Project Status with Active Project")
        response = self.chat(
            message="what's the status of my current project?",
            session_id="test-status",
            active_project_id=1
        )
        results["chat_status"] = response is not None
        print()
        
        # Test 7: Get logs
        log_test("TEST 7: Get Logs")
        response = self.chat(
            message="show me logs for project testapp",
            session_id="test-logs"
        )
        results["chat_logs"] = response is not None
        print()
        
        # Test 8: Dangerous operation (should trigger confirmation)
        log_test("TEST 8: Dangerous Operation (Confirmation Flow)")
        response = self.chat(
            message="stop all projects",
            session_id="test-confirm"
        )
        results["chat_confirmation"] = response is not None and response.get("type") == "confirmation"
        print()
        
        # Test 9: Selection endpoint
        log_test("TEST 9: Selection Endpoint")
        response = self.selection(
            session_id="test-selection",
            selection="thinkai-likrt6",
            intent={
                "tool": "start_project",
                "args": {
                    "project_id": "thinkai-likrt6"
                }
            }
        )
        results["selection_endpoint"] = response is not None
        print()
        
        # Test 10: Confirm endpoint
        log_test("TEST 10: Confirm Endpoint (Cancel)")
        response = self.confirm(
            session_id="test-confirm",
            confirmed=False
        )
        results["confirm_endpoint"] = response is not None
        print()
        
        # Print summary
        print()
        print("=" * 70)
        print(" TEST SUMMARY")
        print("=" * 70)
        
        for test_name, passed in results.items():
            status = "[PASS]" if passed else "[FAIL]"
            print(f"  {test_name:30} {status}")
        
        print()
        total = len(results)
        passed = sum(1 for v in results.values() if v)
        print(f"Total: {passed}/{total} tests passed")
        print("=" * 70)
        print()
        
        return results


def cmd_chat(args) -> int:
    """Handle chat command."""
    tester = AIChatTester(args.base_url)
    
    response = tester.chat(
        message=args.message,
        session_id=args.session_id,
        active_project_id=args.project_id,
        timeout=args.timeout
    )
    
    if args.json and response:
        print(pretty_json(response))
    
    return 0 if response else 1


def cmd_selection(args) -> int:
    """Handle selection command."""
    tester = AIChatTester(args.base_url)
    
    try:
        intent = json.loads(args.intent)
    except json.JSONDecodeError:
        log_error("Invalid JSON in intent parameter")
        return 1
    
    response = tester.selection(
        session_id=args.session_id,
        selection=args.selection,
        intent=intent,
        timeout=args.timeout
    )
    
    if args.json and response:
        print(pretty_json(response))
    
    return 0 if response else 1


def cmd_confirm(args) -> int:
    """Handle confirm command."""
    tester = AIChatTester(args.base_url)
    
    response = tester.confirm(
        session_id=args.session_id,
        confirmed=args.confirmed,
        timeout=args.timeout
    )
    
    if args.json and response:
        print(pretty_json(response))
    
    return 0 if response else 1


def cmd_test_all(args) -> int:
    """Handle test-all command."""
    tester = AIChatTester(args.base_url)
    results = tester.run_all_tests()
    
    # Return non-zero if any test failed
    all_passed = all(results.values())
    return 0 if all_passed else 1


def main():
    parser = argparse.ArgumentParser(
        description="AI Chat Endpoint Tester",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test basic conversation
  test_ai_chat chat "hello"
  
  # Test with active project
  test_ai_chat chat "status" --project-id 5
  
  # Test selection endpoint
  test_ai_chat selection --session-id "test" --selection "myproject" --intent '{"tool":"start_project","args":{"project_id":"myproject"}}'
  
  # Test confirmation endpoint
  test_ai_chat confirm --session-id "test" --confirmed True
  
  # Run all tests
  test_ai_chat test-all
  
  # Use custom base URL
  test_ai_chat test-all --base-url http://localhost:8002
        """
    )
    
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL for API (default: {DEFAULT_BASE_URL})"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Request timeout in seconds (default: {DEFAULT_TIMEOUT})"
    )
    
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON response"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Chat command
    chat_parser = subparsers.add_parser("chat", help="Test chat endpoint")
    chat_parser.add_argument("message", help="Message to send")
    chat_parser.add_argument("--session-id", default="test-session", help="Session ID")
    chat_parser.add_argument("--project-id", type=int, help="Active project ID")
    
    # Selection command
    selection_parser = subparsers.add_parser("selection", help="Test selection endpoint")
    selection_parser.add_argument("--session-id", required=True, help="Session ID")
    selection_parser.add_argument("--selection", required=True, help="Selected project domain")
    selection_parser.add_argument("--intent", required=True, help="Intent JSON string")
    
    # Confirm command
    confirm_parser = subparsers.add_parser("confirm", help="Test confirm endpoint")
    confirm_parser.add_argument("--session-id", required=True, help="Session ID")
    confirm_parser.add_argument("--confirmed", type=lambda x: x.lower() == "true", required=True, help="True to confirm, False to cancel")
    
    # Test-all command
    test_all_parser = subparsers.add_parser("test-all", help="Run all tests")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(0)
    
    if args.command == "chat":
        exit_code = cmd_chat(args)
    elif args.command == "selection":
        exit_code = cmd_selection(args)
    elif args.command == "confirm":
        exit_code = cmd_confirm(args)
    elif args.command == "test-all":
        exit_code = cmd_test_all(args)
    else:
        exit_code = 1
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
