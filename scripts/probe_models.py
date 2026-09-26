#!/usr/bin/env python3
"""Compare create-chat candidate models on OpenRouter: speed + tool-calling + cost.

For each model: 3 rounds of
  (a) STREAMED simple completion  -> time-to-first-token (TTFT)
  (b) TOOL-FORCED call            -> does it emit a proper tool_call? total latency
      (the actual bar that killed glm-4.7-flash in create chat)

Run on a VPS that has the backend .env (OPENROUTER_API_KEY):

    cd /root/clawd-backend && git pull
    venv/bin/python scripts/probe_models.py                 # default shortlist
    venv/bin/python scripts/probe_models.py qwen/qwen3.7-flash deepseek/deepseek-v4-flash

Cost per call comes from OpenRouter's own usage reporting in the response.
"""

import json
import statistics
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
DEFAULT_MODELS = [
    "z-ai/glm-5.3-flash",
    "qwen/qwen3.7-flash",
    "deepseek/deepseek-v4.1-flash",
    "deepseek/deepseek-v4-flash",
    "google/gemini-2.5-flash-lite",
    "bytedance-seed/seed-1.6-flash",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "request_inputs",
            "description": "Ask the user for missing details before building their project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One clear question per missing detail.",
                    }
                },
                "required": ["questions"],
            },
        },
    }
]

TOOL_PROMPT = (
    "You are a project creation assistant. The user said: 'make me a bot'. "
    "You are missing required details (which platform, what the bot should do). "
    "Call the request_inputs tool with one or two concrete questions."
)


def load_key():
    import os
    for line in (REPO / ".env").read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            os.environ["OPENROUTER_API_KEY"] = line.split("=", 1)[1].strip()
            break
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        sys.exit("OPENROUTER_API_KEY not found in .env or environment")
    return key


def probe(model: str, key: str):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    ttfts = []
    tool_ok = 0
    tool_lat = []
    cost = 0.0

    for rnd in range(3):
        # (a) TTFT via streaming
        try:
            t0 = time.perf_counter()
            first = None
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
                "max_tokens": 8,
                "stream": True,
            }
            r = requests.post(url, headers={**headers}, json=payload, stream=True, timeout=45)
            for line in r.iter_lines():
                if line and line.startswith(b"data: ") and first is None:
                    first = time.perf_counter() - t0
                    if line.strip() == b"data: [DONE]":
                        first = None  # empty stream, don't count
                        break
            if first:
                ttfts.append(first)
        except Exception:
            pass

        # (b) tool-forced call
        try:
            t0 = time.perf_counter()
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": TOOL_PROMPT}],
                "tools": TOOLS,
                "tool_choice": "auto",
                "max_tokens": 300,
            }
            r = requests.post(url, headers=headers, json=payload, timeout=60)
            body = r.json()
            msg = (body.get("choices") or [{}])[0].get("message", {})
            if msg.get("tool_calls"):
                tool_ok += 1
                tool_lat.append(time.perf_counter() - t0)
            cost += float((body.get("usage") or {}).get("cost") or 0)
        except Exception:
            pass

    return ttfts, tool_ok, tool_lat, cost


def main():
    models = sys.argv[1:] or DEFAULT_MODELS
    key = load_key()
    print(f"{'model':<36}{'TTFT med':>9}{'tool ok':>9}{'tool lat':>10}{'cost/run':>10}")
    print("-" * 76)
    for m in models:
        ttfts, tool_ok, tool_lat, cost = probe(m, key)
        ttft = f"{statistics.median(ttfts)*1000:.0f}ms" if ttfts else "FAIL"
        tok = f"{tool_ok}/3"
        tlat = f"{statistics.median(tool_lat):.2f}s" if tool_lat else "-"
        c = f"${cost/max(1,len(tool_lat)+ (3-tool_ok)*0 + 3):.6f}" if cost else "$0"
        print(f"{m:<36}{ttft:>9}{tok:>9}{tlat:>10}{c:>10}")


if __name__ == "__main__":
    main()
