#!/usr/bin/env python3
"""Dev Cycle engine — event-driven orchestrator (LISTEN/NOTIFY).

Wakes on `dev_cycle_events` notifications; 60s reconcile covers lost
events. State transitions per task: todo → in_progress → under_review →
done (verifier gate) | failed (repairs exhausted).

Entry: dev_cycle_engine.py (pm2) → main() here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.dev_cycles import chat_agent, store
from services.dev_cycles.notify import CHANNEL, notify_cycle

logger = logging.getLogger("services.dev_cycles.engine")

RECONCILE_INTERVAL = 60  # seconds — lost-event safety net
TASK_WALL_CLOCK_MIN = 30  # a task stuck in_progress longer than this = failed


# ── event dispatch ──────────────────────────────────────────────────────

def handle_event(payload: Dict[str, Any]) -> None:
    """Route one notification. Never raises (engine must survive bad events)."""
    event = payload.get("event")
    try:
        if event == "cycle_created":
            _on_cycle_created(int(payload["cycle_id"]))
        elif event == "user_message":
            _on_user_message(int(payload["cycle_id"]))
        elif event == "run_completed":
            _on_run_completed(
                kind=str(payload.get("kind")),
                run_id=int(payload.get("run_id") or 0),
                status=str(payload.get("status") or ""),
            )
        else:
            logger.debug("[ENGINE] ignored event %s", event)
    except Exception as exc:
        logger.exception("[ENGINE] event %s failed: %s", event, exc)


def _on_cycle_created(cycle_id: int) -> None:
    cycle = store.get_cycle(cycle_id)
    if not cycle:
        return
    if cycle.get("project_id"):
        store.add_message(cycle_id, "agent",
                          "Hi! I'm your delivery engineer. This cycle drives your existing "
                          "project. Tell me what to change or improve — I'll plan the edits, "
                          "apply them, verify the site still works, and send you the result.")
    else:
        store.add_message(cycle_id, "agent",
                          "Hi! I'm your delivery engineer. Describe the website you want — "
                          "purpose, pages, style, any assets (SVG logos, images) — and I'll "
                          "plan the build, execute it task by task, verify it works, and "
                          "send you the live link.")
    store.update_cycle(cycle_id, status="intake")


def _on_user_message(cycle_id: int) -> None:
    """Intake turn: clarify until ready, then plan → tasks → first dispatch."""
    cycle = store.get_cycle(cycle_id)
    if not cycle:
        return
    status = cycle.get("status")

    if status in ("delivered", "failed"):
        _handle_correction(cycle)
        return
    if status == "building":
        # building: a correction or new task may have been added — dispatch
        # the next task if nothing is in flight (the engine's dispatch_next
        # already checks for in-flight tasks and skips if so)
        _dispatch_next(cycle_id)
        return
    if status != "intake":
        return

    mode = "existing" if cycle.get("project_id") else "new"
    history = [{"role": m["role"], "content": m["content"]}
               for m in store.get_messages(cycle_id) if m["role"] in ("user", "agent")]
    verdict = chat_agent.intake_turn(history, mode)
    # Existing-mode shortcut: the change request is usually clear from the
    # first message; after 2 user replies force ready (the model oscillates
    # on ready-vs-ask and the dead-loop tie-break just repeats a question).
    user_turns = sum(1 for m in history if m["role"] == "user")
    if mode == "existing" and user_turns >= 2:
        verdict["ready"] = True
        verdict["questions"] = []
    accum = (cycle.get("requirement_accum") or "")
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    store.update_cycle(cycle_id, requirement_accum=(accum + "\n" + last_user).strip()[:20000])

    if not verdict["ready"]:
        q = " ".join(verdict["questions"]) or "Could you share a bit more detail?"
        store.add_message(cycle_id, "agent", q)
        return

    # Ready → plan (frozen) → tasks → dispatch first
    store.update_cycle(cycle_id, status="planning")
    requirement = cycle.get("requirement_accum") or last_user
    plan = chat_agent.generate_plan(requirement, mode)
    dod = plan["dod"]
    store.update_cycle(cycle_id, plan=json.dumps(plan), dod=json.dumps(dod), status="building")

    titles = []
    for i, t in enumerate(plan["tasks"]):
        store.add_task(cycle_id, position=i, title=t.get("title", f"Task {i+1}"),
                       description=t.get("description", ""), kind=t.get("kind", "instruct"))
        titles.append(f"{i+1}. {t.get('title', '')}")
    store.add_message(cycle_id, "agent",
                      f"📋 Plan locked — {len(plan['tasks'])} task(s), {len(dod)} checks:\n"
                      + "\n".join(titles)
                      + "\n\nStarting the build. Reply anytime to adjust.")

    _dispatch_next(cycle_id)


def _handle_correction(cycle: Dict[str, Any]) -> None:
    """A message on a delivered/building cycle → append a correction task."""
    cycle_id = cycle["id"]
    msgs = store.get_messages(cycle_id)
    last_user = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
    if not last_user:
        return
    pos = len(store.get_tasks(cycle_id))
    task = store.add_task(cycle_id, position=pos, title=f"Correction: {last_user[:60]}",
                          description=last_user[:4000], kind="instruct")
    store.update_cycle(cycle_id, status="building")
    store.add_message(cycle_id, "agent", f"Got it — added to the board as task {pos + 1}.")
    # Only dispatch if nothing is in flight
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
    store.add_message(cycle_id, "agent", f"🔨 **{task['title']}** — in progress")

    try:
        if task["kind"] == "create":
            _dispatch_create(cycle_id, task)
        else:
            _dispatch_instruct(cycle_id, task)
    except Exception as exc:
        logger.exception("[ENGINE] dispatch failed task %s", task["id"])
        store.update_task(task["id"], status="failed", result=json.dumps({"error": str(exc)[:500]}))
        store.add_message(cycle_id, "agent",
                          f"⚠️ Task '{task['title']}' could not start: {exc}. Skipping — reply to retry.")
        _dispatch_next(cycle_id)


def _dispatch_create(cycle_id: int, task: Dict[str, Any]) -> None:
    from services.project_creation_runs import enqueue_project_creation_run
    import secrets as _secrets

    cycle = store.get_cycle(cycle_id)
    name = (cycle.get("plan") or {}).get("name") or f"cycle-{cycle_id}-{_secrets.token_hex(2)}"
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
        _dispatch_next(cycle_id)
        return

    session_key = _ensure_cycle_session(cycle_id, project_id)
    res = create_run(
        session_id=_session_id(session_key), session_key=session_key,
        project_id=project_id, user_id=cycle["user_id"], channel="webchat",
        mode="dream", user_message=task["description"],
        session_context="", billing_user_id=None,
    )
    store.update_task(task["id"], session_run_id=res.get("id"))


# ── run completion ──────────────────────────────────────────────────────

def _on_run_completed(kind: str, run_id: int, status: str) -> None:
    """A creation or session run finished → move its task to review."""
    if not run_id:
        return
    task = store.find_task_by_run(run_id, kind)
    if not task:
        return  # not a cycle-managed run

    cycle_id = task["cycle_id"]
    if status != "completed":
        store.update_task(task["id"], status="failed",
                          result=json.dumps({"run_status": status}))
        store.add_message(cycle_id, "agent",
                          f"⚠️ **{task['title']}** — run {status}. Reply to retry.")
        _dispatch_next(cycle_id)
        return

    store.update_task(task["id"], status="under_review")
    _review_task(cycle_id, task)


def _compute_outcome(task: Dict[str, Any], cycle: Dict[str, Any], dod: list) -> Dict[str, Any]:
    """Run the task's checks once and fold into a single outcome dict."""
    frontend_domain = _frontend_domain(cycle)
    CORE_KINDS = {"url_200", "console_clean"}

    if task.get("dod_item"):
        # single-check task (instruct tasks with a specific dod_item)
        from services.dev_cycles.verifier import verify
        outcome = verify(task["dod_item"], frontend_domain)
        outcome["summary"] = {"results": [outcome],
                              "passed": 1 if outcome["verdict"] == "pass" else 0,
                              "failed": 1 if outcome["verdict"] == "fail" else 0,
                              "unverified": 1 if outcome["verdict"] == "unverified" else 0}
        return outcome

    # full DoD (create-task / instruct sweeps): core-vs-content split
    from services.dev_cycles.verifier import verify_all
    outcome_all = verify_all(dod, frontend_domain)
    core_fail = sum(1 for r in outcome_all["results"]
                    if r["check"].get("kind") in CORE_KINDS and r["verdict"] == "fail")
    core_unverified = sum(1 for r in outcome_all["results"]
                          if r["check"].get("kind") in CORE_KINDS and r["verdict"] == "unverified")
    content_fail = sum(1 for r in outcome_all["results"]
                       if r["check"].get("kind") not in CORE_KINDS and r["verdict"] == "fail")
    if core_fail > 0:
        verdict = "fail"
    elif core_unverified > 0:
        # site reachability itself is unknown — NOT a pass
        verdict = "unverified"
    else:
        verdict = "pass"
    return {
        "verdict": verdict,
        "evidence": json.dumps(outcome_all)[:800],
        "summary": outcome_all,
        "core_fail": core_fail,
        "content_fail": content_fail,
    }


def _review_task(cycle_id: int, task: Dict[str, Any]) -> None:
    """Verifier gate: under_review → done | back to in_progress (repair).

    Core checks (url_200, console_clean) are BLOCKERS — if the site doesn't
    load or has console errors, the task genuinely fails and triggers repair.
    Content checks (dom_exists, text_present) are QUALITY SIGNALS — failures
    go into the receipt as warnings, but don't block the task from
    completing. This prevents a 8/9-passing site from being marked "failed"
    because one decorative element is missing after 2 repair attempts.
    """
    cycle = store.get_cycle(cycle_id)
    dod = cycle.get("dod") or []
    if isinstance(dod, str):
        dod = json.loads(dod)

    outcome = _compute_outcome(task, cycle, dod)
    if outcome["verdict"] == "unverified":
        # Infra flake (CDP/browser down) — NEVER re-run the build for a
        # checker problem (token burn). One retry after a settle pause;
        # still unverified → park as todo until the next trigger.
        time.sleep(20)
        outcome = _compute_outcome(task, cycle, dod)
        if outcome["verdict"] == "unverified":
            store.update_task(task["id"], status="todo",
                              result=json.dumps({"verdict": "unverified", "evidence": outcome.get("evidence", "")}))
            store.add_message(cycle_id, "agent",
                              f"⏳ **{task['title']}** — checks couldn't run (infra). "
                              f"Parked — send a message to retry.")
            return

    if outcome["verdict"] == "pass":
        warnings = ""
        summary = outcome.get("summary") or {}
        content_fail = summary.get("failed", 0) if not outcome.get("core_fail") else outcome.get("content_fail", 0)
        if content_fail and content_fail > 0:
            failed_descs = [r["check"].get("description", r["check"].get("kind", "?"))
                           for r in summary.get("results", []) if r["verdict"] == "fail"]
            warnings = f" (⚠️ {content_fail} minor check{'s' if content_fail > 1 else ''}: {', '.join(failed_descs[:3])})"
        store.update_task(task["id"], status="done",
                          result=json.dumps({"verdict": "pass", "evidence": outcome.get("evidence", ""),
                                             "content_warnings": content_fail}))
        store.add_message(cycle_id, "agent",
                          f"✅ **{task['title']}** — core checks passed{warnings}.")
        _dispatch_next(cycle_id)
        return

    # core fail → repair (≤2) or give up
    repairs = int(task.get("repair_count") or 0)
    if repairs >= 2:
        store.update_task(task["id"], status="failed",
                          result=json.dumps({"verdict": "fail", "evidence": outcome.get("evidence", ""),
                                             "repairs": repairs}))
        store.add_message(cycle_id, "agent",
                          f"❌ **{task['title']}** — core checks failed after {repairs} repairs. "
                          f"Evidence: {str(outcome.get('evidence'))[:300]}")
        _dispatch_next(cycle_id)
        return

    failed_check = task.get("dod_item") or {"kind": "multi", "description": "one or more DoD items",
                                            "params": {}}
    instruction = chat_agent.repair_instruction(
        task["title"], failed_check, str(outcome.get("evidence", "")))
    store.update_task(task["id"], status="todo", repair_count=repairs + 1,
                      result=json.dumps({"verdict": "fail", "evidence": outcome.get("evidence", "")}))
    # Replace the task description with the repair instruction
    store.update_task(task["id"], description=instruction, kind="instruct")
    store.add_message(cycle_id, "agent",
                      f"🔁 **{task['title']}** — check failed, repairing ({repairs + 1}/2).")
    _dispatch_next(cycle_id)


def _finalize(cycle_id: int) -> None:
    """All tasks terminal → final DoD sweep + screenshot + Telegram receipt."""
    from services.dev_cycles.verifier import verify_all

    cycle = store.get_cycle(cycle_id)
    domain = _frontend_domain(cycle)
    dod = cycle.get("dod") or []
    if isinstance(dod, str):
        dod = json.loads(dod)
    sweep = verify_all(dod, domain)

    evidence: Dict[str, Any] = {"sweep": sweep}
    screenshot_path = None
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

    # Split results into core (blocker) vs content (warning) for the receipt
    CORE_KINDS = {"url_200", "console_clean"}
    core_fails = [r for r in sweep["results"]
                  if r["check"].get("kind") in CORE_KINDS and r["verdict"] == "fail"]
    content_fails = [r for r in sweep["results"]
                     if r["check"].get("kind") not in CORE_KINDS and r["verdict"] == "fail"]
    failed_tasks = [t["title"] for t in store.get_tasks(cycle_id) if t["status"] == "failed"]
    receipt = (f"📦 Dev cycle delivered\n"
               f"🌐 https://{domain}\n"
               f"✅ {sweep['passed']}/{len(dod)} checks passed")
    if content_fails:
        descs = [r["check"].get("description", r["check"].get("kind", "?")) for r in content_fails]
        receipt += f"\n⚠️ Minor: {', '.join(descs[:4])}"
    if sweep["unverified"]:
        receipt += f"\n⏳ Unverified: {sweep['unverified']}"
    if core_fails or failed_tasks:
        receipt += f"\n❌ Issues: {', '.join(failed_tasks) if failed_tasks else 'core checks failed'}"
    store.update_cycle(cycle_id, status="delivered",
                       evidence=json.dumps(evidence)[:100000])
    store.add_message(cycle_id, "agent", receipt)

    _send_telegram(cycle, receipt, screenshot_path)


def _send_telegram(cycle: Dict[str, Any], text: str, photo_path: Optional[str]) -> None:
    """Receipt via the project's telegram creds if present (env pattern)."""
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = cycle.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
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
    _plan = cycle.get("plan") or {}
    if isinstance(_plan, str):
        _plan = json.loads(_plan)
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
    """Catch what notifications missed: stuck tasks, finished runs, wake-ups."""
    now = datetime.now(timezone.utc)
    for cycle in store.active_cycles():
        cycle_id = cycle["id"]
        # Restart-safe finalize: all tasks terminal, none in flight, but the
        # cycle never got its receipt (e.g. the engine died mid-finalize).
        if cycle.get("status") == "building":
            tasks = store.get_tasks(cycle_id)
            if tasks and all(t["status"] in ("done", "failed") for t in tasks):
                logger.info("[RECONCILE] cycle %s all tasks terminal — finalizing", cycle_id)
                _finalize(cycle_id)
                continue
        for task in store.get_tasks(cycle_id):
            if task["status"] not in ("in_progress", "under_review"):
                continue
            # wall clock
            try:
                started = task.get("updated_at")
                if started and (now - started).total_seconds() > TASK_WALL_CLOCK_MIN * 60:
                    store.update_task(task["id"], status="failed",
                                      result=json.dumps({"error": "wall-clock timeout"}))
                    store.add_message(cycle_id, "agent",
                                      f"⏰ Task '{task['title']}' timed out. Reply to retry.")
                    _dispatch_next(cycle_id)
                    continue
            except Exception:
                pass
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

    loop = asyncio.get_event_loop()
    last_reconcile = 0.0

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
                    handle_event(json.loads(n.payload))
                except Exception:
                    logger.warning("[ENGINE] bad payload: %s", (n.payload or "")[:200])

            if time.monotonic() - last_reconcile > RECONCILE_INTERVAL:
                last_reconcile = time.monotonic()
                await loop.run_in_executor(None, reconcile)

            await asyncio.sleep(0.2)

        except psycopg2.Error as exc:
            logger.warning("[ENGINE] listen connection lost (%s) — reconnecting", exc)
            conn = None
            await asyncio.sleep(2)
        except Exception:
            logger.exception("[ENGINE] loop error")
            await asyncio.sleep(2)
