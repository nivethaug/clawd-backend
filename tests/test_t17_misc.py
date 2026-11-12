"""T17: limit-check fail-closed (503), proxy session_key mismatch (400)."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

app = audit_conftest.app_module


def test_t17a_limit_check_failure_fails_closed(monkeypatch):
    import services.rate_limiter as rl

    def boom(uid):
        raise RuntimeError("db down")

    monkeypatch.setattr(rl, "get_user_tier_and_role",
                        lambda uid: {"tier": "free", "role": "user"})
    monkeypatch.setattr(rl, "_get_effective_max_projects", lambda uid, cfg: 3)

    from audit_conftest import make_fake_db

    class _ExplodingDB:
        def __enter__(self):
            raise RuntimeError("db down")

        def __exit__(self, *a):
            return False

    import database_adapter
    monkeypatch.setattr(database_adapter, "get_db", lambda: _ExplodingDB())
    monkeypatch.setattr(rl, "get_db", lambda: _ExplodingDB(), raising=False)
    result = rl.check_project_limit(1)
    assert result["allowed"] is False
    assert result["error"] == "limit_check_failed"


def test_t17a_endpoint_maps_limit_failure_to_503():
    src = open(os.path.join(os.path.dirname(audit_conftest.__file__), "..", "app.py"),
               encoding="utf-8").read()
    assert src.count('limit_check_failed') >= 2  # both create + clone sites
    assert "status_code=503" in src


def test_t17b_proxy_session_key_mismatch_400(monkeypatch):
    import services.project_proxy as pp
    from starlette.responses import JSONResponse

    class _Req:
        url = type("U", (), {"path": "/chat"})()
        method = "POST"
        headers = {"content-length": "10"}
        query_params = {"session_key": "KEY-AAA"}

        async def body(self):
            return b'{"session_key": "KEY-BBB"}'

    async def _call_next(_r):
        return JSONResponse({"leak": True})

    monkeypatch.setattr(pp, "_get_worker_url", lambda: "http://worker:8003")
    resp = asyncio.run(pp.project_proxy_middleware(_Req(), _call_next))
    assert resp.status_code == 400

    # matching keys route normally (no 400)
    class _Req2(_Req):
        query_params = {"session_key": "KEY-BBB"}

    resp2 = asyncio.run(pp.project_proxy_middleware(_Req2(), _call_next))
    assert resp2.status_code != 400
