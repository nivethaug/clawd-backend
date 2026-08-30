"""Sandbox limits block — rendered into agent build/edit/chat prompts so
models KNOW the enforcement rules before writing `pip install` commands.
Mirrors services/sandbox/package_gate.py + egress.py. Fail-soft: returns
"" when the enforcement module is missing."""


def sandbox_limits_block() -> str:
    try:
        from services.sandbox.package_gate import (
            DEFAULT_BLOCKED, max_install_mb)
    except ImportError:
        return ""
    blocked = ", ".join(sorted(
        b[:-1] + "*" if b.endswith("*") else b for b in DEFAULT_BLOCKED))
    cap = max_install_mb()
    return f"""
## 🛡️ SANDBOX LIMITS (enforced — do not fight them)

**Python packages:** installing these is BLOCKED at the platform gate and
will fail: {blocked}. They are multi-GB LLM/GPU runtimes that do not belong
in a project sandbox. Instead:
- Call LLMs via API (the integrations/proxy in this prompt) — no local models.
- If the project truly needs GPU execution, call a GPU provider (e.g. RunPod
  API) with a key the owner stores in Global Integrations.

**Install size cap:** total pip download per operation must stay under
{cap} MB. Prefer small, focused dependencies (requests/flask/fastapi/etc.).

**Network:** the sandbox's internet access is allowlisted (package
registries, GitHub, the platform API) and every download is size-capped —
do NOT attempt to download model weights, datasets, or large binaries
(e.g. HuggingFace). Use APIs instead.

**Disk:** each project has a hard workspace size limit. Keep dependencies
minimal, stream instead of hoarding data, and clean temp files.

If a required capability seems blocked, tell the user what the limit is and
propose the API-based alternative — never try to bypass the gate.
"""
