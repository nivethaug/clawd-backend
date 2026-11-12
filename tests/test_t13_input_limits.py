"""T13: input limits on /chat and /projects models + proxy body cap."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

app = audit_conftest.app_module


# ── Message / ChatRequest ────────────────────────────────────────────────

def test_t13_message_content_cap():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        app.Message(role="user", content="x" * 20_001)
    assert app.Message(role="user", content="x" * 20_000).content.endswith("x")


def test_t13_messages_list_cap():
    from pydantic import ValidationError
    msgs = [{"role": "user", "content": "hi"}] * 51
    with pytest.raises(ValidationError):
        app.ChatRequest(session_key="s", messages=msgs)
    ok = app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "hi"}] * 50)
    assert len(ok.messages) == 50


def test_t13_image_session_model_mode_caps():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "x"}],
                        image="A" * 12_000_001)
    with pytest.raises(ValidationError):
        app.ChatRequest(session_key="s" * 129, messages=[{"role": "user", "content": "x"}])
    with pytest.raises(ValidationError):
        app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "x"}],
                        model="m" * 101)
    with pytest.raises(ValidationError):
        app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "x"}],
                        mode="evil")
    ok = app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "x"}],
                         mode="plan")
    assert ok.mode == "plan"


def test_t13_design_context_size_cap():
    from pydantic import ValidationError
    big = {"nodes": [{"id": i, "label": "n" * 50} for i in range(4000)]}
    with pytest.raises(ValidationError):
        app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "x"}],
                        design_context=big)
    ok = app.ChatRequest(session_key="s", messages=[{"role": "user", "content": "x"}],
                         design_context={"nodes": [1, 2, 3]})
    assert ok.design_context == {"nodes": [1, 2, 3]}


# ── CreateProjectRequest ─────────────────────────────────────────────────

def test_t13_create_request_caps():
    from pydantic import ValidationError
    base = {"name": "n"}
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, description="d" * 10_001)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, template_id="t" * 101)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, telegram_chat_id="c" * 65)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, discord_webhook_url="w" * 2049)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, email_to="e" * 255)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, api_endpoint="u" * 2049)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, git_origin_url="g" * 2049)
    with pytest.raises(ValidationError):
        app.CreateProjectRequest(**base, global_integration_ids=list(range(21)))
    assert app.CreateProjectRequest(**base, description="d" * 10_000).name == "n"


def test_t13_env_var_value_cap():
    from project_initial_env import normalize_initial_environment_variables
    with pytest.raises(ValueError):
        normalize_initial_environment_variables([{"key": "K", "value": "v" * 8193}])
    out = normalize_initial_environment_variables([{"key": "K", "value": "v" * 8192}])
    assert out[0]["value"].endswith("v")


# ── Proxy body cap ───────────────────────────────────────────────────────

def test_t13_proxy_body_too_large_413(monkeypatch):
    import services.project_proxy as pp
    import asyncio
    from starlette.responses import JSONResponse

    class _Req:
        url = type("U", (), {"path": "/chat"})()
        method = "POST"
        headers = {"content-length": str(16 * 1024 * 1024)}
        query_params = {}

        async def body(self):
            return b"{}"

    async def _call_next(_r):
        return JSONResponse({"leak": True})

    monkeypatch.setattr(pp, "_get_worker_url", lambda: "http://worker:8003")
    resp = asyncio.run(pp.project_proxy_middleware(_Req(), _call_next))
    assert resp.status_code == 413
