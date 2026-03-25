#!/usr/bin/env python3
"""
AI Chat Endpoint Tester

Test all AI chat endpoints with comprehensive scenarios.
Can run from anywhere with configurable base URL.

Usage:
    test_ai_chat chat "list my projects"
    test_ai_chat chat "start project testapp"
    test_ai_chat chat "switch to thinkai-likrt6"
    test_ai_chat chat "which project am I using?"
    test_ai_chat selection --session-id "user-123" --intent '{"tool":"start_project","args":{"project_id":"testapp"}}'
    test_ai_chat confirm --session-id "user-123" --action "confirm"
    test_ai_chat test-all
    test_ai_chat test-tools

Tests Covered:
    - Infrastructure: health, list_projects
    - Basic Chat: text conversation, list via AI
    - Project Operations: start, stop, restart, status, logs
    - Context Management: set_active_project, get_active_project, clear_active_project
    - Selection Flow: non-existent project, selection endpoint
    - Confirmation Flow: dangerous operations, confirm/cancel
    - Edge Cases: empty message, long message, special chars, session persistence
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
        
        # ==========================================
        # SECTION 1: Infrastructure Tests
        # ==========================================
        print("--- SECTION 1: Infrastructure ---")
        print()
        
        # Test 1: Server health
        log_test("TEST 1.1: Server Health Check")
        results["health"] = self.test_health()
        print()
        
        # Test 2: List projects
        log_test("TEST 1.2: List Projects (for test data)")
        results["list_projects"] = self.test_list_projects()
        print()
        
        # ==========================================
        # SECTION 2: Basic Chat Tests
        # ==========================================
        print("--- SECTION 2: Basic Chat ---")
        print()
        
        # Test 3: Basic text conversation
        log_test("TEST 2.1: Basic Text Conversation")
        response = self.chat(
            message="hello, what can you help me with?",
            session_id="test-basic"
        )
        results["chat_text"] = response is not None and response.get("type") == "text"
        print()
        
        # Test 4: List projects via AI
        log_test("TEST 2.2: List Projects via AI (list_projects)")
        response = self.chat(
            message="show me all my projects",
            session_id="test-list"
        )
        results["tool_list_projects"] = response is not None and response.get("type") == "execution"
        print()
        
        # ==========================================
        # SECTION 3: Project Operations (Auto-Execute)
        # ==========================================
        print("--- SECTION 3: Project Operations (Auto-Execute) ---")
        print()
        
        # Test 5: Start project
        log_test("TEST 3.1: Start Project (start_project)")
        response = self.chat(
            message="start project thinkai-likrt6",
            session_id="test-start"
        )
        results["tool_start_project"] = response is not None
        print()
        
        # Test 6: Stop project
        log_test("TEST 3.2: Stop Project (stop_project)")
        response = self.chat(
            message="stop project thinkai-likrt6",
            session_id="test-stop"
        )
        results["tool_stop_project"] = response is not None
        print()
        
        # Test 7: Restart project
        log_test("TEST 3.3: Restart Project (restart_project)")
        response = self.chat(
            message="restart project thinkai-likrt6",
            session_id="test-restart"
        )
        results["tool_restart_project"] = response is not None
        print()
        
        # Test 8: Project status
        log_test("TEST 3.4: Project Status (project_status)")
        response = self.chat(
            message="what's the status of project thinkai-likrt6?",
            session_id="test-status"
        )
        results["tool_project_status"] = response is not None
        print()
        
        # Test 9: Get logs
        log_test("TEST 3.5: Get Logs (get_logs)")
        response = self.chat(
            message="show me logs for project thinkai-likrt6",
            session_id="test-logs"
        )
        results["tool_get_logs"] = response is not None
        print()
        
        # ==========================================
        # SECTION 4: Context Management Tools (NEW)
        # ==========================================
        print("--- SECTION 4: Context Management Tools (NEW) ---")
        print()
        
        # Test 10: Set active project
        log_test("TEST 4.1: Set Active Project (set_active_project)")
        response = self.chat(
            message="switch to project thinkai-likrt6",
            session_id="test-context-switch"
        )
        results["tool_set_active_project"] = response is not None and response.get("type") in ["execution", "text"]
        print()
        
        # Test 11: Get active project
        log_test("TEST 4.2: Get Active Project (get_active_project)")
        response = self.chat(
            message="which project am I using?",
            session_id="test-context-switch"  # Same session to get the set project
        )
        results["tool_get_active_project"] = response is not None
        print()
        
        # Test 12: Clear active project
        log_test("TEST 4.3: Clear Active Project (clear_active_project)")
        response = self.chat(
            message="clear project context",
            session_id="test-context-switch"  # Same session
        )
        results["tool_clear_active_project"] = response is not None and response.get("type") in ["execution", "text"]
        print()
        
        # Test 13: Verify cleared context
        log_test("TEST 4.4: Verify Cleared Context")
        response = self.chat(
            message="what's my current project?",
            session_id="test-context-switch"
        )
        results["context_cleared_verify"] = response is not None
        print()
        
        # ==========================================
        # SECTION 5: Selection Flow
        # ==========================================
        print("--- SECTION 5: Selection Flow ---")
        print()
        
        # Test 14: Non-existent project name (should trigger selection)
        log_test("TEST 5.1: Non-existent Project (Selection Flow)")
        response = self.chat(
            message="show logs for project nonexistantproject123",
            session_id="test-selection-flow"
        )
        results["selection_triggered"] = response is not None and response.get("type") == "selection"
        print()
        
        # Test 15: Selection endpoint
        log_test("TEST 5.2: Selection Endpoint")
        response = self.selection(
            session_id="test-selection-flow",
            selection="thinkai-likrt6",
            intent={
                "tool": "get_logs",
                "args": {
                    "project_id": "thinkai-likrt6"
                }
            }
        )
        results["selection_endpoint"] = response is not None
        print()
        
        # ==========================================
        # SECTION 6: Confirmation Flow
        # ==========================================
        print("--- SECTION 6: Confirmation Flow ---")
        print()
        
        # Test 16: Dangerous operation (stop all - should trigger confirmation)
        log_test("TEST 6.1: Stop All Projects (Confirmation Required)")
        response = self.chat(
            message="stop all projects",
            session_id="test-confirm-flow"
        )
        results["confirmation_triggered"] = response is not None and response.get("type") == "confirmation"
        print()
        
        # Test 17: Confirm endpoint (cancel)
        log_test("TEST 6.2: Confirm Endpoint (Cancel)")
        response = self.confirm(
            session_id="test-confirm-flow",
            confirmed=False
        )
        results["confirm_cancel"] = response is not None
        print()
        
        # Test 18: Delete project (confirmation required)
        log_test("TEST 6.3: Delete Project (Confirmation Required)")
        response = self.chat(
            message="delete project testproject123",
            session_id="test-delete-flow"
        )
        results["delete_confirmation"] = response is not None
        print()
        
        # ==========================================
        # SECTION 7: Edge Cases
        # ==========================================
        print("--- SECTION 7: Edge Cases ---")
        print()
        
        # Test 19: Empty message
        log_test("TEST 7.1: Empty Message Handling")
        response = self.chat(
            message="",
            session_id="test-empty"
        )
        results["empty_message"] = response is not None  # Should return error gracefully
        print()
        
        # Test 20: Very long message
        log_test("TEST 7.2: Long Message Handling")
        response = self.chat(
            message="start project thinkai-likrt6 " + "and " * 100,
            session_id="test-long"
        )
        results["long_message"] = response is not None
        print()
        
        # Test 21: Special characters
        log_test("TEST 7.3: Special Characters")
        response = self.chat(
            message="show status for project test-project_123",
            session_id="test-special"
        )
        results["special_chars"] = response is not None
        print()
        
        # Test 22: Session persistence
        log_test("TEST 7.4: Session Persistence")
        # Set project in session
        self.chat(
            message="switch to thinkai-likrt6",
            session_id="test-persist"
        )
        # Check if session remembers
        response = self.chat(
            message="restart it",
            session_id="test-persist"
        )
        results["session_persistence"] = response is not None
        print()
        
        # Print summary
        print()
        print("=" * 70)
        print(" TEST SUMMARY")
        print("=" * 70)
        
        # Group results by section
        sections = {
            "Infrastructure": ["health", "list_projects"],
            "Basic Chat": ["chat_text", "tool_list_projects"],
            "Project Operations": ["tool_start_project", "tool_stop_project", "tool_restart_project", "tool_project_status", "tool_get_logs"],
            "Context Management": ["tool_set_active_project", "tool_get_active_project", "tool_clear_active_project", "context_cleared_verify"],
            "Selection Flow": ["selection_triggered", "selection_endpoint"],
            "Confirmation Flow": ["confirmation_triggered", "confirm_cancel", "delete_confirmation"],
            "Edge Cases": ["empty_message", "long_message", "special_chars", "session_persistence"]
        }
        
        for section, tests in sections.items():
            print(f"\n  {section}:")
            for test_name in tests:
                if test_name in results:
                    passed = results[test_name]
                    status = "[PASS]" if passed else "[FAIL]"
                    print(f"    {test_name:35} {status}")
        
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


def cmd_test_tools(args) -> int:
    """Test specific tools individually."""
    tester = AIChatTester(args.base_url)
    results = {}
    
    print()
    print("=" * 70)
    print(" TOOL-SPECIFIC TEST SUITE")
    print("=" * 70)
    print()
    
    tool_tests = [
        # Context Management Tools (NEW)
        ("set_active_project", "switch to thinkai-likrt6", "test-tool-set"),
        ("get_active_project", "which project am I using?", "test-tool-get"),
        ("clear_active_project", "clear project context", "test-tool-clear"),
        
        # Auto-Execute Tools
        ("list_projects", "list all projects", "test-tool-list"),
        ("project_status", "status of thinkai-likrt6", "test-tool-status"),
        ("get_logs", "logs for thinkai-likrt6", "test-tool-logs"),
        ("start_project", "start thinkai-likrt6", "test-tool-start"),
        ("stop_project", "stop thinkai-likrt6", "test-tool-stop"),
        ("restart_project", "restart thinkai-likrt6", "test-tool-restart"),
    ]
    
    for tool_name, message, session_id in tool_tests:
        log_test(f"Testing: {tool_name}")
        response = tester.chat(message=message, session_id=session_id)
        results[tool_name] = response is not None
        print()
    
    # Print summary
    print()
    print("=" * 70)
    print(" TOOL TEST SUMMARY")
    print("=" * 70)
    
    for tool_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {tool_name:30} {status}")
    
    print()
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"Total: {passed}/{total} tools tested successfully")
    print("=" * 70)
    print()
    
    return 0 if all(results.values()) else 1


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
  
  # Test context management
  test_ai_chat chat "switch to thinkai-likrt6"
  test_ai_chat chat "which project am I using?"
  test_ai_chat chat "clear project context"
  
  # Test selection endpoint
  test_ai_chat selection --session-id "test" --selection "myproject" --intent '{"tool":"start_project","args":{"project_id":"myproject"}}'
  
  # Test confirmation endpoint
  test_ai_chat confirm --session-id "test" --confirmed True
  
  # Run all tests
  test_ai_chat test-all
  
  # Test specific tools
  test_ai_chat test-tools
  
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
    
    # Test-tools command
    test_tools_parser = subparsers.add_parser("test-tools", help="Test specific tools individually")
    
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
    elif args.command == "test-tools":
        exit_code = cmd_test_tools(args)
    else:
        exit_code = 1
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
