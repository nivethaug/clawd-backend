#!/usr/bin/env python3
"""Probe candidate models for the create-assistant before switching.

Run on MAIN (has OPENROUTER_API_KEY):
    cd /root/clawd-backend && venv/bin/python scripts/probe_create_models.py

For each candidate: one REAL request with the actual request_inputs tool
schema. Reports tool-call correctness, latency, and token cost. The
DreamSupport lesson: never assume a slug works — the account's
data-policy guardrails have blocked models before.
"""
import json
import os
import sys
import time

import httpx

CANDIDATES = [
    "z-ai/glm-4.7-flash",           # current create-chat default (2.2s in last probe)
    "z-ai/glm-5.3-flash",           # fallback
    "google/gemini-2.5-flash",      # fast output, controllable thinking
    "google/gemini-2.5-flash-lite", # cheapest
    "google/gemini-3-flash-preview",
]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "request_inputs",
        "description": "Pop input fields in the user's chat UI to collect values.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string",
                                    "enum": ["EMAIL_TO", "TELEGRAM_CHAT_ID",
                                             "TELEGRAM_BOT_TOKEN", "DISCORD_WEBHOOK_URL"]},
                            "label": {"type": "string"},
                            "question": {"type": "string"},
                        },
                        "required": ["key", "label", "question"],
                    },
                },
            },
            "required": ["items"],
        },
    },
}]

MESSAGES = [
    {"role": "system", "content":
        "You are a project creation assistant. The user wants hourly BTC "
        "price reports delivered by email. Collect the email address using "
        "the request_inputs tool. Respond in English."},
    {"role": "user", "content": "send btc price every 1h to email"},
]


def main() -> None:
    key = os.getenv("OPENROUTER_API_KEY") or ""
    if not key:
        for line in open(".env", encoding="utf-8"):
            if line.startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("No OPENROUTER_API_KEY found (env or .env)")

    print(f"{'model':32} {'ok':>3} {'tool':>5} {'keys':>28} {'latency':>8} {'in':>6} {'out':>5}")
    for model in CANDIDATES:
        row = {"model": model, "ok": "-", "tool": "-", "keys": "-", "lat": "-", "in": "-", "out": "-"}
        try:
            t0 = time.time()
            r = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": MESSAGES,
                    "tools": TOOLS,
                    "temperature": 0.3,
                    "max_tokens": 700,
                    "reasoning": {"effort": "low"} if "glm" in model or "z-ai/" in model
                                 else {"enabled": False},
                },
                timeout=60,
            )
            latency = time.time() - t0
            row["lat"] = f"{latency:.1f}s"
            if r.status_code != 200:
                row["ok"] = f"HTTP {r.status_code}"
                print(f"{row['model']:32} {row['ok']:>3}  {r.text[:100]}")
                continue
            data = r.json()
            msg = data["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            row["ok"] = "yes"
            if calls:
                row["tool"] = calls[0]["function"]["name"]
                try:
                    args = calls[0]["function"]["arguments"]
                    args = args if isinstance(args, dict) else json.loads(args or "{}")
                    keys = [i.get("key") for i in args.get("items", [])]
                    row["keys"] = ",".join(keys) or "(none)"
                except Exception as e:
                    row["keys"] = f"parse-fail:{type(e).__name__}"
            else:
                row["tool"] = "none"
            u = data.get("usage", {})
            row["in"] = u.get("prompt_tokens", "-")
            row["out"] = u.get("completion_tokens", "-")
        except Exception as e:
            row["ok"] = f"ERR {type(e).__name__}"
        print(f"{row['model']:32} {row['ok']:>3} {row['tool']:>5} {row['keys']:>28} "
              f"{row['lat']:>8} {row['in']:>6} {row['out']:>5}")

    print("\nPick: tool called with the right key + lowest latency + lowest out tokens.")
    print("Switch: set PROMPT_ASSISTANT_MODEL=<model> in main .env, restart main API.")


if __name__ == "__main__":
    main()
