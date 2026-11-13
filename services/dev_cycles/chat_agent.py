#!/usr/bin/env python3
"""The PM brain of a dev cycle — LLM turns, all strict-JSON.

  1. intake_turn(history)        → clarify the full requirement: questions
                                   (each with a default) + a written spec
  2. generate_plan(spec)         → micro tasks, each with its own acceptance
                                   checks, plus the regression checklist
  3. plan_change(request, ...)   → micro tasks for a change on a live
                                   project + the updated regression checklist
  4. repair_instruction(...)     → a fix instruction from failure evidence

Uses the z.ai coding endpoint (free quota) with an OpenRouter fallback.
"""

from __future__ import annotations

import json
import logging
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
    text = (text or "").strip()
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
        out = json.loads(text[start:end + 1])
        return out if isinstance(out, dict) else {}
    except json.JSONDecodeError:
        return {}


PROJECT_TYPE_NAMES = {1: "website", 2: "Telegram bot", 3: "Discord bot"}


def project_type_name(type_id: Any) -> str:
    try:
        return PROJECT_TYPE_NAMES.get(int(type_id or 1), "AI agent")
    except (TypeError, ValueError):
        return "website"


# ── 1. Intake: clarify the full requirement ─────────────────────────────

_SPEC_SHAPE = """{
  "ready": false,
  "questions": [{"q": "short, specific question", "default": "what you'll do if they don't answer"}],
  "spec": {
    "summary": "one or two sentences: what will be built and for whom",
    "goal": "the outcome the client wants",
    "audience": "who uses it",
    "scope": ["each page, section or feature — one per item"],
    "content": "real content the client gave (names, text, prices, contact details), or 'AI-written'",
    "style": "look and feel",
    "integrations": ["external services, where forms send, APIs"],
    "acceptance": ["observable statements of done, in plain words"],
    "assumptions": ["defaults you chose that the client did not specify"]
  }
}"""

INTAKE_SYSTEM = """You are a senior product engineer running the discovery step for a new {ptype}.
Nothing is built until the requirement is fully clear and the client has
confirmed it. Read the conversation and reply with ONLY a JSON object:

""" + _SPEC_SHAPE + """

How to decide:
- Always fill "spec" with your best current understanding, even when not ready.
- ready=false while something that changes WHAT gets built is unknown: the
  goal, the must-have pages or features, real content only the client has
  (business name, contact details, prices, links), or where an integration
  sends data.
- Ask at most 3 questions per turn, most important first. Every question has
  a sensible "default", so the client can simply say "ok".
- Never ask about things with an obvious default (colours, fonts, layout,
  imagery, copy tone) unless the client raised them.
- Never repeat a question the client answered or skipped. Skipped, or "go
  with your suggestions", means: use the default.
- ready=true once every remaining unknown has a reasonable default. Then
  "questions" is empty and "acceptance" lists 3-8 concrete, checkable
  statements of done.
JSON only."""

INTAKE_EXISTING_SYSTEM = """You are a senior engineer running the discovery step for CHANGES to an existing, live {ptype}.
Nothing is changed until the request is clear and the client has confirmed
it. Read the conversation and reply with ONLY a JSON object:

""" + _SPEC_SHAPE + """

For a change request, "scope" lists each change and "acceptance" says how
each change will be visible once done.
- ready=false only when you cannot tell WHAT to change or WHERE, or the
  change needs real content only the client has. Ask at most 2 questions,
  each with a "default".
- A clear instruction ("make the hero headline say X", "add a pricing
  section", "switch to a dark theme") is ready=true straight away.
- Skipped questions, or "go with your suggestions", mean: use the default.
JSON only."""


def _as_list(v: Any, cap: int) -> List[str]:
    if isinstance(v, str):
        v = [v] if v.strip() else []
    return [str(x).strip()[:240] for x in (v or []) if str(x).strip()][:cap] if isinstance(v, list) else []


def _clean_spec(raw: Any, history: List[Dict[str, str]]) -> Dict[str, Any]:
    s = raw if isinstance(raw, dict) else {}
    first_user = next((m["content"] for m in history if m["role"] == "user"), "")
    return {
        "summary": str(s.get("summary") or first_user).strip()[:600],
        "goal": str(s.get("goal") or "").strip()[:300],
        "audience": str(s.get("audience") or "").strip()[:200],
        "scope": _as_list(s.get("scope"), 15),
        "content": str(s.get("content") or "").strip()[:600],
        "style": str(s.get("style") or "").strip()[:200],
        "integrations": _as_list(s.get("integrations"), 6),
        "acceptance": _as_list(s.get("acceptance"), 10),
        "assumptions": _as_list(s.get("assumptions"), 6),
    }


def _clean_questions(raw: Any) -> List[Dict[str, str]]:
    out = []
    for q in raw if isinstance(raw, list) else []:
        if isinstance(q, dict) and str(q.get("q") or "").strip():
            out.append({"q": str(q["q"]).strip()[:300], "default": str(q.get("default") or "").strip()[:200]})
        elif isinstance(q, str) and q.strip():
            out.append({"q": q.strip()[:300], "default": ""})
    return out[:3]


def intake_turn(history: List[Dict[str, str]], mode: str = "new",
                project_type: str = "website") -> Dict[str, Any]:
    """One discovery turn. Returns {ready, questions:[{q, default}], spec,
    missing}. The spec is always filled with the current understanding."""
    convo = "\n".join(f"{m['role']}: {m['content'][:2000]}" for m in history[-20:])
    system = (INTAKE_EXISTING_SYSTEM if mode == "existing" else INTAKE_SYSTEM).replace("{ptype}", project_type)
    try:
        raw = _chat(system, "Conversation so far:\n\n" + convo + "\n\nJSON only.", 1500)
    except Exception as exc:
        # LLM down must not leave the user without a reply — fall through
        # to the tie-break below.
        logger.warning("[INTAKE] LLM call failed: %s", exc)
        raw = ""
    out = _extract_json(raw)
    ready = bool(out.get("ready"))
    questions = _clean_questions(out.get("questions"))
    # Tie-breaks: not-ready with no question would loop forever. Enough
    # words from the client → proceed (the spec still gets confirmed);
    # otherwise ask one plain question. ready + questions → trust ready.
    if not ready and not questions:
        user_words = sum(len(m["content"].split()) for m in history if m["role"] == "user")
        if user_words >= 4:
            ready = True
        elif mode == "existing":
            questions = [{"q": "What would you like me to change?", "default": ""}]
        else:
            questions = [{"q": "What would you like to build? One sentence is enough to start.", "default": ""}]
    if ready and questions:
        questions = []
    return {
        "ready": ready,
        "questions": questions,
        "spec": _clean_spec(out.get("spec"), history),
        "missing": [str(m)[:200] for m in (out.get("missing") or [])][:5],
    }


def spec_to_text(spec: Dict[str, Any]) -> str:
    """The confirmed spec as plain text for the planner."""
    parts = [f"Summary: {spec.get('summary', '')}"]
    for key, label in (("goal", "Goal"), ("audience", "Audience"), ("content", "Content"), ("style", "Style")):
        if spec.get(key):
            parts.append(f"{label}: {spec[key]}")
    for key, label in (("scope", "Scope"), ("integrations", "Integrations"),
                       ("acceptance", "Acceptance criteria"), ("assumptions", "Assumptions")):
        if spec.get(key):
            parts.append(f"{label}:\n" + "\n".join(f"- {x}" for x in spec[key]))
    return "\n".join(parts)


# ── 2. Plan: micro tasks with their own checks ──────────────────────────

# Checks are written BEFORE the site exists, so they must never depend on
# copy or markup the planner guessed — only on structure and on text the
# client literally gave.
_CHECK_RULES = """- Check kinds: url_200 (params.path), dom_exists (params.selector),
  text_present (params.selector + params.text).
- Selectors: plain semantic tags ONLY (nav, header, main, h1, h2, form,
  footer, img, button, input, a[href^="mailto:"], a[href^="tel:"]). NEVER
  class names, ids or data-attributes.
- text_present: ONLY for text the client literally gave (brand name, an
  exact headline, a phone number, opening hours). That exact text must also
  appear word-for-word in the task description as required copy. Never
  invent copy to check.
- Each check "description" is a short plain noun phrase a non-technical
  client understands ("contact form", "opening hours in the footer")."""

VALID_DOD_KINDS = {"url_200", "console_clean", "dom_exists", "text_present"}
CORE_DOD_KINDS = ("url_200", "console_clean")
_DEFAULT_CORE = {
    "url_200": {"kind": "url_200", "params": {"path": "/"}, "description": "site loads"},
    "console_clean": {"kind": "console_clean", "params": {}, "description": "no console errors"},
}


def check_sig(d: Dict[str, Any]) -> str:
    return json.dumps([d.get("kind"), d.get("params") or {}], sort_keys=True)


def _clean_check(d: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(d, dict) or d.get("kind") not in VALID_DOD_KINDS:
        return None
    params = d.get("params") if isinstance(d.get("params"), dict) else {}
    return {"kind": d["kind"], "params": params,
            "description": str(d.get("description") or d["kind"])[:120]}


def _sanitize_checks(checks: Any, cap: int = 3) -> List[Dict[str, Any]]:
    """A task's own checks: valid kinds, no duplicates, and no site-wide
    core checks (the engine adds those to every task)."""
    out, seen = [], set()
    for raw in checks if isinstance(checks, list) else []:
        c = _clean_check(raw)
        if not c or c["kind"] == "console_clean":
            continue
        if c["kind"] == "url_200" and (c["params"].get("path") or "/") == "/":
            continue
        if check_sig(c) in seen:
            continue
        seen.add(check_sig(c))
        out.append(c)
    return out[:cap]


def _sanitize_dod(dod: Any, fallback: Any = None, cap: int = 12) -> List[Dict[str, Any]]:
    """The regression checklist: valid, de-duplicated checks with both core
    checks guaranteed (taken from `fallback`, else defaults)."""
    out, seen = [], set()
    for raw in dod if isinstance(dod, list) else []:
        c = _clean_check(raw)
        if c and check_sig(c) not in seen:
            seen.add(check_sig(c))
            for flag in ("new", "predates_change"):
                if isinstance(raw, dict) and raw.get(flag):
                    c[flag] = True
            out.append(c)
    for kind in reversed(CORE_DOD_KINDS):
        if not any(d["kind"] == kind for d in out):
            prior = next((d for d in (fallback or []) if isinstance(d, dict) and d.get("kind") == kind), None)
            out.insert(0, dict(prior or _DEFAULT_CORE[kind]))
    return out[:cap]


def regression_checks(tasks: List[Dict[str, Any]], base: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Everything every task promised, plus the core checks: the final
    sweep re-runs all of it so a later step can't silently break an earlier one."""
    pool = list(base or []) + [c for t in tasks for c in (t.get("checks") or [])]
    return _sanitize_dod(pool, cap=24)


_TASK_SHAPE = """{
  "tasks": [
    {"title": "short task name", "summary": "what the client gets, max 12 words",
     "description": "a precise instruction for the build agent",
     "kind": "create" | "instruct",
     "checks": [{"kind": "dom_exists", "params": {"selector": "form"}, "description": "contact form"}]}
  ],
  "assumptions": ["defaults you chose, max 3"]
}"""

PLAN_SYSTEM = """You are a senior engineer turning a confirmed spec for a new {ptype} into MICRO TASKS.
Produce ONLY a JSON object:

""" + _TASK_SHAPE + """

Rules:
- Each task is ONE small, focused piece of work that a build agent can finish
  in one go and that can be verified on its own: one page, one section, one
  feature, one integration. Typical plans have 3-8 tasks.
- FIRST task kind="create": the foundation only — every page from the spec
  with working navigation, the overall style, and simple placeholder
  sections. Its description is a complete build brief for that foundation.
- Every later task kind="instruct": ONE focused change on the existing
  project, written as a precise instruction, including any exact content
  from the spec ("Add a footer on every page with the text: Open daily 7am
  to 7pm").
- Order tasks so each builds on the ones before it.
- "checks": 1-3 checks that prove THIS task is done on the live site — never
  checks for another task. Load and console checks are added automatically.
  Every acceptance criterion that is visible on a page must be covered by
  some task's checks.
- If the project is not a website, leave "checks" empty (the platform
  checks the running process instead).
""" + _CHECK_RULES + """
- JSON only. No prose."""

PLAN_EXISTING_SYSTEM = """You are a senior engineer turning a confirmed change request for a live {ptype} into MICRO TASKS.
The project already exists. Produce ONLY a JSON object:

""" + _TASK_SHAPE + """

Rules:
- ALL tasks are kind="instruct". NEVER kind="create" — the project exists.
- Each task is ONE focused change, written as a precise instruction for the
  build agent, with any exact content from the request. Typically 1-4 tasks.
- "checks": 1-3 checks that prove THIS change is live. Load and console
  checks are added automatically.
- If the project is not a website, leave "checks" empty.
""" + _CHECK_RULES + """
- JSON only."""


def _clean_tasks(raw: Any, mode: str, fallback_desc: str, is_website: bool) -> List[Dict[str, Any]]:
    tasks = []
    for t in raw if isinstance(raw, list) else []:
        if not isinstance(t, dict) or not str(t.get("description") or t.get("title") or "").strip():
            continue
        tasks.append({
            "title": str(t.get("title") or "Task").strip()[:120],
            "summary": str(t.get("summary") or "").strip()[:140],
            "description": str(t.get("description") or t.get("title")).strip()[:8000],
            "kind": "create" if t.get("kind") == "create" else "instruct",
            "checks": _sanitize_checks(t.get("checks")) if is_website else [],
        })
    if mode == "existing":
        tasks = [t for t in tasks if t["kind"] != "create"]  # project exists
        if not tasks:
            tasks = [{"title": "Apply the changes", "summary": "", "description": fallback_desc[:8000],
                      "kind": "instruct", "checks": []}]
    else:
        tasks = [t for i, t in enumerate(tasks) if t["kind"] != "create" or i == 0]
        if not tasks or tasks[0]["kind"] != "create":
            tasks.insert(0, {"title": "Build the foundation", "summary": "", "kind": "create",
                             "description": fallback_desc[:8000], "checks": []})
    return tasks[:12]


def generate_plan(requirement: str, mode: str = "new", project_type: str = "website") -> Dict[str, Any]:
    """Micro tasks (each with its own checks) + the regression checklist."""
    system = (PLAN_EXISTING_SYSTEM if mode == "existing" else PLAN_SYSTEM).replace("{ptype}", project_type)
    try:
        raw = _chat(system, f"Confirmed spec:\n\n{requirement}\n\nProduce the micro-task JSON.", 3500)
    except Exception as exc:
        # LLM down → single-task fallback plan below instead of a cycle
        # stuck in "planning" with no reply.
        logger.warning("[PLAN] LLM call failed, using fallback plan: %s", exc)
        raw = ""
    out = _extract_json(raw)
    tasks = _clean_tasks(out.get("tasks"), mode, requirement, project_type == "website")
    assumptions = [str(a)[:120] for a in (out.get("assumptions") or []) if a][:3]
    return {"tasks": tasks, "dod": regression_checks(tasks), "assumptions": assumptions}


# ── 3. A change on a live project ───────────────────────────────────────

CHANGE_SYSTEM = """You are a senior engineer. The client asked for a change on their live {ptype}.
Produce ONLY a JSON object:

{
  "tasks": [ ...micro tasks, same shape as below... ],
  "dod": [ ...the full regression checklist AFTER the change... ]
}

Task shape: {"title", "summary", "description", "kind": "instruct", "checks": [...]}

Rules for tasks:
- 1-4 micro tasks, each ONE focused change written as a precise instruction
  for the build agent, with any exact content the client gave.
- "checks": 1-3 checks that prove THIS change is live.

Rules for "dod" (start from the current checklist you are given):
- REMOVE or REPLACE every check the change makes outdated (the old headline
  text when the client wants a new one; a section the client removes).
- Keep every other check exactly as it is.
- Do not add the new tasks' checks here; they are merged automatically.
""" + _CHECK_RULES + """
- If the project is not a website, leave all checks empty.
- JSON only."""


def plan_change(request: str, spec_summary: str, dod: List[Dict[str, Any]],
                project_type: str = "website") -> Optional[Dict[str, Any]]:
    """Micro tasks for a change + the regression checklist with outdated
    checks removed. None when the LLM is unavailable (caller falls back)."""
    try:
        raw = _chat(CHANGE_SYSTEM.replace("{ptype}", project_type),
                    f"What the project is: {spec_summary[:1500]}\n\n"
                    f"Current checklist:\n{json.dumps(dod)[:6000]}\n\n"
                    f"Client's change request:\n{request[:3000]}\n\nJSON only.", 2500)
    except Exception as exc:
        logger.warning("[CHANGE] LLM call failed: %s", exc)
        return None
    out = _extract_json(raw)
    if not isinstance(out.get("tasks"), list) or not out["tasks"]:
        return None
    tasks = _clean_tasks(out["tasks"], "existing", request, project_type == "website")
    kept = _sanitize_dod(out.get("dod") if isinstance(out.get("dod"), list) else dod, fallback=dod, cap=24)
    old = {check_sig(d) for d in dod if isinstance(d, dict)}
    new_dod = regression_checks(tasks, base=kept)
    for d in new_dod:
        if check_sig(d) not in old:
            d["new"] = True
    return {"tasks": tasks, "dod": new_dod}


# ── 3b. Checklist patch (fallback when plan_change is unavailable) ──────

PATCH_DOD_SYSTEM = """You maintain the acceptance checklist of a live website.
The client just asked for a change. Update the checklist so it describes
the site AFTER the change. Produce ONLY a JSON object: {"dod": [ ... ]}

How to update:
- REMOVE or REPLACE every check the change makes outdated.
- ADD at most 2 checks that confirm the requested change landed.
- Keep every other check exactly as it is. Keep url_200 and console_clean.
""" + _CHECK_RULES + """
- JSON only."""


def patch_dod(dod: List[Dict[str, Any]], correction: str) -> Optional[List[Dict[str, Any]]]:
    """Return the DoD updated for a user correction, or None when it could
    not be produced. Checks that are new relative to `dod` carry "new": True."""
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
    patched = _sanitize_dod(out["dod"], fallback=dod, cap=24)
    old = {check_sig(d): d for d in dod if isinstance(d, dict)}
    for d in patched:
        prior = old.get(check_sig(d))
        if prior is None or prior.get("new"):
            d["new"] = True
    return patched


# ── 4. Repair instruction writer ────────────────────────────────────────

REPAIR_SYSTEM = """You are a senior engineer writing a fix instruction for a build agent.
Given the task, what it was supposed to do, the check that failed on the
live site, and the evidence, write ONE short imperative instruction (2-4
sentences) that fixes it. Reference the exact element/text. No JSON."""


def repair_instruction(task_title: str, failed_check: Dict[str, Any], evidence: str,
                       task_description: str = "") -> str:
    user = (
        f"Task: {task_title}\n"
        + (f"What the task had to do: {task_description[:1500]}\n" if task_description else "")
        + f"Failed check: {failed_check.get('kind')} — {failed_check.get('description')}\n"
        f"Params: {json.dumps(failed_check.get('params') or {})}\n"
        f"Evidence: {evidence[:600]}\n\nWrite the fix instruction."
    )
    return _chat(REPAIR_SYSTEM, user, 400).strip()
