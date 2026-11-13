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
from typing import Any, Dict, List, Optional

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
  "ready": true,
  "questions": [],
  "missing": []
}

Mark ready=true on the FIRST message whenever the kind of site is stated or
can be inferred (landing page, blog, portfolio, shop, docs, dashboard,
restaurant/business site, ...). Pages, sections, style, colours, copy and
images all have good defaults — never ask about them.

Mark ready=false ONLY when you cannot tell what the site is for (e.g. "make
me a website", "hi"). Then ask exactly ONE short question in "questions".
After the client has replied to a question, always mark ready=true.

Reasonable defaults beat interrogation."""


INTAKE_EXISTING_SYSTEM = """You are a senior engineer gathering change requirements for an EXISTING deployed website.
The client already has the site; they're telling you what to change or improve.

Reply with ONLY a JSON object:
{
  "ready": false,
  "questions": ["ONE short question, only if truly ambiguous"],
  "missing": []
}

Mark ready=true as soon as you know WHAT to change. One clear instruction
("make the hero headline say X", "add a pricing section", "change theme to
dark") is enough — pick sensible defaults for how it should look.
Ask (one question, once) only if you cannot tell what to change."""


def intake_turn(history: List[Dict[str, str]], mode: str = "new") -> Dict[str, Any]:
    """Decide whether requirements are complete. Returns
    {ready, questions[], missing[]}. mode="existing" = change intake on a
    deployed site (much lower ready bar than full-site intake)."""
    convo = "\n".join(f"{m['role']}: {m['content'][:1500]}" for m in history[-14:])
    system = INTAKE_EXISTING_SYSTEM if mode == "existing" else INTAKE_SYSTEM
    try:
        raw = _chat(system, "Conversation so far:\n\n" + convo + "\n\nIs it ready to plan? JSON only.", 500)
    except Exception as exc:
        # LLM down must not leave the user without a reply — fall through
        # to the tie-break below (defaults or one plain question).
        logger.warning("[INTAKE] LLM call failed: %s", exc)
        raw = ""
    out = _extract_json(raw)
    ready = bool(out.get("ready"))
    questions = [str(q)[:300] for q in (out.get("questions") or [])][:1]
    # Tie-breaks: not-ready with no question used to repeat a canned
    # question forever. Now: enough words from the user → go with
    # defaults; otherwise ask one plain question. ready with questions =
    # contradiction (trust ready).
    if not ready and not questions:
        user_words = sum(len(m["content"].split()) for m in history if m["role"] == "user")
        if user_words >= 4:
            ready = True
        elif mode == "existing":
            questions = ["What would you like me to change on the site?"]
        else:
            questions = ["What would you like to build? One sentence is enough."]
    if ready and questions:
        questions = []
    return {
        "ready": ready,
        "questions": questions,
        "missing": [str(m)[:200] for m in (out.get("missing") or [])][:5],
    }


# ── 2. Plan: tasks + DoD ────────────────────────────────────────────────

# The DoD is written BEFORE the site exists, so a check must never depend
# on copy or markup the planner guessed — the builder writes its own, and a
# guessed headline/class then shows up as a false warning on a clean build.
_DOD_RULES = """- Only use kinds: url_200, console_clean, dom_exists, text_present.
- Always include one url_200 (path "/") and one console_clean.
- Selectors: plain semantic tags ONLY (nav, header, main, h1, form, footer,
  img, button, a[href^="mailto:"]). NEVER class names, ids or data-attributes.
- text_present: ONLY for text the client literally gave you (their brand
  name, an exact headline they wrote). That exact text must also appear
  word-for-word in a task description as required copy. If the client gave
  no exact text, use dom_exists instead. Never invent copy to check.
- Each check "description" is a short plain noun phrase a non-technical
  client understands ("contact form", "main heading", "pricing section")."""

VALID_DOD_KINDS = {"url_200", "console_clean", "dom_exists", "text_present"}
CORE_DOD_KINDS = ("url_200", "console_clean")
_DEFAULT_CORE = {
    "url_200": {"kind": "url_200", "params": {"path": "/"}, "description": "site loads"},
    "console_clean": {"kind": "console_clean", "params": {}, "description": "no console errors"},
}


def _sanitize_dod(dod: Any, fallback: Any = None) -> List[Dict[str, Any]]:
    """Keep only well-formed checks of known kinds and guarantee both core
    checks are present (taken from `fallback` DoD, else defaults)."""
    out: List[Dict[str, Any]] = []
    for d in dod if isinstance(dod, list) else []:
        if not isinstance(d, dict) or d.get("kind") not in VALID_DOD_KINDS:
            continue
        params = d.get("params") if isinstance(d.get("params"), dict) else {}
        item = {"kind": d["kind"], "params": params,
                "description": str(d.get("description") or d["kind"])[:120]}
        out.append(item)
    for kind in reversed(CORE_DOD_KINDS):
        if not any(d["kind"] == kind for d in out):
            prior = next((d for d in (fallback or []) if isinstance(d, dict) and d.get("kind") == kind), None)
            out.insert(0, dict(prior or _DEFAULT_CORE[kind]))
    return out[:12]

PLAN_SYSTEM = """You are a senior engineer planning a website build as a task board.
Given the full requirement, produce ONLY a JSON object:

{
  "tasks": [
    {"title": "short task name", "summary": "what the client gets, max 12 words",
     "description": "one clear instruction", "kind": "create" | "instruct"}
  ],
  "assumptions": ["up to 3 defaults you chose, e.g. 'light theme'"],
  "dod": [
    {"kind": "url_200", "params": {"path": "/"},
     "description": "site loads"},
    {"kind": "console_clean", "params": {}, "description": "no console errors"},
    {"kind": "dom_exists", "params": {"selector": "nav, header"},
     "description": "navigation"},
    {"kind": "dom_exists", "params": {"selector": "form"},
     "description": "contact form"}
  ]
}

Rules:
- "assumptions": only things the client did NOT specify. Omit if none.
- FIRST task is always kind="create" (the platform builds the site from the
  brief in its description — write that description as a complete build
  brief: pages, sections, style, forms, content instructions).
- Following tasks are kind="instruct" (chat edits: things the create-brief
  cannot guarantee, e.g. wiring a specific API, inserting provided SVG
  assets by name). Most plans need 0-2 of these. Omit if none.
- dod: 4-7 binary checks covering load, no console errors, and the key
  visible elements (navigation, main heading, contact form if requested).
""" + _DOD_RULES + """
- JSON only. No prose."""


PLAN_EXISTING_SYSTEM = """You are a senior engineer planning CHANGES to an existing deployed website.
The site already exists and is live. Produce ONLY a JSON object:

{
  "tasks": [
    {"title": "short task name", "summary": "what changes for the client, max 12 words",
     "description": "one clear instruction", "kind": "instruct"}
  ],
  "assumptions": ["up to 3 defaults you chose"],
  "dod": [
    {"kind": "url_200", "params": {"path": "/"}, "description": "site loads"},
    {"kind": "console_clean", "params": {}, "description": "no console errors"},
    {"kind": "text_present", "params": {"selector": "h1", "text": "exact text the client asked for"},
     "description": "new headline"}
  ]
}

Rules:
- ALL tasks are kind="instruct" (chat instructions to the build agent).
  NEVER produce a kind="create" task — the site already exists.
- Most plans need 1-2 tasks. Each description is ONE clear instruction.
- "assumptions": only things the client did NOT specify. Omit if none.
- dod: 3-5 binary checks covering the change landing correctly plus site
  still loading clean.
""" + _DOD_RULES + """
- JSON only."""


def generate_plan(requirement: str, mode: str = "new") -> Dict[str, Any]:
    try:
        if mode == "existing":
            raw = _chat(PLAN_EXISTING_SYSTEM,
                        f"Change requirement for the existing site:\n\n{requirement}\n\nProduce the task board JSON (instruct tasks only).",
                        2000)
        else:
            raw = _chat(PLAN_SYSTEM, f"Requirement:\n\n{requirement}\n\nProduce the task board JSON.", 2500)
    except Exception as exc:
        # LLM down → single-task fallback plan below instead of a cycle
        # stuck in "planning" with no reply.
        logger.warning("[PLAN] LLM call failed, using fallback plan: %s", exc)
        raw = ""
    out = _extract_json(raw)
    tasks = [t for t in (out.get("tasks") or []) if isinstance(t, dict)]
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
    assumptions = [str(a)[:120] for a in (out.get("assumptions") or []) if a][:3]
    return {"tasks": tasks, "dod": _sanitize_dod(dod), "assumptions": assumptions}


# ── 2b. DoD patch on a correction ───────────────────────────────────────

PATCH_DOD_SYSTEM = """You maintain the acceptance checklist of a live website.
The client just asked for a change. Update the checklist so it describes
the site AFTER the change. Produce ONLY a JSON object: {"dod": [ ... ]}

How to update:
- REMOVE or REPLACE every check the change makes outdated (e.g. a check for
  the old headline text when the client asked for a new headline; a check
  for a section the client asked to remove).
- ADD at most 2 checks that confirm the requested change landed.
- Keep every other check exactly as it is. Keep url_200 and console_clean.
""" + _DOD_RULES + """
- JSON only."""


def patch_dod(dod: List[Dict[str, Any]], correction: str) -> Optional[List[Dict[str, Any]]]:
    """Return the DoD updated for a user correction, or None when it could
    not be produced (caller keeps the old DoD and flags it as predating
    the change). Checks that are new relative to `dod` carry "new": True."""
    try:
        raw = _chat(PATCH_DOD_SYSTEM,
                    "Current checklist:\n" + json.dumps(dod)[:6000]
                    + "\n\nClient's change request:\n" + correction[:2000]
                    + "\n\nReturn the updated checklist JSON.", 1500)
    except Exception as exc:
        logger.warning("[PATCH-DOD] LLM call failed: %s", exc)
        return None
    out = _extract_json(raw)
    if not isinstance(out.get("dod"), list) or not out["dod"]:
        return None
    patched = _sanitize_dod(out["dod"], fallback=dod)

    def _sig(d: Dict[str, Any]) -> str:
        return json.dumps([d.get("kind"), d.get("params") or {}], sort_keys=True)

    old = {_sig(d): d for d in dod if isinstance(d, dict)}
    for d in patched:
        prior = old.get(_sig(d))
        # new for this change, or still-unreported from an earlier one
        if prior is None or prior.get("new"):
            d["new"] = True
    return patched


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
