#!/usr/bin/env python3
"""The PM brain of a dev cycle — LLM turns for intake and planning.

Two calls, both strict-JSON:
  1. intake_turn(history) → {ready: bool, questions: [...], missing: [...]}
  2. generate_plan(requirement) → {tasks: [...], dod: [...]}

Uses the platform's OpenRouter/z.ai client with reasoning_effort=medium.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("services.dev_cycles.chat_agent")


def _chat(system: str, user: str, max_tokens: int = 2000) -> str:
    """One LLM call — plain synchronous httpx (no event loops, thread-safe).

    Prefers the z.ai coding-plan endpoint (free quota) when ZAI_API_KEY is
    set; falls back to OpenRouter."""
    import httpx
    import os as _os

    zai = _os.getenv("ZAI_API_KEY", "").strip()
    if zai:
        url = "https://api.z.ai/api/coding/paas/v4/chat/completions"
        key = zai
        model = "glm-5.3-flash"
        headers = {"Authorization": f"Bearer {key}"}
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"
        key = _os.getenv("OPENROUTER_API_KEY", "")
        model = _os.getenv("OPENROUTER_MODEL", "z-ai/glm-5.3-flash")
        headers = {"Authorization": f"Bearer {key}"}
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    resp = httpx.post(url, json=body, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""


def _extract_json(text: str) -> Dict[str, Any]:
    """Parse the first JSON object from an LLM reply (tolerates fences/prose)."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            p = p.strip().removeprefix("json").strip()
            if p.startswith("{"):
                text = p
                break
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


# ── 1. Intake: clarify or ready ─────────────────────────────────────────

INTAKE_SYSTEM = """You are a senior product engineer gathering requirements to build a website.
You chat with the client to collect everything needed to plan the build.

Reply with ONLY a JSON object:
{
  "ready": false,
  "questions": ["at most 2 short, specific questions"],
  "missing": ["what's still unknown"]
}

Mark ready=true when you know: (a) site purpose, (b) the main pages or
sections, (c) key features/forms. Style, assets and copy can default
(dark/light, AI-written text) — prefer ready=true over more questions.
After TWO user replies, mark ready=true unless something critical is
truly unknown.

If the user attached assets (SVG/images), treat them as provided.
Never ask more than 2 questions per turn. Be pragmatic: reasonable defaults
beat interrogation."""


INTAKE_EXISTING_SYSTEM = """You are a senior engineer gathering change requirements for an EXISTING deployed website.
The client already has the site; they're telling you what to change or improve.

Reply with ONLY a JSON object:
{
  "ready": false,
  "questions": ["at most 2 short questions if truly ambiguous"],
  "missing": []
}

Mark ready=true as soon as you know WHAT to change and roughly HOW it should
look/work after the change. One clear instruction ("make the hero headline
say X", "add a pricing section", "change theme to dark") is usually enough.
Ask only if the change target is genuinely ambiguous."""


def intake_turn(history: List[Dict[str, str]], mode: str = "new") -> Dict[str, Any]:
    """Decide whether requirements are complete. Returns
    {ready, questions[], missing[]}. mode="existing" = change intake on a
    deployed site (much lower ready bar than full-site intake)."""
    convo = "\n".join(f"{m['role']}: {m['content'][:1500]}" for m in history[-14:])
    system = INTAKE_EXISTING_SYSTEM if mode == "existing" else INTAKE_SYSTEM
    raw = _chat(system, "Conversation so far:\n\n" + convo + "\n\nIs it ready to plan? JSON only.", 500)
    out = _extract_json(raw)
    ready = bool(out.get("ready"))
    questions = [str(q)[:300] for q in (out.get("questions") or [])][:2]
    # Tie-breaks: not-ready with no question = dead loop (ask default);
    # ready with questions = contradiction (trust ready).
    if not ready and not questions:
        questions = ["Anything specific about pages or style I should know? Otherwise I can use good defaults."]
    if ready and questions:
        questions = []
    return {
        "ready": ready,
        "questions": questions,
        "missing": [str(m)[:200] for m in (out.get("missing") or [])][:5],
    }


# ── 2. Plan: tasks + DoD ────────────────────────────────────────────────

PLAN_SYSTEM = """You are a senior engineer planning a website build as a task board.
Given the full requirement, produce ONLY a JSON object:

{
  "tasks": [
    {"title": "short task name", "description": "one clear instruction",
     "kind": "create" | "instruct"}
  ],
  "dod": [
    {"kind": "url_200", "params": {"path": "/"},
     "description": "site loads"},
    {"kind": "console_clean", "params": {}, "description": "no console errors"},
    {"kind": "dom_exists", "params": {"selector": "nav, header"},
     "description": "navigation present"},
    {"kind": "text_present", "params": {"selector": "h1", "text": "..."},
     "description": "hero headline"}
  ]
}

Rules:
- FIRST task is always kind="create" (the platform builds the site from the
  brief in its description — write that description as a complete build
  brief: pages, sections, style, forms, content instructions).
- Following tasks are kind="instruct" (chat edits: things the create-brief
  cannot guarantee, e.g. wiring a specific API, inserting provided SVG
  assets by name). Most plans need 0-2 of these. Omit if none.
- dod: 5-9 binary checks covering load, no console errors, and the key
  visible elements (nav, hero headline, contact form if requested).
  Only use kinds: url_200, console_clean, dom_exists, text_present.
- JSON only. No prose."""


PLAN_EXISTING_SYSTEM = """You are a senior engineer planning CHANGES to an existing deployed website.
The site already exists and is live. Produce ONLY a JSON object:

{
  "tasks": [
    {"title": "short task name", "description": "one clear instruction",
     "kind": "instruct"}
  ],
  "dod": [
    {"kind": "url_200", "params": {"path": "/"}, "description": "site loads"},
    {"kind": "console_clean", "params": {}, "description": "no console errors"},
    {"kind": "dom_exists", "params": {"selector": "..."}, "description": "..."},
    {"kind": "text_present", "params": {"selector": "...", "text": "..."}, "description": "..."}
  ]
}

Rules:
- ALL tasks are kind="instruct" (chat instructions to the build agent).
  NEVER produce a kind="create" task — the site already exists.
- Most plans need 1-2 tasks. Each description is ONE clear instruction.
- dod: 3-6 binary checks covering the change landing correctly plus site
  still loading clean. Only kinds: url_200, console_clean, dom_exists,
  text_present.
- JSON only."""


def generate_plan(requirement: str, mode: str = "new") -> Dict[str, Any]:
    if mode == "existing":
        raw = _chat(PLAN_EXISTING_SYSTEM,
                    f"Change requirement for the existing site:\n\n{requirement}\n\nProduce the task board JSON (instruct tasks only).",
                    2000)
    else:
        raw = _chat(PLAN_SYSTEM, f"Requirement:\n\n{requirement}\n\nProduce the task board JSON.", 2500)
    out = _extract_json(raw)
    tasks = out.get("tasks") or []
    dod = out.get("dod") or []
    if mode == "existing":
        # site already exists — strip any create tasks the model added anyway
        tasks = [t for t in tasks if t.get("kind") != "create"]
        if not tasks:
            tasks = [{"title": "Apply the changes", "description": requirement[:4000], "kind": "instruct"}]
    else:
        # sanity: first task must be create
        if tasks and tasks[0].get("kind") != "create":
            tasks.insert(0, {"title": "Build the site", "description": requirement[:4000], "kind": "create"})
        if not tasks:
            tasks = [{"title": "Build the site", "description": requirement[:4000], "kind": "create"}]
    valid_kinds = {"url_200", "console_clean", "dom_exists", "text_present"}
    dod = [d for d in dod if d.get("kind") in valid_kinds]
    if not dod:
        dod = [
            {"kind": "url_200", "params": {"path": "/"}, "description": "site loads"},
            {"kind": "console_clean", "params": {}, "description": "no console errors"},
        ]
    return {"tasks": tasks, "dod": dod}


# ── 3. Repair instruction writer ────────────────────────────────────────

REPAIR_SYSTEM = """You are a senior engineer writing a fix instruction for a website build.
Given the task, the check that failed, and the evidence, write ONE short
imperative instruction (2-4 sentences) for the build agent to fix it.
Reference the exact element/text. No JSON, just the instruction."""


def repair_instruction(task_title: str, failed_check: Dict[str, Any], evidence: str) -> str:
    user = (
        f"Task: {task_title}\n"
        f"Failed check: {failed_check.get('kind')} — {failed_check.get('description')}\n"
        f"Params: {json.dumps(failed_check.get('params') or {})}\n"
        f"Evidence: {evidence[:600]}\n\nWrite the fix instruction."
    )
    return _chat(REPAIR_SYSTEM, user, 400).strip()
