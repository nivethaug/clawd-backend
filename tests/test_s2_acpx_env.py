"""S2: run_acpx_chat child env is allowlisted + thinking flags; no other
acpx/claude subprocess gets a full os.environ."""

import os
import sys
import inspect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import acp_chat_handler as ach  # noqa: E402


class _Proc:
    pid = 777

    def __init__(self):
        self.killed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True

    def communicate(self, *args, **kwargs):
        return ("", "")

    args = ["acpx"]  # some paths read process.args
    returncode = 0

    class stdout:
        readline = staticmethod(lambda: "")
        read = staticmethod(lambda: "DONE end_turn")


def test_s2_run_acpx_chat_env_is_allowlisted(monkeypatch):
    for k, v in {"DB_PASS": "p", "SMTP_PWD": "s", "OPENROUTER_API_KEY": "sk-or-x",
                 "FOO_CREDENTIALS": "c", "TELEGRAM_BOT_TOKEN": "t"}.items():
        monkeypatch.setenv(k, v)

    captured = {}

    def fake_popen(cmd, **kw):
        # skip the "which acpx" probe; capture the REAL spawn (stdbuf/acpx)
        if "cmd" not in captured and cmd and cmd[0] == "stdbuf":
            captured["cmd"] = cmd
            captured["env"] = kw.get("env")
        return _Proc()

    monkeypatch.setattr(ach.subprocess, "Popen", fake_popen)

    async def _no_pre(*a, **k):
        return None

    monkeypatch.setattr(ach, "check_preprocessor", _no_pre)

    def _wm(**kw):
        return "<meta/>"

    h = object.__new__(ach.ACPChatHandler)
    h._plan_mode = False
    h._enhanced_prompt = "do it"
    h.is_telegram_bot = False
    h.is_discord_bot = False
    h.is_scheduler = False
    h.project_type_id = 1
    h.project_name = "P"
    h.project_path = "/tmp/p"
    h.frontend_src_path = "/tmp/p/f"
    h._workflow_meta_block = _wm
    h._build_chat_prompt = lambda m, c: m
    h._build_chat_prompt_telegram = lambda m, c: m
    h._build_chat_prompt_discord = lambda m, c: m
    result = h.run_acpx_chat("do it", "")

    env = captured["env"]
    assert env is not None
    for leaked in ("DB_PASS", "SMTP_PWD", "OPENROUTER_API_KEY",
                   "FOO_CREDENTIALS", "TELEGRAM_BOT_TOKEN"):
        assert leaked not in env, leaked
    assert "PATH" in env
    assert env.get("CLAUDE_DISABLE_THINKING") == "1"
    assert env.get("DISABLE_THINKING") == "1"
    assert env.get("NO_THINKING") == "1"
    assert captured["cmd"][0] in ("stdbuf", "acpx")  # command surface unchanged


def test_s2_no_os_environ_copy_left_in_acpx_or_claude_spawns():
    """acp_chat_handler has NO os.environ.copy() feeding Popen anymore; the
    npm-install copy in app.py is an npm command (out of scope)."""
    src = open(os.path.join(os.path.dirname(audit_conftest.__file__), "..",
                            "acp_chat_handler.py"), encoding="utf-8").read()
    code_lines = [l for l in src.splitlines() if not l.lstrip().startswith("#")]
    assert "os.environ.copy()" not in chr(10).join(code_lines)

    app_src = open(os.path.join(os.path.dirname(audit_conftest.__file__), "..",
                                "app.py"), encoding="utf-8").read()
    # the only remaining copy is the npm-env one (verified: no acpx/claude cmd)
    import re
    for m in re.finditer(r"os\.environ\.copy\(\)", app_src):
        line_no = app_src[:m.start()].count("\n") + 1
        context = app_src[max(0, m.start() - 400):m.start() + 400]
        assert "acpx" not in context and "claude exec" not in context, \
            f"os.environ.copy at app.py:{line_no} feeds an acpx/claude spawn"
