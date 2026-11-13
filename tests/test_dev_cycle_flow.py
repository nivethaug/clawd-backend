"""Dev Cycle concept: clarify → confirm → micro tasks with their own checks
→ execute / verify / repair → deliver only when validated, else notify."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402,F401

import services.dev_cycles.chat_agent as ca  # noqa: E402
import services.dev_cycles.engine as eng  # noqa: E402


# ── fake store ──────────────────────────────────────────────────────────

class FakeStore:
    def __init__(self, cycle, tasks=None, messages=None):
        self.cycle = dict(cycle)
        self.tasks = [dict(t) for t in (tasks or [])]
        self.messages = list(messages or [])
        self.said = []

    def get_cycle(self, _cid):
        return self.cycle

    def update_cycle(self, _cid, **f):
        self.cycle.update(f)

    def get_tasks(self, _cid):
        return self.tasks

    def add_task(self, cycle_id, position, title, description, kind, payload=None, dod_item=None):
        t = {"id": 100 + len(self.tasks), "cycle_id": cycle_id, "position": position, "title": title,
             "description": description, "kind": kind, "status": "todo", "repair_count": 0,
             "payload": json.dumps(payload or {}), "result": "{}",
             "dod_item": json.dumps(dod_item) if dod_item else None}
        self.tasks.append(t)
        return t

    def update_task(self, tid, **f):
        for t in self.tasks:
            if t["id"] == tid:
                t.update(f)

    def get_messages(self, _cid, limit=200):
        return self.messages

    def add_message(self, _cid, _role, content, meta=None):
        self.said.append(content)


def _install(monkeypatch, fs):
    for name in ("get_cycle", "update_cycle", "get_tasks", "add_task", "update_task",
                 "get_messages", "add_message"):
        monkeypatch.setattr(eng.store, name, getattr(fs, name))


def _cycle(**kw):
    c = {"id": 7, "user_id": 1, "status": "intake", "project_id": None, "project_type_id": 1,
         "plan": {}, "dod": [], "requirement_accum": "", "evidence": None, "telegram_chat_id": None}
    c.update(kw)
    return c


def _r(kind, verdict, desc="", user_text="", **params):
    return {"verdict": verdict, "evidence": f"{kind} {verdict}", "user_text": user_text,
            "check": {"kind": kind, "params": params, "description": desc}}


# ── 1. discovery + confirmation ─────────────────────────────────────────

def test_intake_questions_carry_defaults(monkeypatch):
    monkeypatch.setattr(ca, "_chat", lambda *a, **k: json.dumps({
        "ready": False,
        "questions": [{"q": "What's the bakery called?", "default": "Crumb & Co"},
                      {"q": "Where should the contact form send?", "default": "your email"}],
        "spec": {"summary": "Bakery landing page", "scope": ["Home", "Contact"]}}))
    v = ca.intake_turn([{"role": "user", "content": "a website for my bakery"}], "new")
    assert v["ready"] is False
    assert v["questions"][0] == {"q": "What's the bakery called?", "default": "Crumb & Co"}
    assert v["spec"]["scope"] == ["Home", "Contact"]


def test_discovery_asks_then_stays_in_intake(monkeypatch):
    fs = FakeStore(_cycle(), messages=[{"id": 1, "role": "user", "content": "a site for my bakery"}])
    _install(monkeypatch, fs)
    monkeypatch.setattr(eng.chat_agent, "intake_turn", lambda *a, **k: {
        "ready": False, "questions": [{"q": "Bakery name?", "default": "Crumb & Co"}],
        "spec": {"summary": "Bakery site"}, "missing": []})
    eng._on_user_message(7, 1)
    assert fs.cycle["status"] == "intake"
    assert "Bakery name?" in fs.said[-1] and "Suggested: Crumb & Co" in fs.said[-1]
    assert json.loads(fs.cycle["plan"])["spec"]["summary"] == "Bakery site"


def test_ready_shows_spec_and_waits_for_confirmation(monkeypatch):
    fs = FakeStore(_cycle(), messages=[{"id": 1, "role": "user", "content": "landing page for Crumb & Co"}])
    _install(monkeypatch, fs)
    started = []
    monkeypatch.setattr(eng, "_start_build", lambda cid: started.append(cid))
    monkeypatch.setattr(eng.chat_agent, "intake_turn", lambda *a, **k: {
        "ready": True, "questions": [],
        "spec": {"summary": "Landing page for Crumb & Co", "scope": ["Hero", "Contact form"],
                 "acceptance": ["Contact form on the home page"]}, "missing": []})
    eng._on_user_message(7, 1)
    assert fs.cycle["status"] == "confirming"
    assert fs.said[-1].startswith("📝 Here's what I'll build")
    assert "• Contact form" in fs.said[-1] and "Done means:" in fs.said[-1]
    assert started == []  # nothing is built before the client confirms


def test_yes_starts_build_other_reply_adjusts_spec(monkeypatch):
    fs = FakeStore(_cycle(status="confirming"),
                   messages=[{"id": 1, "role": "user", "content": "Yes, build it"}])
    _install(monkeypatch, fs)
    started, turns = [], []
    monkeypatch.setattr(eng, "_start_build", lambda cid: started.append(cid))
    monkeypatch.setattr(eng, "_discovery_turn", lambda *a: turns.append(a))
    eng._on_user_message(7, 1)
    assert started == [7] and turns == []

    fs.messages = [{"id": 2, "role": "user", "content": "Also add a menu page with prices"}]
    eng._on_user_message(7, 2)
    assert started == [7] and len(turns) == 1  # adjustment → another discovery turn


def test_discovery_ends_after_max_turns(monkeypatch):
    msgs = []
    for i in range(eng.MAX_INTAKE_TURNS):
        msgs += [{"id": 2 * i + 1, "role": "user", "content": f"answer {i}"},
                 {"id": 2 * i + 2, "role": "agent", "content": "question"}]
    msgs = msgs[:-1]
    fs = FakeStore(_cycle(), messages=msgs)
    _install(monkeypatch, fs)
    monkeypatch.setattr(eng.chat_agent, "intake_turn", lambda *a, **k: {
        "ready": False, "questions": [{"q": "more?", "default": "x"}], "spec": {"summary": "s"}, "missing": []})
    eng._on_user_message(7, msgs[-1]["id"])
    assert fs.cycle["status"] == "confirming"  # defaults, then the client confirms


# ── 2. micro-task planning ──────────────────────────────────────────────

def test_plan_micro_tasks_with_own_checks(monkeypatch):
    monkeypatch.setattr(ca, "_chat", lambda *a, **k: json.dumps({"tasks": [
        {"title": "Foundation", "kind": "create", "description": "pages + nav",
         "checks": [{"kind": "dom_exists", "params": {"selector": "nav"}, "description": "navigation"},
                    {"kind": "console_clean", "params": {}},          # core → dropped
                    {"kind": "rm_rf", "params": {}}]},                 # invalid → dropped
        {"title": "Contact form", "kind": "instruct", "description": "add a form",
         "checks": [{"kind": "dom_exists", "params": {"selector": "form"}, "description": "contact form"}]},
        {"title": "Sneaky create", "kind": "create", "description": "x"},  # 2nd create → dropped
    ]}))
    plan = ca.generate_plan("spec", "new")
    assert [t["title"] for t in plan["tasks"]] == ["Foundation", "Contact form"]
    assert [c["kind"] for c in plan["tasks"][0]["checks"]] == ["dom_exists"]
    kinds = [(d["kind"], d["params"].get("selector")) for d in plan["dod"]]
    assert ("url_200", None) in kinds and ("console_clean", None) in kinds
    assert ("dom_exists", "nav") in kinds and ("dom_exists", "form") in kinds


def test_plan_fallback_when_llm_down(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(ca, "_chat", boom)
    plan = ca.generate_plan("the spec", "new")
    assert plan["tasks"][0]["kind"] == "create" and plan["tasks"][0]["description"] == "the spec"
    existing = ca.generate_plan("change it", "existing")
    assert all(t["kind"] == "instruct" for t in existing["tasks"])


def test_start_build_stores_checks_per_task(monkeypatch):
    fs = FakeStore(_cycle(status="confirming", plan={"spec": {"summary": "s"}}))
    _install(monkeypatch, fs)
    monkeypatch.setattr(eng, "_dispatch_next", lambda cid: None)
    monkeypatch.setattr(eng, "_eta_minutes", lambda tasks: None)
    form = {"kind": "dom_exists", "params": {"selector": "form"}, "description": "contact form"}
    monkeypatch.setattr(eng.chat_agent, "generate_plan", lambda *a, **k: {
        "tasks": [{"title": "Foundation", "summary": "", "description": "d", "kind": "create", "checks": []},
                  {"title": "Contact form", "summary": "a form", "description": "d", "kind": "instruct",
                   "checks": [form]}],
        "dod": ca.regression_checks([{"checks": [form]}]), "assumptions": []})
    eng._start_build(7)
    assert fs.cycle["status"] == "building"
    assert eng._task_checks(fs.tasks[1]) == [form]
    assert eng._task_checks(fs.tasks[0]) == []
    assert fs.said[-1].startswith("📋 Here's the plan — 2 small steps")


def test_task_checks_reads_all_shapes():
    c = {"kind": "dom_exists", "params": {"selector": "form"}}
    assert eng._task_checks({"dod_item": {"checks": [c]}}) == [c]
    assert eng._task_checks({"dod_item": json.dumps({"checks": [c]})}) == [c]
    assert eng._task_checks({"dod_item": c}) == [c]          # legacy single check
    assert eng._task_checks({"dod_item": None}) == []
    assert len(eng._checks_for({"dod_item": {"checks": [c]}})) == 3  # + core checks


# ── 3. verify: every check blocks ───────────────────────────────────────

def test_content_check_failure_blocks_task(monkeypatch):
    import services.dev_cycles.verifier as ver
    monkeypatch.setattr(eng, "_frontend_domain", lambda c: "s.example")
    monkeypatch.setattr(ver, "verify_all", lambda checks, domain, cb=None: {"results": [
        _r("url_200", "pass"), _r("console_clean", "pass"),
        _r("dom_exists", "fail", "contact form", "Contact form — not found on the page", selector="form")]})
    out = eng._compute_outcome({"dod_item": None}, _cycle(project_id=3))
    assert out["verdict"] == "fail"
    assert out["fails"][0]["check"]["description"] == "contact form"


def test_core_failure_is_repaired_first(monkeypatch):
    import services.dev_cycles.verifier as ver
    monkeypatch.setattr(eng, "_frontend_domain", lambda c: "s.example")
    monkeypatch.setattr(ver, "verify_all", lambda checks, domain, cb=None: {"results": [
        _r("dom_exists", "fail", "contact form", selector="form"), _r("url_200", "fail", "site loads")]})
    out = eng._compute_outcome({"dod_item": None}, _cycle(project_id=3))
    assert out["fails"][0]["check"]["kind"] == "url_200"


def test_failed_check_triggers_repair_then_gives_up(monkeypatch):
    task = {"id": 1, "cycle_id": 7, "title": "Contact form", "description": "add a form",
            "kind": "instruct", "status": "under_review", "repair_count": 0,
            "payload": "{}", "result": "{}", "dod_item": None}
    fs = FakeStore(_cycle(status="building", project_id=3), tasks=[task])
    _install(monkeypatch, fs)
    monkeypatch.setattr(eng, "_dispatch_next", lambda cid: None)
    monkeypatch.setattr(eng.chat_agent, "repair_instruction", lambda *a, **k: "Add the form.")
    fail = {"verdict": "fail", "evidence": "x", "results": [], "passed": 2,
            "fails": [_r("dom_exists", "fail", "contact form", "Contact form — not found on the page")]}
    monkeypatch.setattr(eng, "_compute_outcome", lambda *a, **k: fail)

    eng._review_task(7, fs.tasks[0])
    assert fs.tasks[0]["status"] == "todo" and fs.tasks[0]["repair_count"] == 1
    assert json.loads(fs.tasks[0]["payload"])["repair_instruction"] == "Add the form."

    fs.tasks[0]["repair_count"] = eng.MAX_REPAIRS
    eng._review_task(7, fs.tasks[0])
    assert fs.tasks[0]["status"] == "failed"
    assert "not found on the page" in json.loads(fs.tasks[0]["result"])["reason"]


# ── 4. deliver only when validated, else needs_attention ────────────────

def _done(title="Step", **payload):
    return {"id": 1, "title": title, "status": "done", "result": "{}", "payload": json.dumps(payload),
            "repair_count": 0, "dod_item": None, "kind": "instruct"}


def test_validated_rules():
    ok = {"results": [_r("url_200", "pass")]}
    assert eng._is_validated(ok, [_done()], "s.example")
    assert not eng._is_validated(ok, [_done()], "")                                    # no site
    assert not eng._is_validated({"results": [_r("url_200", "unverified")]}, [_done()], "s.example")
    assert not eng._is_validated(ok, [_done(), dict(_done(), status="failed")], "s.example")
    cancelled = dict(_done(), status="failed", result=json.dumps({"error": "cancelled"}))
    assert eng._is_validated(ok, [_done(), cancelled], "s.example")                    # ignored


def test_attention_receipt_lists_blockers():
    failed = dict(_done("Contact form"), status="failed",
                  result=json.dumps({"reason": "contact form — not found on the page"}))
    r = eng._build_receipt("s.example", {"results": [_r("url_200", "pass")]}, [_done("Foundation"), failed])
    assert r.startswith("⚠️ Needs your attention")
    assert "1 of 2 steps are built and verified" in r
    assert "• Contact form — contact form — not found on the page" in r


def test_unverified_final_check_is_not_delivered():
    r = eng._build_receipt("s.example", {"results": [_r("url_200", "unverified")]}, [_done()])
    assert r.startswith("⚠️ Needs your attention") and "check again" in r


def _finalize_env(monkeypatch, fs, sweep_results):
    import services.dev_cycles.verifier as ver
    _install(monkeypatch, fs)
    monkeypatch.setattr(eng, "_frontend_domain", lambda c: "s.example")
    monkeypatch.setattr(ver, "verify_all", lambda dod, domain, cb=None: eng._counts(list(sweep_results)))
    monkeypatch.setattr(eng, "_send_telegram", lambda *a: None)
    dispatched = []
    monkeypatch.setattr(eng, "_dispatch_next", lambda cid: dispatched.append(cid))
    import services.preview_capture as pc  # noqa: F401  (screenshot is best-effort)
    monkeypatch.setattr(pc, "capture_preview_png", lambda url: None, raising=False)
    return dispatched


def test_finalize_delivers_when_everything_passes(monkeypatch):
    fs = FakeStore(_cycle(status="building", project_id=3, dod=list(eng.CORE_CHECKS)), tasks=[_done()])
    _finalize_env(monkeypatch, fs, [_r("url_200", "pass"), _r("console_clean", "pass")])
    eng._finalize(7)
    assert fs.cycle["status"] == "delivered"
    assert fs.said[-1].startswith("✅ Delivered")


def test_finalize_regression_gets_one_fix_round_then_attention(monkeypatch):
    form_fail = _r("dom_exists", "fail", "contact form", "Contact form — not found on the page", selector="form")
    fs = FakeStore(_cycle(status="building", project_id=3, dod=list(eng.CORE_CHECKS)), tasks=[_done()])
    dispatched = _finalize_env(monkeypatch, fs, [_r("url_200", "pass"), form_fail])

    eng._finalize(7)                        # 1st: a broken earlier step → fix task, not delivery
    assert fs.cycle["status"] == "building" and dispatched == [7]
    fix = fs.tasks[-1]
    assert fix["title"] == "Fix what the final check found"
    assert eng._task_checks(fix)[0]["params"]["selector"] == "form"

    fix["status"] = "done"
    eng._finalize(7)                        # still broken after the fix round → notify
    assert fs.cycle["status"] == "needs_attention"
    assert fs.said[-1].startswith("⚠️ Needs your attention")


def test_needs_attention_accepts_followups(monkeypatch):
    fs = FakeStore(_cycle(status="needs_attention", project_id=3),
                   messages=[{"id": 1, "role": "user", "content": "retry"}])
    _install(monkeypatch, fs)
    calls = []
    monkeypatch.setattr(eng, "_finalize", lambda cid, force_sweep=False: calls.append(cid))
    eng._on_user_message(7, 1)
    assert calls == [7]                     # nothing failed → re-check everything


# ── 5. changes on a live project ────────────────────────────────────────

def test_plan_change_drops_outdated_and_marks_new(monkeypatch):
    old_headline = {"kind": "text_present", "params": {"selector": "h1", "text": "Old"}, "description": "headline"}
    new_headline = {"kind": "text_present", "params": {"selector": "h1", "text": "New"}, "description": "new headline"}
    monkeypatch.setattr(ca, "_chat", lambda *a, **k: json.dumps({
        "tasks": [{"title": "Change headline", "description": "Set the h1 to: New", "kind": "instruct",
                   "checks": [new_headline]}],
        "dod": list(eng.CORE_CHECKS)}))       # model removed the outdated check
    out = ca.plan_change("change the headline to New", "bakery site", list(eng.CORE_CHECKS) + [old_headline])
    sigs = {ca.check_sig(d) for d in out["dod"]}
    assert ca.check_sig(old_headline) not in sigs
    assert any(d.get("new") and d["params"].get("text") == "New" for d in out["dod"])


def test_correction_becomes_micro_tasks_with_echo(monkeypatch):
    fs = FakeStore(_cycle(status="delivered", project_id=3, dod=list(eng.CORE_CHECKS)), tasks=[_done()])
    _install(monkeypatch, fs)
    monkeypatch.setattr(eng, "_dispatch_next", lambda cid: None)
    monkeypatch.setattr(eng.chat_agent, "plan_change", lambda *a, **k: {
        "tasks": [{"title": "Add footer hours", "summary": "", "description": "d", "kind": "instruct",
                   "checks": [{"kind": "text_present", "params": {"selector": "footer", "text": "7am"},
                               "description": "opening hours"}]},
                  {"title": "Add map", "summary": "", "description": "d", "kind": "instruct", "checks": []}],
        "dod": list(eng.CORE_CHECKS)})
    eng._handle_followup(fs.cycle, "Add opening hours 7am to 7pm in the footer and a map")
    assert fs.cycle["status"] == "building"
    assert [t["title"] for t in fs.tasks[1:]] == ["Add footer hours", "Add map"]
    assert "in 2 steps" in fs.said[-1] and "1. Add footer hours" in fs.said[-1]
