"""T14: large prompts spawn with a stdin PIPE; write failures raise."""

import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import services.runtime_manager as rm  # noqa: E402
import claude_code_agent as cca  # noqa: E402


def test_t14_runtime_passes_pipe_when_requested():
    """exec_subprocess_stream has the stdin_pipe kwarg and maps it to PIPE."""
    sig = inspect.signature(rm.ProjectRuntimeManager.exec_subprocess_stream)
    assert "stdin_pipe" in sig.parameters
    assert sig.parameters["stdin_pipe"].default is False

    async def fake_exec(*a, **k):
        stdin_pipe = k.get("stdin_pipe")
        stdin = asyncio.subprocess.PIPE if stdin_pipe else asyncio.subprocess.DEVNULL
        return {"stdin": stdin, "stdin_pipe": stdin_pipe}

    mgr = object.__new__(rm.ProjectRuntimeManager)
    mgr.__dict__.update({"mode": "local", "user_id": None})
    # monkey-level: call through with a stubbed create_subprocess_exec
    captured = {}

    async def fake_spawn(*args, **kw):
        captured.update(kw)
        return "proc"

    orig = rm.asyncio.create_subprocess_exec
    rm.asyncio.create_subprocess_exec = fake_spawn
    try:
        asyncio.run(mgr.exec_subprocess_stream(
            ["echo", "hi"], cwd="/tmp", env={"PATH": "/usr/bin"},
            run_as_root=True, stdin_pipe=True))
    finally:
        rm.asyncio.create_subprocess_exec = orig
    assert captured["stdin"] is asyncio.subprocess.PIPE

    captured.clear()
    rm.asyncio.create_subprocess_exec = fake_spawn
    try:
        asyncio.run(mgr.exec_subprocess_stream(
            ["echo", "hi"], cwd="/tmp", env={"PATH": "/usr/bin"},
            run_as_root=True))
    finally:
        rm.asyncio.create_subprocess_exec = orig
    assert captured["stdin"] is asyncio.subprocess.DEVNULL


def test_t14_agent_passes_stdin_pipe_for_large_prompts():
    """Source check: the spawn call wires _use_stdin_prompt into stdin_pipe."""
    src = inspect.getsource(cca.ClaudeCodeAgent._execute_query)
    assert "stdin_pipe=_use_stdin_prompt" in src


def test_t14_missing_stdin_raises():
    """A large prompt with no stdin pipe must raise, not run empty."""
    # Simulate the write block behavior directly from source semantics:
    # find the guard in source
    src = inspect.getsource(cca.ClaudeCodeAgent._execute_query)
    assert "no stdin pipe" in src
    assert "stdin prompt write failed" in src
    assert "logger.warning" not in src.split("Feed a large prompt via stdin")[1].split("# Mark container")[0]
