"""R3: _acpx_child_env is a TRUE allowlist — denylist leaks are gone."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_conftest  # noqa: E402

import acp_chat_handler as ach  # noqa: E402


def test_r3_secrets_absent_from_child_env(monkeypatch):
    for k, v in {
        "DB_PASS": "p1", "PG_PASS": "p2", "SMTP_PWD": "p3",
        "OPENROUTER_API_KEY": "sk-or-fake", "SENTRY_DSN": "https://dsn",
        "GITHUB_CREDENTIALS": "c", "VAULT_PRIVATE": "x",
        "TELEGRAM_BOT_TOKEN": "t", "DATABASE_URL": "postgres://…",
    }.items():
        monkeypatch.setenv(k, v)
    env = ach._acpx_child_env()
    for k in ("DB_PASS", "PG_PASS", "SMTP_PWD", "OPENROUTER_API_KEY",
              "SENTRY_DSN", "GITHUB_CREDENTIALS", "VAULT_PRIVATE",
              "TELEGRAM_BOT_TOKEN", "DATABASE_URL"):
        assert k not in env, f"{k} leaked"


def test_r3_basics_present(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("TERM", "xterm")
    env = ach._acpx_child_env()
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/root"
    assert env["TERM"] == "xterm"


def test_r3_random_safe_name_still_excluded(monkeypatch):
    """Non-allowlisted innocuous names are excluded too (true allowlist)."""
    monkeypatch.setenv("SOME_INNOCUOUS_VAR", "ok")
    assert "SOME_INNOCUOUS_VAR" not in ach._acpx_child_env()


def test_r3_streaming_path_uses_helper():
    src = open(os.path.join(os.path.dirname(audit_conftest.__file__), "..",
                            "acp_chat_handler.py"), encoding="utf-8").read()
    assert "env = _acpx_child_env()" in src
    assert "os.environ.copy()" not in src.split("def run_acpx_chat_streaming")[1].split("def ")[0]
