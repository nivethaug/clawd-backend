#!/usr/bin/env python3
"""Dev Cycle engine — event-driven orchestrator (LISTEN/NOTIFY).

Wakes on `dev_cycle_events` notifications; 60s reconcile covers lost
events. State transitions per task: todo → in_progress → under_review →
done (verifier gate) | failed (repairs exhausted).

Events are handled on a small thread pool, serialised per cycle by a lock,
so one cycle's verify sweep or LLM call never delays another user's reply.

Entry: dev_cycle_engine.py (pm2) → main() here.
"""

from __future__ import annotations

import asyncio
import hashlib
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
SWEEP_REUSE_S = 90  # the last task's sweep doubles as the receipt sweep
CORE_KINDS = {"url_200", "console_clean"}

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


def _dod_sig(dod: List[Dict[str, Any]]) -> str:
    raw = json.dumps([[d.get("kind"), d.get("params") or {}] for d in dod], sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


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
             "Tell me what to change on your site. I'll make the edit, check the live "
             "site still works, and confirm when it's done.")
    else:
        _say(cycle_id,
             "Tell me what you want to build — one sentence is enough (for example "
             "“a landing page for my bakery with a contact form”). I'll fill in sensible "
             "defaults, build it, check it in a real browser, and send you the link.")
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
    """Intake turn: clarify (rarely) until ready, then plan → tasks → first
    dispatch. On a planned cycle every message is a follow-up."""
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
        # cycle lock) — queue the message instead of dropping it, and let
        # reconcile/dispatch recover the board (first-review bug 3).
        _say(cycle_id, "Noted — I'll add that once the plan is set.")
        store.update_cycle(cycle_id, status="building")
        _dispatch_next(cycle_id)
        return
    if status in ("delivered", "failed", "building"):
        _handle_followup(cycle, msg["content"])
        return
    if status != "intake":
        return

    mode = "existing" if cycle.get("project_id") else "new"
    history = [{"role": m["role"], "content": m["content"]}
               for m in msgs if m["role"] in ("user", "agent") and m["id"] <= msg["id"]]
    verdict = chat_agent.intake_turn(history, mode)
    # Hard cap for both modes: after the client has answered once, build
    # with defaults — never a second round of questions.
    user_turns = sum(1 for m in history if m["role"] == "user")
    if user_turns >= 2:
        verdict["ready"] = True
        verdict["questions"] = []
    requirement = _requirement_text(history)[:20000]
    store.update_cycle(cycle_id, requirement_accum=requirement)

    if not verdict["ready"]:
        _say(cycle_id, " ".join(verdict["questions"]) or "What would you like to build?")
        return

    # Ready → plan (frozen until a correction patches the DoD) → tasks
    store.update_cycle(cycle_id, status="planning")
    plan = chat_agent.generate_plan(requirement, mode)
    dod = plan["dod"]
    store.update_cycle(cycle_id, plan=json.dumps(plan), dod=json.dumps(dod), status="building")

    lines = []
    for i, t in enumerate(plan["tasks"]):
        title = str(t.get("title") or f"Task {i + 1}")[:120]
        summary = str(t.get("summary") or "").strip()[:140]
        store.add_task(cycle_id, position=i, title=title,
                       description=t.get("description", ""), kind=t.get("kind", "instruct"),
                       payload={"summary": summary} if summary else None)
        lines.append(f"{i + 1}. {title}" + (f" — {summary}" if summary else ""))
    _say(cycle_id, _plan_message(plan, lines))

    _dispatch_next(cycle_id)


def _plan_message(plan: Dict[str, Any], lines: List[str]) -> str:
    msg = "📋 Here's the plan:\n" + "\n".join(lines)
    if plan.get("assumptions"):
        msg += "\n\nAssumed: " + ", ".join(plan["assumptions"]) + "."
    shows = [str(d.get("description")) for d in plan["dod"]
             if d.get("kind") not in CORE_KINDS and d.get("description")]
    msg += "\n\nWhen it's built I'll open it in a real browser and check that it loads with no errors"
    msg += (", and shows: " + ", ".join(shows[:6]) + ".") if shows else "."
    eta = _eta_minutes(plan["tasks"])
    if eta:
        msg += f"\nBuilds like this usually take about {eta} min."
    return msg + "\n\nStarting now — reply anytime to change something and I'll queue it."


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
        failed = [t for t in tasks if t["status"] == "failed"]
        if not failed:
            if waiting:
                _recheck(cycle_id, waiting[0])
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
    """A change request on a planned cycle → a correction task (or folded
    into the one already queued), and the DoD is patched to match."""
    cycle_id = cycle["id"]
    instruction = text[:4000]
    if NOTES_RE.search(text):
        notes = [n for n in _open_notes(cycle) if n][:6]
        if notes:
            instruction += "\n\nOpen notes from the last check of the live site:\n" + \
                           "\n".join(f"- {n}" for n in notes)

    # Several quick tweaks = one build and one receipt, not three.
    queued = next((t for t in tasks if t["status"] == "todo" and _payload(t).get("correction")
                   and not int(t.get("repair_count") or 0)), None)
    if queued:
        p = _payload(queued)
        p["requests"] = (p.get("requests") or []) + [text[:300]]
        store.update_task(queued["id"], payload=json.dumps(p),
                          description=((queued.get("description") or "") + "\n\nAlso: " + instruction)[:8000])
        _say(cycle_id, "Got it — added to the change that's queued next.")
    else:
        store.add_task(cycle_id, position=len(tasks), title=f"Change: {text[:60]}",
                       description=instruction, kind="instruct",
                       payload={"correction": True, "requests": [text[:300]]})
        if in_flight:
            _say(cycle_id, f"Got it — queued right after “{in_flight['title']}”, which is running now.")
        else:
            _say(cycle_id, "Got it — making that change now, then re-checking the live site.")
    store.update_cycle(cycle_id, status="building")

    # Keep the checklist true to what the user now wants: without this the
    # receipt warns about exactly the thing they asked to change.
    dod = _dod(cycle)
    patched = chat_agent.patch_dod(dod, text)
    if patched is None:
        for d in dod:
            if d.get("kind") not in CORE_KINDS:
                d["predates_change"] = True
        patched = dod
    store.update_cycle(cycle_id, dod=json.dumps(patched))

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
        store.update_task(task["id"], status="failed", result=json.dumps({"error": str(exc)[:500]}))
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
        store.update_task(task["id"], status="failed",
                          result=json.dumps({"run_status": status}))
        why = _RUN_STATUS_WORDS.get(status, "the build didn't complete")
        _say(cycle_id, f"⚠️ “{task['title']}” didn't finish ({why}). Reply “retry” to run it again.")
        _dispatch_next(cycle_id)
        return

    store.update_task(task["id"], status="under_review",
                      result=json.dumps({"phase": "verifying"}))
    task["result"] = {}
    n = 1 if task.get("dod_item") else len(_dod(store.get_cycle(cycle_id) or {}))
    _say(cycle_id, f"🔎 Build finished — checking the live site in a real browser "
                   f"({n} check{'s' if n != 1 else ''}).")
    _review_task(cycle_id, task)


def _compute_outcome(task: Dict[str, Any], cycle: Dict[str, Any], dod: list,
                     on_progress=None) -> Dict[str, Any]:
    """Run the task's checks once and fold into a single outcome dict.

    Core checks (url_200, console_clean) decide the verdict; content checks
    only ever produce notes for the receipt.
    """
    from services.dev_cycles.verifier import verify, verify_all

    frontend_domain = _frontend_domain(cycle)
    single = _j(task.get("dod_item"), {})
    if single:
        r = verify(single, frontend_domain)
        summary = {"results": [r],
                   "passed": 1 if r["verdict"] == "pass" else 0,
                   "failed": 1 if r["verdict"] == "fail" else 0,
                   "unverified": 1 if r["verdict"] == "unverified" else 0}
    else:
        summary = verify_all(dod, frontend_domain, on_progress)

    def _pick(core: bool, verdict: str) -> list:
        return [r for r in summary["results"]
                if ((r["check"].get("kind") in CORE_KINDS) == core) and r["verdict"] == verdict]

    core_fails = _pick(True, "fail")
    core_unverified = _pick(True, "unverified")
    if core_fails:
        verdict = "fail"
    elif core_unverified or (summary["results"] and summary["unverified"] == len(summary["results"])):
        # site reachability itself is unknown — NOT a pass
        verdict = "unverified"
    else:
        verdict = "pass"
    # Evidence = only what explains the verdict (a dump of every result
    # used to bury the failing check under passing ones).
    explains = core_fails or core_unverified or _pick(False, "unverified")
    evidence = "; ".join(f"{r['check'].get('kind')}: {r['evidence']}" for r in explains)[:800]
    return {
        "verdict": verdict,
        "evidence": evidence,
        "summary": summary,
        "core_fails": core_fails,
        "content_fails": _pick(False, "fail"),
        "full": not single,
    }


def _review_task(cycle_id: int, task: Dict[str, Any]) -> None:
    """Verifier gate: under_review → done | back to todo (repair) | stays
    under_review (checks couldn't run).

    Core checks (url_200, console_clean) are BLOCKERS — if the site doesn't
    load or has console errors, the task genuinely fails and triggers repair.
    Content checks (dom_exists, text_present) are QUALITY SIGNALS — failures
    go into the receipt as notes, but don't block the task from completing.

    Unverified (browser/CDP down) is never a pass and never re-runs the
    build: the task waits in under_review and reconcile() re-verifies it,
    up to MAX_RECHECKS times, before parking it for a user "check again".
    """
    cycle = store.get_cycle(cycle_id)
    dod = _dod(cycle)
    rechecks = int(_result(task).get("recheck_count") or 0)

    def _progress(i: int, total: int, item: Dict[str, Any]) -> None:
        store.update_task(task["id"], result=json.dumps({
            "phase": "verifying", "step": i, "total": total,
            "label": str(item.get("description") or "")[:80],
            "recheck_count": rechecks}))

    outcome = _compute_outcome(task, cycle, dod, _progress)

    if outcome["verdict"] == "unverified":
        rechecks += 1
        parked = rechecks > MAX_RECHECKS
        store.update_task(task["id"], status="under_review", result=json.dumps({
            "verdict": "unverified", "evidence": outcome["evidence"],
            "recheck_count": rechecks, "parked": parked}))
        if rechecks == 1:
            _say(cycle_id, f"⏳ “{task['title']}” is built, but my browser check couldn't run just now. "
                           f"I'll keep re-checking automatically — nothing needed from you.")
        elif parked:
            domain = _frontend_domain(cycle)
            link = f": https://{domain}" if domain else ""
            _say(cycle_id, f"I still can't check the site, though the build itself finished{link}\n"
                           f"Reply “check again” whenever you like.")
        return

    if outcome["verdict"] == "pass":
        notes = len(outcome["content_fails"])
        result = {"verdict": "pass", "evidence": outcome["evidence"], "content_warnings": notes}
        if outcome["full"]:
            # lets _finalize reuse this sweep instead of running it twice
            result.update({"sweep": outcome["summary"], "sweep_at": time.time(),
                           "dod_sig": _dod_sig(dod)})
        store.update_task(task["id"], status="done", result=json.dumps(result)[:100000])
        tail = f" ({notes} note{'s' if notes > 1 else ''} for the summary.)" if notes else ""
        _say(cycle_id, f"✅ {task['title']} — done and loading cleanly.{tail}")
        _dispatch_next(cycle_id)
        return

    # core fail → repair (≤2) or give up
    failing = outcome["core_fails"][0]
    reason = failing.get("user_text") or "The site isn't loading cleanly"
    repairs = int(task.get("repair_count") or 0)
    if repairs >= MAX_REPAIRS:
        store.update_task(task["id"], status="failed",
                          result=json.dumps({"verdict": "fail", "evidence": outcome["evidence"],
                                             "repairs": repairs}))
        _say(cycle_id, f"❌ “{task['title']}” — still not working after {repairs} fixes. {reason}. "
                       f"Reply “retry” to try again, or tell me what to change.")
        _dispatch_next(cycle_id)
        return

    try:
        instruction = chat_agent.repair_instruction(task["title"], failing["check"], outcome["evidence"])
    except Exception as exc:
        logger.warning("[ENGINE] repair instruction failed: %s", exc)
        instruction = ""
    if not instruction:
        instruction = f"The live site has a problem — fix it: {outcome['evidence'][:600]}"
    payload = _payload(task)
    payload["repair_instruction"] = instruction
    store.update_task(task["id"], status="todo", repair_count=repairs + 1, kind="instruct",
                      payload=json.dumps(payload),
                      result=json.dumps({"verdict": "fail", "evidence": outcome["evidence"]}))
    _say(cycle_id, f"🔁 The site isn't working cleanly yet — {_lower_first(reason)}. "
                   f"Fixing it (attempt {repairs + 1} of {MAX_REPAIRS}).")
    _dispatch_next(cycle_id)


# ── receipt ─────────────────────────────────────────────────────────────

def _fresh_sweep(tasks: List[Dict[str, Any]], dod: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The last task's own sweep, if it just ran against this same DoD."""
    sig = _dod_sig(dod)
    for t in reversed(tasks):
        res = _result(t)
        if (t["status"] == "done" and res.get("sweep") and res.get("dod_sig") == sig
                and time.time() - float(res.get("sweep_at") or 0) < SWEEP_REUSE_S):
            return res["sweep"]
    return None


def _build_receipt(domain: str, sweep: Dict[str, Any], tasks: List[Dict[str, Any]]) -> str:
    """The delivery message. First line states the real outcome; notes are
    plain-language and clearly non-blocking; never a bare x/y score."""
    results = sweep.get("results") or []

    def _is_core(r) -> bool:
        return (r.get("check") or {}).get("kind") in CORE_KINDS

    core_fails = [r for r in results if _is_core(r) and r["verdict"] == "fail"]
    core_unverified = [r for r in results if _is_core(r) and r["verdict"] == "unverified"]
    content = [r for r in results if not _is_core(r)]
    content_fails = [r for r in content if r["verdict"] == "fail"]
    content_passed = sum(1 for r in content if r["verdict"] == "pass")
    content_unverified = sum(1 for r in content if r["verdict"] == "unverified")
    failed_tasks = [t["title"] for t in tasks
                    if t["status"] == "failed" and _result(t).get("error") != "cancelled"]
    corrections = [t for t in tasks if t["status"] == "done"
                   and _payload(t).get("correction") and not _payload(t).get("receipted")]
    link = f"https://{domain}"

    if not domain:
        return ("⚠️ The site wasn't created\n"
                "The build didn't finish, so there's no link yet.\n"
                "Reply “retry” to build it again.")
    if core_fails:
        why = ". ".join(r.get("user_text") or "The site isn't loading cleanly" for r in core_fails)
        return (f"⚠️ Built, but not working yet\n{link}\n{why}.\n"
                "Reply “retry” and I'll have another go, or tell me what to change.")
    if core_unverified:
        return (f"⏳ Built — but I couldn't check it\n{link}\n"
                "My browser check couldn't run, so this one is unconfirmed.\n"
                "Reply “check again” anytime.")

    lines: List[str] = []
    if corrections:
        requests = [r for t in corrections for r in (_payload(t).get("requests") or [])]
        if len(requests) == 1:
            lines.append(f"✅ Change is live: “{requests[0][:80]}”")
        else:
            lines.append(f"✅ Your {len(requests) or len(corrections)} changes are live")
        lines.append(link)
        confirmed = [r.get("user_text") for r in content
                     if r["verdict"] == "pass" and (r.get("check") or {}).get("new") and r.get("user_text")]
        if confirmed:
            lines.append("Confirmed on the page: " + "; ".join(confirmed[:3]) + ".")
        lines.append("The site still loads cleanly, with no errors.")
    else:
        lines.append("✅ Your site is live")
        lines.append(link)
        checked = content_passed + len(content_fails)
        if checked:
            lines.append(f"Checked in a real browser: loads, no errors, "
                         f"{content_passed} of {checked} page checks.")
        else:
            lines.append("Checked in a real browser: it loads with no errors.")

    if content_fails:
        lines.append("Worth a look (not blocking):")
        for r in content_fails[:4]:
            note = r.get("user_text") or (r.get("check") or {}).get("description") or "a page check"
            if (r.get("check") or {}).get("predates_change"):
                note += " (this check predates your latest change — it may be outdated)"
            lines.append(f"• {note}")
        if len(content_fails) > 4:
            lines.append(f"• …and {len(content_fails) - 4} more")
    if content_unverified:
        lines.append(f"{content_unverified} page check{'s' if content_unverified > 1 else ''} "
                     f"couldn't run this time.")
    if failed_tasks:
        lines.append("Didn't finish: " + ", ".join(f"“{t}”" for t in failed_tasks[:3])
                     + " — reply “retry” to run it again.")
    if content_fails:
        lines.append("Reply “fix these” and I'll sort them out, or tell me what to change.")
    else:
        lines.append("Reply to change anything.")
    return "\n".join(lines)


def _finalize(cycle_id: int, force_sweep: bool = False) -> None:
    """All tasks terminal → final DoD sweep + screenshot + receipt."""
    from services.dev_cycles.verifier import verify_all

    cycle = store.get_cycle(cycle_id)
    domain = _frontend_domain(cycle)
    dod = _dod(cycle)
    tasks = store.get_tasks(cycle_id)
    sweep = None if force_sweep else _fresh_sweep(tasks, dod)
    if sweep is None:
        if domain:
            _say(cycle_id, "🔎 Final check of the live site…")
        sweep = verify_all(dod, domain)

    evidence: Dict[str, Any] = {"sweep": sweep}
    screenshot_path = None
    if domain:
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

    receipt = _build_receipt(domain, sweep, tasks)

    # This receipt reported the pending corrections and their new checks.
    for t in tasks:
        p = _payload(t)
        if t["status"] == "done" and p.get("correction") and not p.get("receipted"):
            p["receipted"] = True
            store.update_task(t["id"], payload=json.dumps(p))
    for d in dod:
        d.pop("new", None)
    store.update_cycle(cycle_id, status="delivered", dod=json.dumps(dod),
                       evidence=json.dumps(evidence)[:100000])
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
