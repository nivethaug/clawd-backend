"""T12: no host-ACPX fallback; env allowlist; watchdog timeout."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import acp_chat_handler as ach  # noqa: E402


def _bare_handler(**attrs):
    h = object.__new__(ach.ACPChatHandler)
    for k, v in attrs.items():
        setattr(h, k, v)
    return h


def test_t12_claude_failure_propagates_no_fallback(monkeypatch):
    monkeypatch.setattr(ach, "USE_CLAUDE_AGENT", True)
    popen_calls = []
    monkeypatch.setattr(ach.subprocess, "Popen", lambda *a, **k: popen_calls.append(1))

    async def failing_stream(msg, ctx):
        yield "partial..."
        raise RuntimeError("claude exploded")
        yield "never"

    h = _bare_handler(run_claude_chat_streaming=failing_stream)

    async def collect():
        out = []
        try:
            async for chunk in h.run_chat_streaming_unified("hi", ""):
                out.append(chunk)
        except RuntimeError as e:
            return out, e
        return out, None

    chunks, err = asyncio.run(collect())
    assert err is not None and "claude exploded" in str(err)
    assert popen_calls == []          # ACPX never spawned as a fallback


def test_t12_acpx_env_has_no_secret_keys(monkeypatch):
    monkeypatch.setattr(ach, "USE_CLAUDE_AGENT", False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-fake")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    monkeypatch.setenv("SOME_SAFE_VAR", "ok")

    captured = {}

    class _FakeProc:
        pid = 4242

        def poll(self):
            return 0

        class stdout:
            @staticmethod
            def readline():
                return ""

            @staticmethod
            def read():
                return ""

    def fake_popen(cmd, **kw):
        if "cmd" not in captured:      # first call = the acpx spawn itself
            captured["cmd"] = cmd
            captured["env"] = kw.get("env")
        return _FakeProc()

    async def _no_pre(*a, **k):
        return None

    monkeypatch.setattr(ach, "check_preprocessor", _no_pre)
    monkeypatch.setattr(ach.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ach.subprocess, "PIPE", -1)
    monkeypatch.setattr(ach.subprocess, "STDOUT", -2)

    def _workflow_meta_block(**kw):
        return "<meta/>"

    h = _bare_handler(
        _plan_mode=False,
        _enhanced_prompt="do the thing",
        is_telegram_bot=False,
        is_discord_bot=False,
        is_scheduler=False,
        is_agent=False,
        is_bot_project=False,
        project_type_id=1,
        project_name="P",
        project_path="/tmp/p",
        frontend_src_path="/tmp/p/f",
        _workflow_meta_block=_workflow_meta_block,
        _build_chat_prompt=lambda msg, ctx: msg,
        _build_chat_prompt_telegram=lambda msg, ctx: msg,
        _build_chat_prompt_discord=lambda msg, ctx: msg,
    )
    list(h.run_acpx_chat_streaming("do the thing", ""))

    env = captured["env"]
    assert env is not None
    for key in ("OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "DB_PASSWORD"):
        assert key not in env, f"secret {key} leaked into acpx env"
    assert "PATH" in env and "SOME_SAFE_VAR" in env
    assert "--approve-all" in captured["cmd"]  # unchanged command surface
