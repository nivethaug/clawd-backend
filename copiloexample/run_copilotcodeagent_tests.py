#!/usr/bin/env python3
"""
Simple CopilotCodeAgent test runner.

Run:
    python3 copiloexample/run_copilotcodeagent_tests.py [--interactive] [--stream] [--verbose]
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Allow importing from repository root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copilot_code_agent import CopilotCodeAgent, configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run CopilotCodeAgent example tests")
    parser.add_argument(
        "--repo-path",
        default=str(Path(__file__).resolve().parent.parent),
        help="Workspace path passed to CopilotCodeAgent",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Per-query timeout in seconds",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable agent logging",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Print streamed agent output and progress messages live",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode: prompt for queries from terminal",
    )
    return parser.parse_args()


async def run_tests(repo_path: str, timeout: float, stream: bool, interactive: bool) -> int:
    streamed_chunks: list[str] = []
    progress_events: list[str] = []
    current_test = 0

    def on_text(text: str) -> None:
        streamed_chunks.append(text)
        if stream:
            print(f"[TEST {current_test}] STREAM: {text}", flush=True)

    def on_progress(message: str) -> None:
        progress_events.append(message)
        if stream:
            print(f"[TEST {current_test}] PROGRESS: {message}", flush=True)

    print(f"Running CopilotCodeAgent tests in: {repo_path}")
    async with CopilotCodeAgent(
        repo_path=repo_path,
        on_text=on_text,
        on_progress=on_progress,
    ) as agent:
        if interactive:
            print("Interactive mode: Enter prompts (type 'quit' to exit)")
            idx = 0
            while True:
                try:
                    prompt = input("Prompt: ").strip()
                    if prompt.lower() in ('quit', 'exit', 'q'):
                        break
                    if not prompt:
                        print("Empty prompt, try again.")
                        continue
                    idx += 1
                    current_test = idx
                    print(f"\n[TEST {idx}] Prompt: {prompt}")
                    response = await agent.query(prompt, timeout=timeout)
                    if not response:
                        print(f"[TEST {idx}] FAIL: empty response")
                        return 1
                    print(f"[TEST {idx}] PASS: {response[:300]}")
                except (EOFError, KeyboardInterrupt):
                    print("\nExiting interactive mode.")
                    break
        else:
            test_prompts = [
                "Give a one-sentence summary of this repository.",
                "List 5 key Python modules in this repository and their purpose in one line each.",
                "What is the main FastAPI entry file in this repo?",
            ]
            for idx, prompt in enumerate(test_prompts, start=1):
                current_test = idx
                print(f"\n[TEST {idx}] Prompt: {prompt}")
                response = await agent.query(prompt, timeout=timeout)
                if not response:
                    print(f"[TEST {idx}] FAIL: empty response")
                    return 1
                print(f"[TEST {idx}] PASS: {response[:300]}")

    print(f"\nDone. Stream chunks: {len(streamed_chunks)}, Progress events: {len(progress_events)}")
    return 0


def main() -> int:
    args = parse_args()
    if args.verbose:
        configure_logging()
    return asyncio.run(run_tests(args.repo_path, args.timeout, args.stream, args.interactive))


if __name__ == "__main__":
    raise SystemExit(main())
