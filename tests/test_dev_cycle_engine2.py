"""Requested tests: _build_receipt variants, _sanitize_dod, patch_dod
fallback, command detection, intake tie-break."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.dev_cycles.engine as eng  # noqa: E402
import services.dev_cycles.chat_agent as ca  # noqa: E402


# ── _build_receipt ───────────────────────────────────────────────────────

def _sweep(results):
    return {"results": results,
            "passed": sum(1 for r in results if r["verdict"] == "pass"),
            "failed": sum(1 for r in results if r["verdict"] == "fail"),
            "unverified": sum(1 for r in results if r["verdict"] == "unverified")}


CORE_OK = {"verdict": "pass", "check": {"kind": "url_200"}, "user_text": "The site loads"}
CONSOLE_OK = {"verdict": "pass", "check": {"kind": "console_clean"}}
CONTENT_FAIL = {"verdict": "fail", "check": {"kind": "dom_exists", "description": "contact form"},
                "user_text": "Contact form — I couldn't find one"}
CONTENT_PASS = {"verdict": "pass", "check": {"kind": "text_present", "description": "headline",
                "new": True}, "user_text": "Headline — headline now reads 'Hello'"}
CORE_FAIL = {"verdict": "fail", "check": {"kind": "console_clean"},
             "user_text": "The page has 2 script errors"}


def test_receipt_clean():
    r = eng._build_receipt("site.example", _sweep([CORE_OK, CONSOLE_OK, CONTENT_PASS]),
                           [{"title": "Build", "status": "done", "result": "{}", "payload": "{}"}])
    assert r.startswith("✅ Delivered")
    assert "https://site.example" in r
    assert "final check of the whole site (3 checks) passed" in r
    assert "⚠" not in r


def test_receipt_content_miss_blocks_delivery():
    # a promised element missing is no longer a "minor note": not validated
    r = eng._build_receipt("site.example",
                           _sweep([CORE_OK, CONSOLE_OK, CONTENT_FAIL, CONTENT_PASS]),
                           [{"title": "Build", "status": "done", "result": "{}", "payload": "{}"}])
    assert r.startswith("⚠️ Needs your attention")
    assert "Contact form" in r
    assert "retry" in r


def test_receipt_corrected():
    tasks = [{"title": "Change: make it dark", "status": "done", "result": "{}",
              "payload": json.dumps({"correction": True, "requests": ["make it dark"],
                                     "receipted": False})}]
    r = eng._build_receipt("site.example",
                           _sweep([CORE_OK, CONSOLE_OK, CONTENT_PASS]), tasks)
    assert "Change is live" in r
    assert "make it dark" in r
    assert "Confirmed on the page" in r


def test_receipt_core_fail():
    r = eng._build_receipt("site.example", _sweep([CORE_OK, CORE_FAIL]),
                           [{"title": "Build", "status": "done", "result": "{}", "payload": "{}"}])
    assert r.startswith("⚠️ Needs your attention")
    assert "script errors" in r


def test_receipt_no_domain():
    r = eng._build_receipt("", _sweep([CORE_FAIL]), [])
    assert "wasn't created" in r
    assert "https://" not in r


# ── _sanitize_dod ────────────────────────────────────────────────────────

def test_sanitize_dod_strips_invalid_kinds():
    dod = [{"kind": "url_200", "params": {}}, {"kind": "rm_rf", "params": {}}]
    out = ca._sanitize_dod(dod)
    kinds = [d["kind"] for d in out]
    assert "rm_rf" not in kinds
    assert "url_200" in kinds


def test_sanitize_dod_ensures_core():
    out = ca._sanitize_dod([{"kind": "dom_exists", "params": {"selector": "nav"}}])
    kinds = [d["kind"] for d in out]
    assert "url_200" in kinds and "console_clean" in kinds


def test_sanitize_dod_none_input():
    out = ca._sanitize_dod(None)
    kinds = [d["kind"] for d in out]
    assert "url_200" in kinds and "console_clean" in kinds


# ── patch_dod fallback ───────────────────────────────────────────────────

def test_patch_dod_returns_none_on_llm_failure(monkeypatch):
    def failing_chat(*a, **kw):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(ca, "_chat", failing_chat)
    result = ca.patch_dod([{"kind": "url_200", "params": {}}], "change the headline")
    assert result is None  # caller keeps old DoD + flags predates_change


def test_patch_dod_marks_new_checks(monkeypatch):
    def fake_chat(system, user, max_tokens=2000):
        return json.dumps({"dod": [
            {"kind": "url_200", "params": {"path": "/"}},
            {"kind": "text_present", "params": {"selector": "h1", "text": "Hello"},
             "description": "new headline"},
        ]})
    monkeypatch.setattr(ca, "_chat", fake_chat)
    result = ca.patch_dod([{"kind": "url_200", "params": {"path": "/"},
                            "description": "site loads"}], "change the headline to Hello")
    assert result is not None
    news = [d for d in result if d.get("new")]
    assert any(d.get("params", {}).get("text") == "Hello" for d in news)


# ── command detection (≤4 words) ────────────────────────────────────────

def test_retry_command_short():
    assert eng.RETRY_RE.match("retry")
    assert eng.RETRY_RE.match("please try again")
    assert eng.RETRY_RE.match("redo")


def test_retry_not_matched_for_long_messages():
    # the word-limit gate lives in _handle_followup (is_command), verified
    # separately in test_dev_cycle_review1; here we verify the regexes
    # themselves don't anchor mid-sentence changes
    assert not eng.RETRY_RE.match("change the retry button color")


def test_recheck_command():
    assert eng.RECHECK_RE.match("check again")
    assert eng.RECHECK_RE.match("re-check")
    assert not eng.RECHECK_RE.match("check the contact form again please")


# ── intake tie-break ────────────────────────────────────────────────────

def test_intake_not_ready_no_questions_forces_ready(monkeypatch):
    """not-ready with zero questions = dead loop → must force ready."""
    def fake_chat(system, user, max_tokens=500):
        return json.dumps({"ready": False, "questions": [], "missing": []})
    monkeypatch.setattr(ca, "_chat", fake_chat)
    verdict = ca.intake_turn([{"role": "user", "content": "build a coffee shop site"}], "new")
    assert verdict["ready"] is True
    assert verdict["questions"] == []


def test_intake_short_input_gets_one_question(monkeypatch):
    """<4 words + not-ready + no questions → one plain question (not a loop)."""
    def fake_chat(system, user, max_tokens=500):
        return json.dumps({"ready": False, "questions": [], "missing": []})
    monkeypatch.setattr(ca, "_chat", fake_chat)
    verdict = ca.intake_turn([{"role": "user", "content": "a site"}], "new")
    assert verdict["ready"] is False
    assert len(verdict["questions"]) == 1


def test_intake_ready_with_questions_contradiction_trusts_ready(monkeypatch):
    def fake_chat(system, user, max_tokens=500):
        return json.dumps({"ready": True, "questions": ["what color?"], "missing": []})
    monkeypatch.setattr(ca, "_chat", fake_chat)
    verdict = ca.intake_turn([{"role": "user", "content": "build a site"}], "new")
    assert verdict["ready"] is True
    assert verdict["questions"] == []
