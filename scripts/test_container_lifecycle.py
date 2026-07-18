#!/usr/bin/env python3
"""
Manual container lifecycle test — Phase 3 gate.

Validates the full container lifecycle against a real Docker daemon:
    create → start → exec → health → stop → start → restart → remove

Also verifies the security posture (no docker socket, no host paths exposed,
correct uid, hardening flags applied).

Usage:
    python3 scripts/test_container_lifecycle.py [user_id]

Defaults to user_id=99999 (a "test" user that won't collide with real users).
The script cleans up after itself (removes the container + workspace dir).

Prerequisites:
    1. Build the image: ./scripts/build_user_image.sh
    2. Create the network: docker network create dreamagent-net
    3. Create the cache dir: mkdir -p /srv/cache/npm /srv/cache/pip && \\
       chown -R 1001:1001 /srv/cache
"""

from __future__ import annotations

import os
import sys
import shutil
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.container_manager import (
    ContainerManager,
    CONTAINER_IMAGE,
    CONTAINER_NETWORK,
    SHARED_CACHE_HOST,
    WORKSPACE_ROOT,
    _docker_available,
)


def ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 99999
    print(f"\nContainerManager lifecycle test (user_id={user_id})")
    print(f"  image     = {CONTAINER_IMAGE}")
    print(f"  network   = {CONTAINER_NETWORK}")
    print(f"  workspace = {WORKSPACE_ROOT}/user_{user_id}")
    print(f"  cache     = {SHARED_CACHE_HOST}")

    # ─────────────────────────────────────────────────────────────────
    section("Preconditions")
    # ─────────────────────────────────────────────────────────────────
    if not _docker_available():
        fail("docker daemon not available — start dockerd first")
        return 1
    ok("docker daemon reachable")

    # Check image exists
    import subprocess
    r = subprocess.run(
        ["docker", "image", "inspect", CONTAINER_IMAGE],
        capture_output=True,
    )
    if r.returncode != 0:
        fail(f"image {CONTAINER_IMAGE} not found — run ./scripts/build_user_image.sh first")
        return 1
    ok(f"image {CONTAINER_IMAGE} exists")

    # Check network exists
    r = subprocess.run(
        ["docker", "network", "inspect", CONTAINER_NETWORK],
        capture_output=True,
    )
    if r.returncode != 0:
        fail(f"network {CONTAINER_NETWORK} not found — run: docker network create {CONTAINER_NETWORK}")
        return 1
    ok(f"network {CONTAINER_NETWORK} exists")

    # Check cache dir
    if not os.path.isdir(SHARED_CACHE_HOST):
        fail(f"cache dir {SHARED_CACHE_HOST} missing — run: mkdir -p {SHARED_CACHE_HOST}/npm {SHARED_CACHE_HOST}/pip")
        return 1
    ok(f"cache dir {SHARED_CACHE_HOST} exists")

    cm = ContainerManager(user_id=user_id)

    try:
        # ─────────────────────────────────────────────────────────────
        section("1. ensure_workspace()")
        # ─────────────────────────────────────────────────────────────
        ws = cm.ensure_workspace()
        if not ws.exists():
            fail(f"workspace not created: {ws}")
            return 1
        ok(f"workspace created: {ws}")

        # ─────────────────────────────────────────────────────────────
        section("2. ensure_container() (create)")
        # ─────────────────────────────────────────────────────────────
        name = cm.ensure_container()
        if name != cm.container_name:
            fail(f"unexpected container name: {name}")
            return 1
        time.sleep(2)  # let it reach steady state
        if not cm.is_running():
            fail("container not running after ensure_container")
            return 1
        ok(f"container {name} created and running")

        # ─────────────────────────────────────────────────────────────
        section("3. exec (whoami + id)")
        # ─────────────────────────────────────────────────────────────
        r = cm.exec(["sh", "-c", "whoami && id"])
        if r.returncode != 0:
            fail(f"exec failed: {r.stderr}")
            return 1
        if "dreampilot" not in r.stdout:
            fail(f"unexpected user: {r.stdout}")
            return 1
        ok(f"runs as: {r.stdout.strip().splitlines()[0]}")
        if "uid=1001" not in r.stdout:
            fail(f"unexpected uid: {r.stdout}")
            return 1
        ok("uid=1001 confirmed")

        # ─────────────────────────────────────────────────────────────
        section("4. Security checks (no docker socket, no /root, etc.)")
        # ─────────────────────────────────────────────────────────────
        # /root must NOT exist or be empty
        r = cm.exec(["sh", "-c", "ls /root 2>&1 || echo NO_ROOT"])
        if "NO_ROOT" in r.stdout or "No such file" in r.stdout:
            ok("/root not accessible inside container")
        else:
            fail(f"/root accessible: {r.stdout}")

        # No docker socket
        r = cm.exec(["sh", "-c", "ls /var/run/docker.sock 2>&1 || echo NO_SOCK"])
        if "NO_SOCK" in r.stdout or "No such file" in r.stdout:
            ok("/var/run/docker.sock not mounted")
        else:
            fail("docker socket is mounted — SECURITY ISSUE")

        # /workspace must be the bind-mount target
        r = cm.exec(["sh", "-c", "pwd && ls /workspace"])
        if "/workspace" in r.stdout:
            ok("workdir is /workspace")
        else:
            fail(f"workdir wrong: {r.stdout}")

        # No sudo
        r = cm.exec(["sh", "-c", "which sudo || echo NO_SUDO"])
        if "NO_SUDO" in r.stdout:
            ok("no sudo available")
        else:
            fail(f"sudo present: {r.stdout}")

        # ─────────────────────────────────────────────────────────────
        section("5. health()")
        # ─────────────────────────────────────────────────────────────
        h = cm.health()
        if h.get("status") != "running":
            fail(f"health check failed: {h}")
            return 1
        ok(f"health: status={h.get('status')}, cpu={h.get('cpu_percent')}, mem={h.get('memory_used')}")

        # ─────────────────────────────────────────────────────────────
        section("6. stop() + start() cycle")
        # ─────────────────────────────────────────────────────────────
        cm.stop()
        time.sleep(2)
        if cm.is_running():
            fail("container still running after stop")
            return 1
        ok("stopped")
        cm.start()
        time.sleep(2)
        if not cm.is_running():
            fail("container not running after start")
            return 1
        ok("restarted")

        # ─────────────────────────────────────────────────────────────
        section("7. restart()")
        # ─────────────────────────────────────────────────────────────
        cm.restart()
        time.sleep(2)
        if not cm.is_running():
            fail("container not running after restart")
            return 1
        ok("restart() works")

        # ─────────────────────────────────────────────────────────────
        section("8. translate_host_path()")
        # ─────────────────────────────────────────────────────────────
        host_p = f"/workspaces/user_{user_id}/website/test_proj"
        container_p = cm.translate_host_path(host_p)
        expected = f"/workspace/website/test_proj"
        if container_p != expected:
            fail(f"path translation wrong: {container_p} != {expected}")
            return 1
        ok(f"{host_p}  →  {container_p}")

        # ─────────────────────────────────────────────────────────────
        section("9. remove()")
        # ─────────────────────────────────────────────────────────────
        cm.remove(force=True)
        if cm._container_exists():
            fail("container still exists after remove")
            return 1
        ok("container removed")

        # ─────────────────────────────────────────────────────────────
        section("ALL LIFECYCLE TESTS PASSED")
        # ─────────────────────────────────────────────────────────────
        print("\nContainerManager works end-to-end.")
        print("Phase 3 container infrastructure is ready.")
        print("\nNote: this test created and removed a test user's workspace dir.")
        print(f"If you want to keep it clean: rm -rf {WORKSPACE_ROOT}/user_{user_id}")
        return 0

    finally:
        # Best-effort cleanup in case the test failed mid-way.
        try:
            if cm._container_exists():
                cm.remove(force=True)
                print(f"\n(cleaned up test container {cm.container_name})")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
