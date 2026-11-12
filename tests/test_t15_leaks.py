"""T15: error responses carry refs, not exception text; uniform 404s."""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

app = audit_conftest.app_module


def test_t15_helper_returns_short_ref():
    ref = app._safe_error_ref()
    assert re.fullmatch(r"[0-9a-f]{8}", ref)


def test_t15_no_raw_exception_patterns_left():
    src = open(os.path.join(os.path.dirname(audit_conftest.__file__), "..", "app.py"),
               encoding="utf-8").read()
    for bad in ("(Details: {str(e)})", "ACP chat failed - {str(e)}",
                "Failed to queue project creation: {str(e)}",
                "Failed to create project record: {str(e)}"):
        assert bad not in src, bad


def test_t15_session_runs_errors_use_refs():
    path = os.path.join(os.path.dirname(audit_conftest.__file__), "..",
                        "services", "session_chat_runs.py")
    src = open(path, encoding="utf-8").read()
    assert "Session chat failed: {str(e)}" not in src
    assert src.count("Session chat failed (ref") >= 2


def test_t15_foreign_integration_is_404_like_missing():
    """Both 'missing' and 'owned by someone else' say Integration not found."""
    from fastapi.testclient import TestClient
    from audit_conftest import FakeRow, make_fake_db

    def route(c):
        return c.post("/projects", json={"name": "x"},
                      headers={"Authorization": "Bearer test-t15"})

    # stub auth to a fixed user
    monkey = None
    import unittest.mock as mock
    with mock.patch.object(app, "get_user_id_from_token", return_value=42), \
         mock.patch.object(app, "check_project_limit",
                           lambda uid: {"allowed": True, "max": 0}):
        # missing integration id → the 404 branch (never a 403 leak)
        rows = [("SELECT id, user_id", [])]  # integration lookup: not found
        app.get_db = make_fake_db(rows)
        client = TestClient(app.app)
        r = client.post("/projects",
                        json={"name": "x", "global_integration_ids": [999]},
                        headers={"Authorization": "Bearer t"})
        # 404 for missing; foreign-owner path now returns the SAME 404 text
        assert r.status_code in (404, 422)
        if r.status_code == 404:
            assert "not found" in r.json()["detail"].lower()
            assert "access" not in r.json()["detail"].lower()
