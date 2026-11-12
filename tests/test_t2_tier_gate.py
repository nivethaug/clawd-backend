"""T2: free-tier model/effort gates must see the real project owner user_id."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_conftest import app_module  # noqa: E402

app = app_module


def _tier(monkeypatch, tier, role="user"):
    import services.rate_limiter as rl
    monkeypatch.setattr(rl, "get_user_tier_and_role",
                        lambda _uid: {"tier": tier, "role": role})


def test_t2_free_user_premium_model_falls_back_to_default(monkeypatch):
    _tier(monkeypatch, "free")
    info = app._resolve_session_model("z-ai/glm-5.3", 42)  # tier "pro" model
    assert info.get("default") is True


def test_t2_free_user_effort_high_falls_back_to_low(monkeypatch):
    _tier(monkeypatch, "free")
    assert app._resolve_reasoning_effort("high", 42) == "low"


def test_t2_pro_user_keeps_selection(monkeypatch):
    _tier(monkeypatch, "pro")
    info = app._resolve_session_model("z-ai/glm-5.3", 42)
    assert info["id"] == "z-ai/glm-5.3"
    assert app._resolve_reasoning_effort("high", 42) == "high"


def test_t2_admin_on_free_tier_keeps_selection(monkeypatch):
    # admins are exempt from the free-tier clamp
    _tier(monkeypatch, "free", role="admin")
    info = app._resolve_session_model("z-ai/glm-5.3", 24)
    assert info["id"] == "z-ai/glm-5.3"


def test_t2_stream_endpoint_resolves_owner_before_model(monkeypatch):
    """The endpoint code path: owner lookup precedes resolver calls (regression
    guard for the user_id=None ordering bug)."""
    import services.rate_limiter as rl
    calls = []

    real_resolve = app._resolve_session_model

    def spy_resolve(model_id, user_id=None):
        calls.append(("model", user_id))
        return real_resolve(model_id, user_id)

    monkeypatch.setattr(app, "_resolve_session_model", spy_resolve)
    assert real_resolve is not None
    # source-level assertion: owner lookup must come before resolver call
    src = open(app.__file__, encoding="utf-8").read()
    anchor = src.index("# ── BILLING: Reserve AI credits before processing (ACP mode only) ──────")
    segment = src[anchor:anchor + 1600]
    owner_pos = segment.index("SELECT user_id FROM projects WHERE id")
    model_pos = segment.index("_resolve_session_model(request.model")
    assert owner_pos < model_pos, "owner lookup must precede model resolution"
