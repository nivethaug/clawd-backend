#!/usr/bin/env python3
"""
Real-world test for ClaudeCodeAgent with naturescape project.

This test runs against the actual project at:
/root/dreampilot/projects/website/992_naturescape_20260321_065048

It tests:
- Frontend (React/TypeScript/Vite)
- Backend (Python/FastAPI)
- File operations
- Code generation
- Multi-turn queries
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_code_agent import ClaudeCodeAgent, claude_code_agent, configure_logging


# Project path on server
PROJECT_PATH = "/root/dreampilot/projects/website/992_naturescape_20260321_065048"

# Fallback for local testing
LOCAL_FALLBACK = r"D:\openclawbackend\clawd-backend\templates\blank-template"


def get_project_path() -> str:
    """Get the project path, using server path or local fallback."""
    if Path(PROJECT_PATH).exists():
        print(f"Using server project: {PROJECT_PATH}")
        return PROJECT_PATH
    elif Path(LOCAL_FALLBACK).exists():
        print(f"Using local fallback: {LOCAL_FALLBACK}")
        return LOCAL_FALLBACK
    else:
        # Use current directory
        print(f"Using current directory: {os.getcwd()}")
        return os.getcwd()


async def test_analyze_project_structure():
    """Test: Analyze the project structure (frontend + backend)."""
    print("\n" + "=" * 70)
    print("TEST 1: Analyze Project Structure")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        # Query 1: List project structure
        print("\n[Query] What is the structure of this project?")
        response = await agent.query(
            "List the directory structure of this project. "
            "Identify if it has frontend and backend folders. "
            "What framework is each using?"
        )
        if response:
            print(f"[Response]\n{response}\n")
        else:
            print("[Response] No response received")


async def test_backend_analysis():
    """Test: Analyze backend Python code."""
    print("\n" + "=" * 70)
    print("TEST 2: Backend Analysis")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        # Query: Analyze backend
        print("\n[Query] Analyze the backend structure")
        response = await agent.query(
            "Look at the backend folder. "
            "What Python framework is used? "
            "List the main routes and services."
        )
        if response:
            print(f"[Response]\n{response}\n")


async def test_frontend_analysis():
    """Test: Analyze frontend React code."""
    print("\n" + "=" * 70)
    print("TEST 3: Frontend Analysis")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        # Query: Analyze frontend
        print("\n[Query] Analyze the frontend structure")
        response = await agent.query(
            "Look at the frontend/src folder. "
            "What React components exist? "
            "What styling approach is used (Tailwind, CSS modules, etc)?"
        )
        if response:
            print(f"[Response]\n{response}\n")


async def test_create_component():
    """Test: Create a new React component."""
    print("\n" + "=" * 70)
    print("TEST 4: Create React Component")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        # Query: Create a simple component
        print("\n[Query] Create a test component")
        response = await agent.query(
            "Create a simple React component called TestComponent.tsx in frontend/src/components/ "
            "that displays 'Hello from Claude!' with Tailwind styling. "
            "Include proper TypeScript types."
        )
        if response:
            print(f"[Response]\n{response}\n")


async def test_create_api_endpoint():
    """Test: Create a new backend API endpoint."""
    print("\n" + "=" * 70)
    print("TEST 5: Create API Endpoint")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        # Query: Create API endpoint
        print("\n[Query] Create a health check endpoint")
        response = await agent.query(
            "Create a simple health check endpoint in the backend "
            "that returns {\"status\": \"healthy\", \"timestamp\": <current_time>}. "
            "Add it to the routes folder."
        )
        if response:
            print(f"[Response]\n{response}\n")


async def test_multi_turn_conversation():
    """Test: Multi-turn conversation."""
    print("\n" + "=" * 70)
    print("TEST 6: Multi-turn Conversation")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        queries = [
            "What is the main entry point of the backend?",
            "What database is being used, if any?",
            "List all environment variables used in the project.",
        ]

        for i, query in enumerate(queries, 1):
            print(f"\n[Query {i}] {query}")
            response = await agent.query(query)
            if response:
                print(f"[Response {i}]\n{response[:300]}{'...' if len(response) > 300 else ''}\n")
            print("-" * 50)


async def test_code_review():
    """Test: Code review functionality."""
    print("\n" + "=" * 70)
    print("TEST 7: Code Review")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        print("\n[Query] Review the main.py file")
        response = await agent.query(
            "Review the backend/main.py file. "
            "Suggest 3 improvements for code quality, security, or performance."
        )
        if response:
            print(f"[Response]\n{response}\n")


async def test_streaming_with_callback():
    """Test: Streaming response with callback."""
    print("\n" + "=" * 70)
    print("TEST 8: Streaming with Callback")
    print("=" * 70)

    project_path = get_project_path()

    chunks = []

    def on_chunk(text: str):
        chunks.append(text)
        print(f"  ▸ {text}", end="", flush=True)

    async with ClaudeCodeAgent(project_path, on_text=on_chunk) as agent:
        print("\n[Query] Generate a project summary (streaming)")
        response = await agent.query(
            "Provide a 3-sentence summary of this project's purpose and tech stack."
        )
        print()  # Newline after streaming
        print(f"\n[Total chunks received: {len(chunks)}]")
        if response:
            print(f"[Final response: {response}]")


async def test_error_handling():
    """Test: Error handling with invalid request."""
    print("\n" + "=" * 70)
    print("TEST 9: Error Handling")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        print("\n[Query] Request to access non-existent file")
        response = await agent.query(
            "Read the file /nonexistent/path/to/file.txt and summarize it."
        )
        if response:
            print(f"[Response]\n{response}\n")


async def run_all_tests():
    """Run all tests with timing."""
    print("\n" + "=" * 70)
    print("ClaudeCodeAgent - Real Project Test Suite")
    print("=" * 70)
    print(f"Project: {get_project_path()}")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    tests = [
        ("Analyze Project Structure", test_analyze_project_structure),
        ("Backend Analysis", test_backend_analysis),
        ("Frontend Analysis", test_frontend_analysis),
        ("Create React Component", test_create_component),
        ("Create API Endpoint", test_create_api_endpoint),
        ("Multi-turn Conversation", test_multi_turn_conversation),
        ("Code Review", test_code_review),
        ("Streaming with Callback", test_streaming_with_callback),
        ("Error Handling", test_error_handling),
    ]

    results = []

    for name, test_func in tests:
        start_time = datetime.now()
        try:
            await test_func()
            elapsed = (datetime.now() - start_time).total_seconds()
            results.append((name, "✓ PASS", elapsed))
            print(f"\n✓ {name} completed in {elapsed:.2f}s")
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            results.append((name, f"✗ FAIL: {e}", elapsed))
            print(f"\n✗ {name} failed: {e}")

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, status, _ in results if "PASS" in status)
    total = len(results)

    for name, status, elapsed in results:
        print(f"  {status} | {name} ({elapsed:.2f}s)")

    print("-" * 70)
    print(f"Total: {passed}/{total} passed")
    print(f"Finished: {datetime.now().isoformat()}")
    print("=" * 70)


async def quick_test():
    """Quick single test for fast verification."""
    print("\n" + "=" * 70)
    print("QUICK TEST")
    print("=" * 70)

    project_path = get_project_path()

    async with ClaudeCodeAgent(project_path) as agent:
        print(f"\nProject: {project_path}")
        print("[Query] What framework is this project using?")
        response = await agent.query("What framework is this project using? Answer in one sentence.")
        print(f"[Response] {response}")
        print("\n✓ Quick test passed!")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test ClaudeCodeAgent with real project")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--quick", action="store_true", help="Run quick test only")
    parser.add_argument("--log-file", type=str, help="Log to file")

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.debug else logging.INFO
    configure_logging(level=level, log_file=args.log_file)

    # Run tests
    if args.quick:
        asyncio.run(quick_test())
    else:
        asyncio.run(run_all_tests())
