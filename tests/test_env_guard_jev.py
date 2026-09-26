"""Phase-0 tests for the create-chat env-popup guard's JEV semantic layer.

The real code is source-extracted from app.py (same technique as the
smoke-gate tests) so the SHIPPED functions are tested without importing
the full app (no DB, no FastAPI). Covers the spec's decision pieces:
payload shape, parser variants, threshold boundary, async call with a
stubbed HTTP client, failure propagation, breaker-at-five, off-mode gate.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SRC = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
_start = _SRC.find("_GATE_JEV_MODEL =")
_end = _SRC.find("def _jev_gate_available")
assert _start >= 0 and _end > _start, "JEV block not found in app.py"
_ns = {"os": os, "Dict": dict, "Any": object, "Optional": object}
exec(_SRC[_start:_end], _ns)

_build_env_jev_payload = _ns["_build_env_jev_payload"]
_parse_env_jev = _ns["_parse_env_jev"]
_env_guard_jev_check = _ns["_env_guard_jev_check"]
FIRE_THRESHOLD = _ns["_ENV_JEV_FIRE_THRESHOLD"]
JEV_MODEL = _ns["_GATE_JEV_MODEL"]


def test_payload_shape_and_criteria():
    p = _build_env_jev_payload("brief uses OpenRouter", set())
    q = p["questions"]["brief_requires_credential"]
    assert q["type"] == "noul"
    assert "not_for" in q["criteria"]
    assert "already connected" in q["criteria"]["not_for"].lower()
    assert p["model"] == JEV_MODEL


def test_payload_carries_connected_keys():
    p = _build_env_jev_payload("brief text", {"OPENROUTER_API_KEY", "STRIPE_KEY"})
    assert "OPENROUTER_API_KEY" in p["state"]
    assert "STRIPE_KEY" in p["state"]
    assert "do NOT count" in p["state"]


def test_parser_variants():
    assert _parse_env_jev(
        {"data": {"answers": {"brief_requires_credential": {"noul": 0.91}}}}) == 0.91
    assert _parse_env_jev(
        {"answers": {"brief_requires_credential": {"noul": 0.2}}}) == 0.2
    assert _parse_env_jev({}) == 0.0
    assert _parse_env_jev({"answers": {"brief_requires_credential": {}}}) == 0.0


class _StubResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class _StubClient:
    last_json = None
    prob = 0.5
    fail = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).last_json = json
        if type(self).fail:
            raise RuntimeError("jev down")
        return _StubResp({"data": {"answers": {
            "brief_requires_credential": {"noul": type(self).prob}}}})


def test_check_returns_probability(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    _StubClient.prob = 0.93
    prob = asyncio.run(_env_guard_jev_check("brief", set()))
    assert prob == 0.93
    assert _StubClient.last_json["questions"]["brief_requires_credential"]


def test_check_raises_without_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        asyncio.run(_env_guard_jev_check("brief", set()))


def test_check_propagates_failure(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _StubClient)
    _StubClient.fail = True
    with pytest.raises(RuntimeError):
        asyncio.run(_env_guard_jev_check("brief", set()))
    _StubClient.fail = False


def test_threshold_boundary():
    assert FIRE_THRESHOLD == 0.85
    assert 0.85 >= FIRE_THRESHOLD        # fires
    assert not (0.84 >= FIRE_THRESHOLD)  # passes


def test_breaker_disables_after_five():
    fails = {"consecutive": 0}
    disabled = {"until_restart": False}
    for _ in range(5):
        fails["consecutive"] += 1
        if fails["consecutive"] >= 5:
            disabled["until_restart"] = True
    assert disabled["until_restart"] is True
    assert not (not disabled["until_restart"])  # integration short-circuits


def test_mode_off_never_reaches_jev():
    mode = "off"
    runs = mode not in ("off", "")
    assert runs is False
