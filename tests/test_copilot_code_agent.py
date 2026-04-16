#!/usr/bin/env python3
"""
Smoke test for CopilotCodeAgent.

Usage:
    python3 tests/test_copilot_code_agent.py
    python3 tests/test_copilot_code_agent.py --prompt "List files here" --timeout 180
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Add repo root to import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot_code_agent import CopilotCodeAgent, configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test CopilotCodeAgent")
    parser.add_argument(
        "--repo-path",
        default=os.getcwd(),
        help="Repository/workspace path for CopilotCodeAgent (default: current directory)",
    )
    parser.add_argument(
        "--prompt",
        default="Give a one-sentence summary of this repository.",
        help="Prompt to send to Copilot CLI",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds for the query (default: 120)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


async def run_smoke_test(repo_path: str, prompt: str, timeout: float, verbose: bool) -> int:
    if verbose:
        configure_logging()

    chunks: list[str] = []
    progress_updates: list[str] = []

    def on_text(text: str) -> None:
        chunks.append(text)

    def on_progress(message: str) -> None:
        progress_updates.append(message)

    try:
        async with CopilotCodeAgent(
            repo_path=repo_path,
            on_text=on_text,
            on_progress=on_progress,
        ) as agent:
            response = await agent.query(prompt, timeout=timeout)

        if not response:
            print("FAIL: CopilotCodeAgent returned empty response.")
            print(f"stream_chunks={len(chunks)} progress_updates={len(progress_updates)}")
            return 1

        print("PASS: CopilotCodeAgent query succeeded.")
        print(f"stream_chunks={len(chunks)} progress_updates={len(progress_updates)}")
        print(f"response={response[:500]}")
        return 0
    except Exception as exc:
        print(f"FAIL: CopilotCodeAgent query failed: {exc}")
        return 1


def main() -> int:
    args = parse_args()
    return asyncio.run(
        run_smoke_test(
            repo_path=args.repo_path,
            prompt=args.prompt,
            timeout=args.timeout,
            verbose=args.verbose,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
