#!/usr/bin/env python3
"""Dev Cycle engine — event-driven orchestrator (LISTEN/NOTIFY).

The cycle, end to end:
  intake      clarify the full requirement with the client (questions with
              defaults, a written spec kept in plan["spec"])
  confirming  the spec is shown; nothing is built until the client says yes
  planning    the spec becomes MICRO TASKS, each with its own checks
              (stored in cycle_tasks.dod_item = {"checks": [...]})
  building    per task: execute → verify ITS checks on the live project →
              repair (≤ MAX_REPAIRS) until validated
  delivered   only when every task is validated AND a final regression sweep
              of everything promised passes
  needs_attention  anything that could not be validated: the client is told
              exactly what is blocked and what to do

Wakes on `dev_cycle_events` notifications; 60s reconcile covers lost
events. Task states: todo → in_progress → under_review → done | failed.

Events are handled on a small thread pool, serialised per cycle by a lock,
so one cycle's verify sweep or LLM call never delays another user's reply.

Entry: dev_cycle_engine.py (pm2) → main() here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from services.dev_cycles import chat_agent, store
from services.dev_cycles.notify import CHANNEL, notify_cycle

logger = logging.getLogger("services.dev_cycles.engine")

RECONCILE_INTERVAL = 60  # seconds — lost-event safety net
TASK_WALL_CLOCK_MIN = 30  # a task stuck in_progress longer than this = failed
MAX_REPAIRS = 2
MAX_RECHECKS = 5  # automatic re-verifies (one per reconcile) before parking
MAX_INTAKE_TURNS = 4  # after this many client replies, go with the defaults
MAX_REGRESSION_FIXES = 1  # automatic fix rounds when the final sweep finds a break
CORE_KINDS = {"url_200", "console_clean"}
CORE_CHECKS = [
    {"kind": "url_200", "params": {"path": "/"}, "description": "site loads"},
    {"kind": "console_clean", "params": {}, "description": "no console errors"},
]
FOLLOWUP_STATUSES = ("building", "delivered", "failed", "needs_attention")

# A short reply that approves the spec ("yes", "looks good, go").
APPROVE_RE = re.compile(
    r"^\W*(yes|yep|yeah|yup|ok|okay|sure|go|go ahead|start|build it|do it|confirm(ed)?|"
    r"looks good|sounds good|perfect|great|lgtm|approved?)\b", re.I)

# Short follow-up messages that are commands, not change requests.
RETRY_RE = re.compile(r"^\W*(please\s+)?(retry|try again|again|redo|re-?run)\b", re.I)
RECHECK_RE = re.compile(r"^\W*(please\s+)?(check (it )?again|re-?check|verify again)\b", re.I)
# "fix these" / "fix the warnings" → the change refers to the last receipt's notes.
NOTES_RE = re.compile(
    r"\bfix (it|them|these|those|that|this|the (notes?|warnings?|issues?|problems?))\b"
    r"|\b(warnings?|the notes?)\b", re.I)


# ── small helpers ───────────────────────────────────────────────────────

def _j(value: Any, default: Any) -> Any:
    """JSONB columns arrive as dict/list (RealDictCursor) or, rarely, str."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return default
    return value if isinstance(value, type(default)) else default


def _result(task: Dict[str, Any]) -> Dict[str, Any]:
    return _j(task.get("result"), {})


def _payload(task: Dict[str, Any]) -> Dict[str, Any]:
    return _j(task.get("payload"), {})


def _dod(cycle: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [d for d in _j(cycle.get("dod"), []) if isinstance(d, dict)]


def _plan(cycle: Dict[str, Any]) -> Dict[str, Any]:
    return _j(cycle.get("plan"), {})


def _spec(cycle: Dict[str, Any]) -> Dict[str, Any]:
    return _j(_plan(cycle).get("spec"), {})


def _task_checks(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A task's own acceptance checks. dod_item holds {"checks": [...]};
    older rows may hold a single check dict or a list."""
    raw = task.get("dod_item")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = None
    if isinstance(raw, dict) and isinstance(raw.get("checks"), list):
        raw = raw["checks"]
    elif isinstance(raw, dict) and raw.get("kind"):
        raw = [raw]
    return [c for c in raw if isinstance(c, dict) and c.get("kind")] if isinstance(raw, list) else []


def _ptype_name(cycle: Dict[str, Any]) -> str:
    return chat_agent.project_type_name(cycle.get("project_type_id"))


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def _say(cycle_id: int, text: str) -> None:
    store.add_message(cycle_id, "agent", text)


# ── event dispatch ──────────────────────────────────────────────────────

_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="cycle")
_locks: Dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def _cycle_lock(cycle_id: int) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(cycle_id)
        if lock is None:
            lock = _locks[cycle_id] = threading.Lock()
        return lock


def _event_cycle_id(payload: Dict[str, Any]) -> Optional[int]:
    if payload.get("event") == "run_completed":
        run_id = int(payload.get("run_id") or 0)
        task = store.find_task_by_run(run_id, str(payload.get("kind"))) if run_id else None
        return int(task["cycle_id"]) if task else None  # None = not a cycle-managed run
    if payload.get("cycle_id") is None:
        return None
    return int(payload["cycle_id"])


def handle_event(payload: Dict[str, Any]) -> None:
    """Route one notification under its cycle's lock. Never raises (the
    engine must survive bad events)."""
    event = payload.get("event")
    try:
        if event not in ("cycle_created", "user_message", "run_completed"):
            logger.debug("[ENGINE] ignored event %s", event)
            return
        cycle_id = _event_cycle_id(payload)
        if cycle_id is None:
            return
        with _cycle_lock(cycle_id):
            if event == "cycle_created":
                _on_cycle_created(cycle_id)
            elif event == "user_message":
                mid = payload.get("message_id")
                _on_user_message(cycle_id, int(mid) if mid else None)
            else:
                _on_run_completed(
                    kind=str(payload.get("kind")),
                    run_id=int(payload.get("run_id") or 0),
                    status=str(payload.get("status") or ""),
                )
    except Exception as exc:
        logger.exception("[ENGINE] event %s failed: %s", event, exc)


def _on_cycle_created(cycle_id: int) -> None:
    cycle = store.get_cycle(cycle_id)
    if not cycle:
        return
    if cycle.get("project_id"):
        _say(cycle_id,
             "Tell me what you'd like changed. I'll ask anything I need to know, confirm "
             "the change with you, then do it in small steps — checking each one on the "
             "live project — and let you know once it's all verified.")
    else:
        _say(cycle_id,
             "Tell me what you want to build. I'll ask a few questions until the requirement "
             "is clear and confirm it with you. Then I'll split it into small steps, build and "
             "check each one in a real browser, and deliver the link once everything is verified.")
    store.update_cycle(cycle_id, status="intake")


def _requirement_text(history: List[Dict[str, str]]) -> str:
    """The brief for the planner: everything the client said, with the
    engineer's questions kept so short answers ("yes, dark") have context."""
    turns = []
    seen_user = False
    for m in history:
        if m["role"] == "user":
            seen_user = True
            turns.append(("Client", m["content"]))
        elif seen_user:  # skip the greeting
            turns.append(("Engineer asked", m["content"]))
    while turns and turns[-1][0] != "Client":
        turns.pop()
    if len(turns) == 1:
        return turns[0][1]
    return "\n".join(f"{who}: {text}" for who, text in turns)


def _on_user_message(cycle_id: int, message_id: Optional[int] = None) -> None:
    """Route a client message by cycle stage: discovery (intake), spec
    confirmation, or a follow-up on a planned cycle."""
    cycle = store.get_cycle(cycle_id)
    if not cycle:
        return
    status = cycle.get("status")

    msgs = store.get_messages(cycle_id)
    # Handle the message this event is about (two quick messages = two
    # events; reading "the last one" twice would drop the first).
    msg = next((m for m in msgs if m["id"] == message_id), None) if message_id else None
    if msg is None:
        msg = next((m for m in reversed(msgs) if m["role"] == "user"), None)
    if not msg or msg["role"] != "user":
        return

    if status == "planning":
        # The plan step crashed (it normally completes atomically under the
        # cycle lock) — acknowledge instead of dropping the message, and let
        # dispatch recover the board.
        _say(cycle_id, "Noted — I'll add that once the plan is set.")
        store.update_cycle(cycle_id, status="building")
        _dispatch_next(cycle_id)
        return
    if status in FOLLOWUP_STATUSES:
        _handle_followup(cycle, msg["content"])
        return
    if status == "confirming":
        text = msg["content"].strip()
        if len(text.split()) <= 8 and APPROVE_RE.match(text):
            _start_build(cycle_id)
            return
        # Anything else adjusts the spec: one more discovery turn.
    elif status != "intake":
        return
    _discovery_turn(cycle, msgs, msg)


def _questions_message(questions: List[Dict[str, str]]) -> str:
    if len(questions) == 1 and not questions[0].get("default"):
        return questions[0]["q"]
    lines = ["A few questions so I build exactly what you need:"]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q['q']}")
        if q.get("default"):
            lines.append(f"   Suggested: {q['default']}")
    if any(q.get("default") for q in questions):
        lines.append("Answer what you like — for anything you skip I'll go with the suggestion.")
    return "\n".join(lines)


def _spec_message(spec: Dict[str, Any], mode: str) -> str:
    """The written requirement the client confirms before anything is built."""
    lines = ["📝 Here's what I'll change" if mode == "existing" else "📝 Here's what I'll build"]
    if spec.get("summary"):
        lines.append(spec["summary"])
    for key, label in (("goal", "Goal"), ("audience", "For"), ("content", "Content"), ("style", "Style")):
        if spec.get(key):
            lines.append(f"{label}: {spec[key]}")
    if spec.get("integrations"):
        lines.append("Connects to: " + ", ".join(spec["integrations"]))
    for key, label in (("scope", "Changes:" if mode == "existing" else "Includes:"),
                       ("acceptance", "Done means:")):
        if spec.get(key):
            lines.append(label)
            lines.extend(f"• {x}" for x in spec[key])
    if spec.get("assumptions"):
        lines.append("Assumed: " + "; ".join(spec["assumptions"]) + ".")
    lines.append("Reply “yes” to start, or tell me what to change.")
    return "\n".join(lines)


def _discovery_turn(cycle: Dict[str, Any], msgs: List[Dict[str, Any]], msg: Dict[str, Any]) -> None:
    """Clarify until the requirement is complete, then show the spec for
    confirmation. Never builds on its own."""
    cycle_id = cycle["id"]
    mode = "existing" if cycle.get("project_id") else "new"
    history = [{"role": m["role"], "content": m["content"]}
               for m in msgs if m["role"] in ("user", "agent") and m["id"] <= msg["id"]]
    verdict = chat_agent.intake_turn(history, mode, _ptype_name(cycle))
    # Discovery must end: after MAX_INTAKE_TURNS replies, go with the defaults
    # (the client still confirms the spec before anything is built).
    user_turns = sum(1 for m in history if m["role"] == "user")
    if user_turns >= MAX_INTAKE_TURNS:
        verdict["ready"] = True
        verdict["questions"] = []

    plan = _plan(cycle)
    plan["spec"] = verdict["spec"]
    store.update_cycle(cycle_id, requirement_accum=_requirement_text(history)[:20000],
                       plan=json.dumps(plan))

    if not verdict["ready"]:
        store.update_cycle(cycle_id, status="intake")
        _say(cycle_id, _questions_message(verdict["questions"]) or "What would you like to build?")
        return
    store.update_cycle(cycle_id, status="confirming")
    _say(cycle_id, _spec_message(verdict["spec"], mode))


def _start_build(cycle_id: int) -> None:
    """The client confirmed the spec → micro tasks with their own checks."""
    cycle = store.get_cycle(cycle_id)
    mode = "existing" if cycle.get("project_id") else "new"
    website = _is_website(cycle)
    store.update_cycle(cycle_id, status="planning")
    requirement = (chat_agent.spec_to_text(_spec(cycle))
                   + "\n\nConversation with the client:\n" + (cycle.get("requirement_accum") or ""))
    result = chat_agent.generate_plan(requirement[:20000], mode, _ptype_name(cycle))

    plan = _plan(cycle)
    plan["assumptions"] = result["assumptions"]
    plan["regression_fixes"] = 0
    store.update_cycle(cycle_id, plan=json.dumps(plan), dod=json.dumps(result["dod"]), status="building")

    lines = []
    for i, t in enumerate(result["tasks"]):
        store.add_task(cycle_id, position=i, title=t["title"], description=t["description"],
                       kind=t["kind"], payload={"summary": t["summary"]} if t["summary"] else None,
                       dod_item={"checks": t["checks"]} if t["checks"] else None)
        lines.append(f"{i + 1}. {t['title']}" + (f" — {t['summary']}" if t["summary"] else ""))
    _say(cycle_id, _plan_message(result, lines, website))
    _dispatch_next(cycle_id)


def _plan_message(plan: Dict[str, Any], lines: List[str], website: bool = True) -> str:
    n = len(lines)
    msg = f"📋 Here's the plan — {n} small step{'s' if n != 1 else ''}, each checked before the next:\n"
    msg += "\n".join(lines)
    if plan.get("assumptions"):
        msg += "\n\nAssumed: " + "; ".join(plan["assumptions"]) + "."
    if website:
        msg += ("\n\nAfter each step I check it on the live site and fix anything that fails. "
                "Once every step is verified, I re-check everything together and send you the link.")
    else:
        msg += ("\n\nAfter each step I check the project is running and fix anything that fails. "
                "You'll hear from me once everything is verified.")
    eta = _eta_minutes(plan["tasks"])
    if eta:
        msg += f"\nBuilds like this usually take about {eta} min."
    return msg + "\nReply anytime to add or change something — I'll queue it."


def _median_run_seconds(kind: str) -> Optional[float]:
    """Median duration of the last 20 completed runs; None until there are
    at least 5 (never print a guessed number)."""
    from database_postgres import get_db

    table, extra = (("project_creation_runs", "AND type_id = 1") if kind == "create"
                    else ("session_chat_runs", ""))
    try:
        with get_db() as conn:
            try:
                row = conn.execute(
                    f"""SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY secs) AS med,
                               COUNT(*) AS n
                        FROM (SELECT EXTRACT(EPOCH FROM (completed_at - started_at)) AS secs
                              FROM {table}
                              WHERE status = 'completed' AND completed_at IS NOT NULL
                                AND started_at IS NOT NULL {extra}
                              ORDER BY id DESC LIMIT 20) s""").fetchone()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
        d = dict(row) if row is not None and not isinstance(row, dict) else (row or {})
        if int(d.get("n") or 0) >= 5 and d.get("med"):
            return float(d["med"])
    except Exception as exc:
        logger.debug("[ENGINE] no ETA for %s runs: %s", kind, exc)
    return None


def _eta_minutes(tasks: List[Dict[str, Any]]) -> Optional[int]:
    total = 0.0
    for kind in ("create", "instruct"):
        n = sum(1 for t in tasks if (t.get("kind") or "instruct") == kind)
        if not n:
            continue
        med = _median_run_seconds(kind)
        if med is None:
            return None
        total += n * (med + 60)  # + roughly a minute of browser checks each
    return max(1, round(total / 60)) if total else None


# ── follow-ups on a planned cycle (retry / check again / corrections) ───

def _handle_followup(cycle: Dict[str, Any], text: str) -> None:
    cycle_id = cycle["id"]
    text = (text or "").strip()
    if not text:
        return
    tasks = store.get_tasks(cycle_id)
    waiting = [t for t in tasks if t["status"] == "under_review"
               and _result(t).get("verdict") == "unverified"]
    in_flight = next((t for t in tasks if t["status"] in ("in_progress", "under_review")), None)

    # Keyword commands ("retry", "check again") only when the message is
    # short — "Redo the hero section in blue" is a change request, not a
    # retry command (first-review bug 1).
    is_command = len(text.split()) <= 4

    if is_command and RECHECK_RE.match(text):
        if waiting:
            _recheck(cycle_id, waiting[0])
        elif in_flight:
            _say(cycle_id, "I'm still working on this step — I'll check the live site as soon as it finishes.")
        else:
            store.update_cycle(cycle_id, status="building")
            _finalize(cycle_id, force_sweep=True)
        return

    if is_command and RETRY_RE.match(text):
        failed = [t for t in tasks if t["status"] == "failed" and _result(t).get("error") != "cancelled"]
        plan = _plan(cycle)
        plan["regression_fixes"] = 0  # an explicit retry earns a fresh fix round
        store.update_cycle(cycle_id, plan=json.dumps(plan))
        if not failed:
            if waiting:
                _recheck(cycle_id, waiting[0])
            elif cycle.get("status") == "needs_attention" and not in_flight:
                # every step is done but the final check didn't pass → re-check / fix
                _say(cycle_id, "On it — re-checking everything on the live project.")
                store.update_cycle(cycle_id, status="building")
                _finalize(cycle_id, force_sweep=True)
            else:
                _say(cycle_id, "Nothing failed, so there's nothing to retry — tell me what you'd like changed.")
            return
        for t in failed:
            payload = _payload(t)
            # Bug 2: drop a stale repair instruction — the retry must run the
            # task's own description, not the previous failure's fix text.
            payload.pop("repair_instruction", None)
            # Bug 4: retrying a failed CREATE must not build a second project
            # against the user's quota. If the cycle already has a project,
            # retry as an instruct build on that project instead.
            if t.get("kind") == "create" and cycle.get("project_id"):
                payload["create_retry"] = True
                store.update_task(t["id"], status="todo", repair_count=0,
                                  result=json.dumps({}), kind="instruct",
                                  payload=json.dumps(payload))
            else:
                store.update_task(t["id"], status="todo", repair_count=0,
                                  result=json.dumps({}), payload=json.dumps(payload))
        names = ", ".join(f"“{t['title']}”" for t in failed[:3])
        _say(cycle_id, f"On it — retrying {names}.")
        store.update_cycle(cycle_id, status="building")
        _dispatch_next(cycle_id)
        return

    _handle_correction(cycle, text, tasks, in_flight)
    if waiting:
        # the user is here anyway — don't make them wait for the next reconcile
        _recheck(cycle_id, waiting[0])


def _recheck(cycle_id: int, task: Dict[str, Any]) -> None:
    """Re-verify a task whose checks couldn't run. Never re-runs the build."""
    _say(cycle_id, "🔎 Checking the live site again…")
    res = _result(task)
    res.update({"recheck_count": 0, "parked": False})
    store.update_task(task["id"], result=json.dumps(res))
    task["result"] = res
    _review_task(cycle_id, task)


def _open_notes(cycle: Dict[str, Any]) -> List[str]:
    """Unresolved findings from the last receipt, in plain words."""
    sweep = _j(cycle.get("evidence"), {}).get("sweep") or {}
    return [r.get("user_text") or (r.get("check") or {}).get("description") or ""
            for r in sweep.get("results") or [] if r.get("verdict") == "fail"]


def _handle_correction(cycle: Dict[str, Any], text: str, tasks: List[Dict[str, Any]],
                       in_flight: Optional[Dict[str, Any]]) -> None:
    """A change request on a planned cycle → micro tasks with their own
    checks, appended to the board, and the regression checklist updated so
    outdated checks never contradict what the client now wants."""
    cycle_id = cycle["id"]
    request = text[:4000]
    if NOTES_RE.search(text):
        notes = [n for n in _open_notes(cycle) if n][:6]
        if notes:
            request += "\n\nOpen issues from the last check of the live project:\n" + \
                       "\n".join(f"- {n}" for n in notes)

    dod = _dod(cycle)
    summary = _spec(cycle).get("summary") or (cycle.get("requirement_accum") or "")[:1500]
    planned = chat_agent.plan_change(request, summary, dod, _ptype_name(cycle))
    if planned is None:
        # LLM unavailable: one task carrying the request as-is; flag checks
        # that may now be outdated instead of reporting them as failures.
        new_tasks = [{"title": f"Change: {text[:60]}", "summary": "", "description": request,
                      "kind": "instruct", "checks": []}]
        patched = chat_agent.patch_dod(dod, text)
        if patched is None:
            for d in dod:
                if d.get("kind") not in CORE_KINDS:
                    d["predates_change"] = True
            patched = dod
    else:
        new_tasks, patched = planned["tasks"], planned["dod"]

    for i, t in enumerate(new_tasks):
        payload = {"correction": True, "requests": [text[:300]]}
        if t.get("summary"):
            payload["summary"] = t["summary"]
        store.add_task(cycle_id, position=len(tasks) + i, title=t["title"],
                       description=t["description"], kind="instruct", payload=payload,
                       dod_item={"checks": t["checks"]} if t.get("checks") else None)
    plan = _plan(cycle)
    plan["regression_fixes"] = 0
    store.update_cycle(cycle_id, status="building", dod=json.dumps(patched), plan=json.dumps(plan))

    n = len(new_tasks)
    steps = "\n".join(f"{i}. {t['title']}" for i, t in enumerate(new_tasks, 1))
    when = f"right after “{in_flight['title']}”, which is running now" if in_flight else "now"
    _say(cycle_id, f"Got it — I'll do this in {n} step{'s' if n != 1 else ''}, starting {when}:\n"
                   f"{steps}\nEach one gets checked on the live project before I move on.")
    _dispatch_next(cycle_id)


# ── task dispatch ───────────────────────────────────────────────────────

def _dispatch_next(cycle_id: int) -> None:
    """Start the next todo task (one at a time)."""
    cycle = store.get_cycle(cycle_id)
    if not cycle or cycle.get("status") != "building":
        return
    tasks = store.get_tasks(cycle_id)
    if any(t["status"] in ("in_progress", "under_review") for t in tasks):
        return  # one at a time

    task = next((t for t in tasks if t["status"] == "todo"), None)
    if task is None:
        _finalize(cycle_id)
        return

    store.update_task(task["id"], status="in_progress")
    if not int(task.get("repair_count") or 0):  # repairs announce themselves
        step = tasks.index(task) + 1
        _say(cycle_id, f"🔨 Working on: {task['title']} (step {step} of {len(tasks)})")

    try:
        if task["kind"] == "create":
            _dispatch_create(cycle_id, task)
        else:
            _dispatch_instruct(cycle_id, task)
    except Exception as exc:
        logger.exception("[ENGINE] dispatch failed task %s", task["id"])
        store.update_task(task["id"], status="failed", result=json.dumps(
            {"error": str(exc)[:500], "reason": "it couldn't start (an internal error on our side)"}))
        _say(cycle_id, f"⚠️ I couldn't start “{task['title']}” (an internal error on our side). "
                       f"Reply “retry” to try again.")
        _dispatch_next(cycle_id)


def _dispatch_create(cycle_id: int, task: Dict[str, Any]) -> None:
    from services.project_creation_runs import enqueue_project_creation_run
    import secrets as _secrets

    cycle = store.get_cycle(cycle_id)
    name = _j(cycle.get("plan"), {}).get("name") or f"cycle-{cycle_id}-{_secrets.token_hex(2)}"
    domain = f"{name.lower().replace(' ', '-')[:40]}-{_secrets.token_hex(3)}"
    res = enqueue_project_creation_run(
        user_id=cycle["user_id"], name=name[:60], domain=domain,
        description=task["description"][:4000], type_id=1, template_id=None,
        bot_token=None, telegram_bot_token=None, telegram_chat_id=None,
        discord_webhook_url=None, email_to=None, api_endpoint=None,
        description_for_worker=task["description"][:8000],
    )
    # enqueue returns the PROJECT dict (not the run). Resolve the run row
    # by project so the engine can correlate completion notifications.
    project_id = res.get("id") or res.get("project_id")
    store.update_cycle(cycle_id, project_id=project_id)
    from database_postgres import get_db
    with get_db() as conn:
        run = conn.execute(
            "SELECT id FROM project_creation_runs WHERE project_id = %s ORDER BY id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    if run:
        _rid = (dict(run) if not isinstance(run, dict) else run)["id"]
        store.update_task(task["id"], creation_run_id=_rid)


def _dispatch_instruct(cycle_id: int, task: Dict[str, Any]) -> None:
    from services.session_chat_runs import create_run

    cycle = store.get_cycle(cycle_id)
    project_id = cycle.get("project_id")
    if not project_id:
        store.update_task(task["id"], status="failed",
                          result=json.dumps({"error": "no project yet"}))
        _say(cycle_id, f"⚠️ Skipped “{task['title']}” — the site wasn't created, so there's "
                       f"nothing to change yet. Reply “retry” to build it again.")
        _dispatch_next(cycle_id)
        return

    session_key = _ensure_cycle_session(cycle_id, project_id)
    # A repair runs its fix instruction; the task keeps its own description
    # (so a later "retry" and the board still show what the task is).
    message = _payload(task).get("repair_instruction") or task["description"]
    res = create_run(
        session_id=_session_id(session_key), session_key=session_key,
        project_id=project_id, user_id=cycle["user_id"], channel="webchat",
        mode="dream", user_message=message,
        session_context="", billing_user_id=None,
    )
    store.update_task(task["id"], session_run_id=res.get("id"))


# ── run completion ──────────────────────────────────────────────────────

_RUN_STATUS_WORDS = {"failed": "the build stopped with an error",
                     "cancelled": "the build was cancelled",
                     "interrupted": "the build was interrupted"}


def _on_run_completed(kind: str, run_id: int, status: str) -> None:
    """A creation or session run finished → move its task to review."""
    if not run_id:
        return
    task = store.find_task_by_run(run_id, kind)
    if not task:
        return  # not a cycle-managed run
    if task["status"] != "in_progress":
        return  # duplicate event — this run is already being reviewed

    cycle_id = task["cycle_id"]
    if status != "completed":
        why = _RUN_STATUS_WORDS.get(status, "the build didn't complete")
        store.update_task(task["id"], status="failed",
                          result=json.dumps({"run_status": status, "reason": why}))
        _say(cycle_id, f"⚠️ “{task['title']}” didn't finish ({why}). I'll carry on with the other "
                       f"steps — reply “retry” anytime to run it again.")
        _dispatch_next(cycle_id)
        return

    store.update_task(task["id"], status="under_review",
                      result=json.dumps({"phase": "verifying"}))
    task["result"] = {}
    cycle = store.get_cycle(cycle_id) or {}
    if _is_website(cycle):
        n = len(_checks_for(task))
        _say(cycle_id, f"🔎 {task['title']} — built. Checking it on the live site "
                       f"({n} check{'s' if n != 1 else ''}).")
    else:
        _say(cycle_id, f"🔎 {task['title']} — built. Checking the project is running.")
    _review_task(cycle_id, task)


def _checks_for(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What validates a task: the core checks plus the task's own checks."""
    out, seen = [], set()
    for c in CORE_CHECKS + _task_checks(task):
        sig = chat_agent.check_sig(c)
        if sig not in seen:
            seen.add(sig)
            out.append(c)
    return out


def _counts(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"results": results,
            "passed": sum(1 for r in results if r["verdict"] == "pass"),
            "failed": sum(1 for r in results if r["verdict"] == "fail"),
            "unverified": sum(1 for r in results if r["verdict"] == "unverified")}


def _compute_outcome(task: Dict[str, Any], cycle: Dict[str, Any], on_progress=None) -> Dict[str, Any]:
    """Run the task's checks once. Every check blocks: a task is validated
    only when all of its checks pass on the live project."""
    if _is_website(cycle):
        from services.dev_cycles.verifier import verify_all
        results = verify_all(_checks_for(task), _frontend_domain(cycle), on_progress)["results"]
    else:
        # Bots / agents / schedulers: the project's process must be alive.
        from services.dev_cycles.verifier import verify_process
        results = [verify_process(cycle)]

    fails = [r for r in results if r["verdict"] == "fail"]
    # a page that doesn't load explains every other miss → repair that first
    fails.sort(key=lambda r: 0 if (r.get("check") or {}).get("kind") in CORE_KINDS else 1)
    unverified = [r for r in results if r["verdict"] == "unverified"]
    verdict = "fail" if fails else ("unverified" if unverified or not results else "pass")
    explains = fails or unverified
    evidence = "; ".join(f"{(r.get('check') or {}).get('kind')}: {r.get('evidence', '')}"
                         for r in explains)[:800]
    return {"verdict": verdict, "evidence": evidence, "results": results, "fails": fails,
            "passed": sum(1 for r in results if r["verdict"] == "pass")}


def _review_task(cycle_id: int, task: Dict[str, Any]) -> None:
    """Verifier gate: under_review → done | back to todo (repair) | stays
    under_review (checks couldn't run) | failed (repairs exhausted).

    Unverified (browser/CDP down) is never a pass and never re-runs the
    build: the task waits in under_review and reconcile() re-verifies it,
    up to MAX_RECHECKS times, before parking it for a "check again".
    """
    cycle = store.get_cycle(cycle_id)
    rechecks = int(_result(task).get("recheck_count") or 0)

    def _progress(i: int, total: int, item: Dict[str, Any]) -> None:
        store.update_task(task["id"], result=json.dumps({
            "phase": "verifying", "step": i, "total": total,
            "label": str(item.get("description") or "")[:80],
            "recheck_count": rechecks}))

    outcome = _compute_outcome(task, cycle, _progress)

    if outcome["verdict"] == "unverified":
        rechecks += 1
        parked = rechecks > MAX_RECHECKS
        store.update_task(task["id"], status="under_review", result=json.dumps({
            "verdict": "unverified", "evidence": outcome["evidence"],
            "recheck_count": rechecks, "parked": parked}))
        if rechecks == 1:
            _say(cycle_id, f"⏳ “{task['title']}” is built, but my check couldn't run just now. "
                           f"I'll keep re-checking automatically — nothing needed from you.")
        elif parked:
            domain = _frontend_domain(cycle) if _is_website(cycle) else ""
            link = f": https://{domain}" if domain else ""
            _say(cycle_id, f"I still can't run the check, though the build itself finished{link}\n"
                           f"Reply “check again” whenever you like.")
        return

    if outcome["verdict"] == "pass":
        n = outcome["passed"]
        store.update_task(task["id"], status="done", result=json.dumps(
            {"verdict": "pass", "evidence": outcome["evidence"], "checks": n}))
        _say(cycle_id, f"✅ {task['title']} — verified ({n} check{'s' if n != 1 else ''} passed).")
        _dispatch_next(cycle_id)
        return

    # a check failed → repair (≤ MAX_REPAIRS) or give up on this step
    failing = outcome["fails"][0]
    reason = failing.get("user_text") or "a check failed on the live project"
    repairs = int(task.get("repair_count") or 0)
    if repairs >= MAX_REPAIRS:
        store.update_task(task["id"], status="failed", result=json.dumps(
            {"verdict": "fail", "evidence": outcome["evidence"], "repairs": repairs, "reason": reason}))
        _say(cycle_id, f"❌ “{task['title']}” — still failing after {repairs} fixes: {_lower_first(reason)}. "
                       f"I'll carry on with the other steps and tell you what needs your attention at the end.")
        _dispatch_next(cycle_id)
        return

    try:
        instruction = chat_agent.repair_instruction(task["title"], failing.get("check") or {},
                                                    outcome["evidence"], task.get("description") or "")
    except Exception as exc:
        logger.warning("[ENGINE] repair instruction failed: %s", exc)
        instruction = ""
    if not instruction:
        instruction = (f"This step isn't working on the live project yet ({reason}). Fix it. "
                       f"Evidence: {outcome['evidence'][:600]}")
    payload = _payload(task)
    payload["repair_instruction"] = instruction
    store.update_task(task["id"], status="todo", repair_count=repairs + 1, kind="instruct",
                      payload=json.dumps(payload),
                      result=json.dumps({"verdict": "fail", "evidence": outcome["evidence"], "reason": reason}))
    _say(cycle_id, f"🔁 {task['title']} — {_lower_first(reason)}. "
                   f"Fixing it (attempt {repairs + 1} of {MAX_REPAIRS}).")
    _dispatch_next(cycle_id)


# ── delivery: validated → delivered, otherwise needs_attention ──────────

_ERROR_WORDS = {"wall-clock timeout": f"it ran over {TASK_WALL_CLOCK_MIN} minutes",
                "no project yet": "the project wasn't created"}


def _failure_reason(task: Dict[str, Any]) -> str:
    r = _result(task)
    return (r.get("reason") or _ERROR_WORDS.get(str(r.get("error") or ""))
            or ("the build stopped" if r.get("run_status") else "it didn't finish"))


def _live_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [t for t in tasks if _result(t).get("error") != "cancelled"]


def _is_validated(sweep: Dict[str, Any], tasks: List[Dict[str, Any]], domain: str,
                  is_website: bool = True) -> bool:
    """Deliverable only when every step passed AND the final regression
    sweep of everything promised passed."""
    results = sweep.get("results") or []
    return (bool(results) and (bool(domain) or not is_website)
            and all(t["status"] == "done" for t in _live_tasks(tasks))
            and all(r["verdict"] == "pass" for r in results))


def _build_receipt(domain: str, sweep: Dict[str, Any], tasks: List[Dict[str, Any]],
                   is_website: bool = True) -> str:
    """The closing message. Delivered only when validated; otherwise it says
    exactly what is blocked and what the client can do about it."""
    results = sweep.get("results") or []
    noun = "site" if is_website else "project"
    link = f"https://{domain}" if is_website and domain else ""
    live = _live_tasks(tasks)
    failed = [t for t in live if t["status"] == "failed"]
    done = [t for t in live if t["status"] == "done"]
    sweep_fails = [r for r in results if r["verdict"] == "fail"]
    sweep_unverified = [r for r in results if r["verdict"] == "unverified"]

    if is_website and not domain:
        return ("⚠️ Needs your attention\n"
                "The site wasn't created, so there's nothing to check yet.\n"
                "Reply “retry” to build it again.")
    if failed or sweep_fails:
        lines = ["⚠️ Needs your attention"] + ([link] if link else [])
        lines.append(f"{len(done)} of {len(live)} steps are built and verified. Not done yet:")
        lines += [f"• {t['title']} — {_failure_reason(t)}" for t in failed[:5]]
        lines += [f"• {r.get('user_text') or (r.get('check') or {}).get('description') or 'a check failed'}"
                  for r in sweep_fails[:5]]
        lines.append("Reply “retry” and I'll try again, or tell me how you'd like it handled.")
        return "\n".join(lines)
    if sweep_unverified or not results:
        return "\n".join(["⚠️ Needs your attention"] + ([link] if link else []) + [
            f"Every step is built, but my final check of the {noun} couldn't run, "
            f"so I can't confirm it all works together yet.",
            "Reply “check again” and I'll re-check."])

    corrections = [t for t in done if _payload(t).get("correction") and not _payload(t).get("receipted")]
    lines = []
    if corrections:
        requests = list(dict.fromkeys(r for t in corrections for r in (_payload(t).get("requests") or [])))
        if len(requests) == 1:
            lines.append(f"✅ Change is live: “{requests[0][:80]}”")
        else:
            lines.append(f"✅ Your {len(requests) or len(corrections)} changes are live")
    else:
        lines.append("✅ Delivered — every step verified")
    if link:
        lines.append(link)
    n, k = len(done), len(results)
    lines.append(f"All {n} step{'s' if n != 1 else ''} passed their checks, and a final check of the "
                 f"whole {noun} ({k} check{'s' if k != 1 else ''}) passed"
                 f"{' in a real browser' if is_website else ''}.")
    confirmed = [r.get("user_text") for r in results
                 if (r.get("check") or {}).get("new") and r.get("user_text")]
    if confirmed:
        lines.append("Confirmed on the page: " + "; ".join(confirmed[:3]) + ".")
    lines.append("Reply to change anything.")
    return "\n".join(lines)


def _finalize(cycle_id: int, force_sweep: bool = False) -> None:
    """All tasks terminal → regression sweep of everything promised →
    one automatic fix round if something broke along the way → delivered
    (validated) or needs_attention, with a screenshot + Telegram receipt.
    `force_sweep` is kept for callers; the sweep always runs."""
    from services.dev_cycles.verifier import verify_all, verify_process

    cycle = store.get_cycle(cycle_id)
    website = _is_website(cycle)
    domain = _frontend_domain(cycle) if website else ""
    dod = _dod(cycle) or [dict(c) for c in CORE_CHECKS]
    tasks = store.get_tasks(cycle_id)

    if website:
        if domain:
            _say(cycle_id, f"🔎 All steps done — re-checking everything together on the live site "
                           f"({len(dod)} checks).")
        sweep = verify_all(dod, domain)
    else:
        sweep = _counts([verify_process(cycle)])

    sweep_fails = [r for r in sweep["results"] if r["verdict"] == "fail"]
    plan = _plan(cycle)
    fixes = int(plan.get("regression_fixes") or 0)
    if (website and domain and sweep_fails and fixes < MAX_REGRESSION_FIXES
            and all(t["status"] == "done" for t in _live_tasks(tasks))):
        # A later step broke something an earlier step had verified.
        plan["regression_fixes"] = fixes + 1
        problems = [r.get("user_text") or (r.get("check") or {}).get("description") or "a check failed"
                    for r in sweep_fails]
        store.add_task(
            cycle_id, position=len(tasks), title="Fix what the final check found",
            description=("The final check of the live site found problems in things earlier steps "
                         "had built. Fix them without breaking anything else:\n"
                         + "\n".join(f"- {p}" for p in problems)
                         + "\nEvidence: " + "; ".join(r.get("evidence", "") for r in sweep_fails)[:1500]),
            kind="instruct",
            payload={"regression": True, "summary": "Repair anything the final check found broken"},
            dod_item={"checks": [r["check"] for r in sweep_fails
                                 if (r.get("check") or {}).get("kind") not in CORE_KINDS][:6]} or None)
        store.update_cycle(cycle_id, plan=json.dumps(plan), status="building")
        _say(cycle_id, "🔁 The final check found something that broke along the way:\n"
                       + "\n".join(f"• {p}" for p in problems[:4]) + "\nFixing it before I deliver.")
        _dispatch_next(cycle_id)
        return

    validated = _is_validated(sweep, tasks, domain, website)
    screenshot_path = None
    if website and domain:
        try:
            from services.preview_capture import capture_preview_png
            png = capture_preview_png(f"https://{domain}/")
            if png:
                sp = f"/tmp/cycle_{cycle_id}_receipt.png"
                with open(sp, "wb") as f:
                    f.write(png)
                screenshot_path = sp
        except Exception as exc:
            logger.warning("[ENGINE] receipt screenshot failed: %s", exc)

    receipt = _build_receipt(domain, sweep, tasks, is_website=website)
    if validated:
        # this receipt reported the pending changes and their new checks
        for t in tasks:
            p = _payload(t)
            if t["status"] == "done" and p.get("correction") and not p.get("receipted"):
                p["receipted"] = True
                store.update_task(t["id"], payload=json.dumps(p))
        for d in dod:
            d.pop("new", None)
    store.update_cycle(cycle_id, status="delivered" if validated else "needs_attention",
                       dod=json.dumps(dod), evidence=json.dumps({"sweep": sweep})[:100000])
    _say(cycle_id, receipt)
    _send_telegram(cycle, receipt, screenshot_path)


def _send_telegram(cycle: Dict[str, Any], text: str, photo_path: Optional[str]) -> None:
    """Receipt to the cycle's own Telegram chat. The env TELEGRAM_CHAT_ID
    is the platform owner's chat — only an admin's cycles fall back to it
    (it used to receive every user's receipt)."""
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = cycle.get("telegram_chat_id")
    if not chat_id:
        try:
            from services.rate_limiter import get_user_tier_and_role
            if (get_user_tier_and_role(cycle["user_id"]) or {}).get("role") == "admin":
                chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        except Exception:
            chat_id = None
    if not token or not chat_id:
        return
    try:
        if photo_path and os.path.isfile(photo_path):
            with open(photo_path, "rb") as f:
                httpx.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": text[:1000]},
                    files={"photo": f}, timeout=30,
                )
        else:
            httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       data={"chat_id": chat_id, "text": text}, timeout=30)
    except Exception as exc:
        logger.warning("[ENGINE] telegram receipt failed: %s", exc)


# ── helpers ─────────────────────────────────────────────────────────────

def _ensure_cycle_session(cycle_id: int, project_id: int) -> str:
    """One session per cycle for instruct runs (idempotent)."""
    import uuid as _uuid
    from database_postgres import get_db

    key_field = "cycle_session_key"
    cycle = store.get_cycle(cycle_id)
    _plan = _j(cycle.get("plan"), {})
    existing = _plan.get(key_field)
    if existing:
        return existing

    session_key = str(_uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sessions (project_id, session_key, label, channel, agent_id)
               VALUES (%s, %s, %s, 'webchat', 'main')""",
            (project_id, session_key, f"Dev Cycle {cycle_id}"),
        )
        conn.commit()
    _plan[key_field] = session_key
    store.update_cycle(cycle_id, plan=json.dumps(_plan))
    return session_key


def _session_id(session_key: str) -> int:
    from database_postgres import get_db

    with get_db() as conn:
        row = conn.execute("SELECT id FROM sessions WHERE session_key = %s", (session_key,)).fetchone()
    if row:
        d = dict(row) if not isinstance(row, dict) else row
        return int(d["id"])
    return 0


def _project_type_id(cycle: Dict[str, Any]) -> int:
    """The type of project this cycle drives (1=website, 2=telegram bot,
    3=discord bot, 4=scheduler, 5=agent). New-project cycles default to 1."""
    return int(cycle.get("project_type_id") or 1)


def _is_website(cycle: Dict[str, Any]) -> bool:
    return _project_type_id(cycle) == 1


def _frontend_domain(cycle: Dict[str, Any]) -> str:
    from domain_config import BASE_DOMAIN
    from database_postgres import get_db

    pid = cycle.get("project_id")
    if pid:
        with get_db() as conn:
            row = conn.execute("SELECT domain FROM projects WHERE id = %s", (pid,)).fetchone()
        if row:
            d = dict(row) if not isinstance(row, dict) else row
            if d.get("domain"):
                return f"{d['domain']}.{BASE_DOMAIN}"
    return ""


# ── reconcile (lost-event safety net) ───────────────────────────────────

def reconcile() -> None:
    """Catch what notifications missed: stuck tasks, finished runs, and
    tasks waiting for a re-verify. A cycle busy in an event handler is
    skipped (its lock is held) and picked up on the next pass."""
    for cycle in store.active_cycles():
        lock = _cycle_lock(cycle["id"])
        if not lock.acquire(blocking=False):
            continue
        try:
            _reconcile_cycle(cycle)
        except Exception:
            logger.exception("[RECONCILE] cycle %s failed", cycle["id"])
        finally:
            lock.release()


def _reconcile_cycle(cycle: Dict[str, Any]) -> None:
    cycle_id = cycle["id"]
    if cycle.get("status") != "building":
        return
    tasks = store.get_tasks(cycle_id)
    # Restart-safe finalize: all tasks terminal, none in flight, but the
    # cycle never got its receipt (e.g. the engine died mid-finalize).
    if tasks and all(t["status"] in ("done", "failed") for t in tasks):
        logger.info("[RECONCILE] cycle %s all tasks terminal — finalizing", cycle_id)
        _finalize(cycle_id)
        return
    if tasks and not any(t["status"] in ("in_progress", "under_review") for t in tasks):
        _dispatch_next(cycle_id)  # a todo task with nothing in flight (lost wake-up)
        return

    for task in tasks:
        if task["status"] == "under_review":
            # Checks couldn't run (or the engine died mid-review): verify
            # again. Parked tasks wait for the user's "check again".
            if not _result(task).get("parked"):
                logger.info("[RECONCILE] task %s re-verify", task["id"])
                _review_task(cycle_id, task)
            return
        if task["status"] != "in_progress":
            continue
        if int(task.get("age_s") or 0) > TASK_WALL_CLOCK_MIN * 60:
            store.update_task(task["id"], status="failed",
                              result=json.dumps({"error": "wall-clock timeout"}))
            _say(cycle_id, f"⏰ “{task['title']}” ran over {TASK_WALL_CLOCK_MIN} minutes, so I stopped "
                           f"waiting for it. Reply “retry” to run it again.")
            _dispatch_next(cycle_id)
            return
        # run finished without notify?
        rid = task.get("session_run_id") or task.get("creation_run_id")
        if rid:
            from database_postgres import get_db
            kind = "session" if task.get("session_run_id") else "creation"
            table = "session_chat_runs" if kind == "session" else "project_creation_runs"
            with get_db() as conn:
                row = conn.execute(f"SELECT status FROM {table} WHERE id = %s", (rid,)).fetchone()
            if row:
                st = (dict(row) if not isinstance(row, dict) else row).get("status")
                if st in ("completed", "failed", "cancelled", "interrupted"):
                    logger.info("[RECONCILE] task %s run %s finished (%s) without notify",
                                task["id"], rid, st)
                    _on_run_completed(kind, rid, st)
        return


# ── main loop (async: LISTEN + periodic reconcile) ─────────────────────

async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logger.info("[ENGINE] dev-cycle engine starting")

    import psycopg2
    from services.dev_cycles.notify import open_listen_connection

    conn = None

    def _ensure_listen():
        nonlocal conn
        if conn is None or conn.closed:
            conn = open_listen_connection()
            logger.info("[ENGINE] LISTEN %s connected", CHANNEL)

    last_reconcile = 0.0
    reconcile_job: Optional[Future] = None

    while True:
        try:
            _ensure_listen()

            # psycopg2 sync LISTEN pattern: poll() processes pending
            # notifications into conn.notifies. Poll every 200ms — cheap,
            # no query hits the server (reads the local socket only).
            conn.poll()
            while conn.notifies:
                n = conn.notifies.pop(0)
                logger.info("[ENGINE] event received: %s", (n.payload or "")[:200])
                try:
                    # Off the loop: handlers block for minutes (builds'
                    # verify sweeps, LLM calls); handle_event serialises
                    # per cycle and never raises.
                    _pool.submit(handle_event, json.loads(n.payload))
                except Exception:
                    logger.warning("[ENGINE] bad payload: %s", (n.payload or "")[:200])

            if (time.monotonic() - last_reconcile > RECONCILE_INTERVAL
                    and (reconcile_job is None or reconcile_job.done())):
                last_reconcile = time.monotonic()
                reconcile_job = _pool.submit(reconcile)

            await asyncio.sleep(0.2)

        except psycopg2.Error as exc:
            logger.warning("[ENGINE] listen connection lost (%s) — reconnecting", exc)
            conn = None
            await asyncio.sleep(2)
        except Exception:
            logger.exception("[ENGINE] loop error")
            await asyncio.sleep(2)
