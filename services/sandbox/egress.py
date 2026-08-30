#!/usr/bin/env python3
"""
Egress Allowlist (Layer 3) — the biggest security + disk win.

A squid sidecar container (`dreamagent-egress`) is the ONLY route to the
internet for project sandboxes. Destinations are allowlisted; every
response body is size-capped (kills HuggingFace multi-GB model downloads
and the exfil angle in one move).

Activation (worker .env.postgres):
  EGRESS_ENFORCE=1
  EGRESS_ALLOWLIST=pypi.org,files.pythonhosted.org,registry.npmjs.org,api.github.com,github.com,objects.githubusercontent.com,api.dreamagent.cloud
  EGRESS_REPLY_MAX_MB=200          # per-response body cap
  EGRESS_PROXY_IMAGE=squid:alpine  # optional override

Enforcement points:
  - containers: container_manager puts project containers on an --internal
    network with the squid container as the only egress; HTTP(S)_PROXY env
    points at it. With --internal, direct egress is impossible even if the
    process ignores the proxy env — only squid's CONNECT path exists.
  - bwrap sandboxes: scheduler/backend sandbox scripts export the same
    proxy env; full enforcement for those needs the host nftables rule
    emitted by scripts/setup-egress.sh (owner-based redirect).
"""

import logging
import os
import shlex
from typing import List, Optional

logger = logging.getLogger("services.sandbox.egress")

DEFAULT_ALLOWLIST = (
    "pypi.org,files.pythonhosted.org,registry.npmjs.org,"
    "api.github.com,github.com,objects.githubusercontent.com,"
    "api.dreamagent.cloud"
)
DEFAULT_REPLY_MAX_MB = 200


def egress_enforced() -> bool:
    return os.getenv("EGRESS_ENFORCE", "").strip() in ("1", "true", "yes")


def allowlist() -> List[str]:
    raw = os.getenv("EGRESS_ALLOWLIST", DEFAULT_ALLOWLIST)
    return [d.strip().lstrip(".").lower() for d in raw.split(",") if d.strip()]


def reply_max_mb() -> int:
    try:
        return max(10, int(os.getenv("EGRESS_REPLY_MAX_MB", DEFAULT_REPLY_MAX_MB)))
    except (TypeError, ValueError):
        return DEFAULT_REPLY_MAX_MB


def proxy_env(where: str = "container") -> dict:
    """Env vars pointing sandbox processes at the sidecar. Empty dict when
    enforcement is off. `where`: "container" (docker network, sidecar by
    name) or "host" (bwrap sandboxes, sidecar published on localhost)."""
    if not egress_enforced():
        return {}
    url = ("http://dreamagent-egress:3128" if where == "container"
           else "http://127.0.0.1:3128")
    return {
        "HTTP_PROXY": url, "http_proxy": url,
        "HTTPS_PROXY": url, "https_proxy": url,
        # CRITICAL exclusions: host.docker.internal is the wrapper-v2 LLM
        # endpoint — proxying it would break every agent's LLM calls.
        "NO_PROXY": "localhost,127.0.0.1,host.docker.internal,172.17.0.1,"
                    "api.dreamagent.cloud",
        "no_proxy": "localhost,127.0.0.1,host.docker.internal,172.17.0.1,"
                    "api.dreamagent.cloud",
    }


def squid_conf() -> str:
    """squid.conf for the sidecar — generated from the env allowlist."""
    domains = allowlist()
    acl_lines = "\n".join(
        f"acl allowed_domains dstdomain .{shlex.quote(d)}"
        for d in domains if d
    ) or "acl allowed_domains dstdomain .pypi.org"
    return f"""# dreamagent egress sidecar — GENERATED, do not hand-edit
http_port 3128

# Allowlist: only these destinations are reachable. Everything else
# (huggingface.co, *.hf.co, arbitrary hosts, exfil endpoints) is denied.
{acl_lines}

http_access allow allowed_domains
http_access deny all

# Per-response body cap — blocks multi-GB model/dataset downloads even
# to allowlisted hosts (e.g. a huge GitHub release asset).
reply_body_max_size {reply_max_mb()} MB

# CONNECT (https) is the only method sandbox code needs
http_access deny !CONNECT

cache deny all
access_log stdio:/var/log/squid/access.log
"""


def ensure_egress_sidecar(_run) -> Optional[str]:
    """Start/refresh the squid sidecar container. `_run` is
    container_manager._run (subprocess runner). Returns container name or
    None when enforcement is off. Idempotent."""
    if not egress_enforced():
        return None
    image = os.getenv("EGRESS_PROXY_IMAGE", "squid:alpine")
    name = "dreamagent-egress"
    conf_path = "/opt/dreamagent-egress/squid.conf"
    try:
        import pathlib
        pathlib.Path("/opt/dreamagent-egress").mkdir(parents=True, exist_ok=True)
        with open(conf_path, "w", encoding="utf-8") as fh:
            fh.write(squid_conf())
    except OSError as e:
        logger.error("[EGRESS] cannot write %s: %s", conf_path, e)
        return None

    # Idempotent: an existing sidecar is NEVER removed — restarting it
    # would briefly cut egress for every running project container.
    # Stopped → started; missing → created; config drift → logged only
    # (restart requires a manual `docker restart dreamagent-egress`).
    exists = _run(["ps", "-a", "-q", "-f", f"name={name}"]).stdout.strip()
    if exists:
        running = _run(["ps", "-q", "-f", f"name={name}"]).stdout.strip()
        if not running:
            _run(["start", name])
            logger.info("[EGRESS] sidecar started (was stopped): %s", name)
        else:
            logger.debug("[EGRESS] sidecar already running: %s", name)
        return name

    _run(["pull", "-q", image])
    result = _run([
        "run", "-d", "--name", name,
        "--restart", "unless-stopped",
        # project containers reach it by name on the shared network;
        # host-published loopback port serves bwrap sandboxes
        "--network", os.getenv("CONTAINER_NETWORK", "dreamagent-net"),
        "-p", "127.0.0.1:3128:3128",
        "-v", f"{conf_path}:/etc/squid/squid.conf:ro",
        image,
    ])
    ok = getattr(result, "returncode", 1) == 0
    logger.info("[EGRESS] sidecar %s (%s)", "started" if ok else "FAILED", name)
    return name if ok else None
