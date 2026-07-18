"""
System metrics collector for the VPS monitoring dashboard.

Exposes a single function `collect()` that returns a dict describing the
current host's CPU, memory, disk, network, Docker, PostgreSQL, PM2 and
process state. Designed to be called on-demand (no daemon, no polling)
from the admin-only `/admin/system-metrics` endpoint.

Each block is wrapped so that a failure in one collector (e.g. Docker not
installed on this host) never breaks the whole response — the failing
section is returned as `{"error": "..."}` and the rest still works.

No network egress. No writes. Read-only by design.
"""

from __future__ import annotations

import os
import re
import json
import shutil
import socket
import logging
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Cap how long any external command can run. We are on-demand only, but a
# hung subprocess would still tie up the request — fail fast instead.
_CMD_TIMEOUT = 8


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _run(cmd: List[str], timeout: int = _CMD_TIMEOUT) -> Optional[str]:
    """Run a command, return stdout as text. Return None on any failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("command failed %s: %s", cmd, exc)
        return None


def _safe(fn, *args, **kwargs):
    """Run a collector, return its result or {"error": "..."} on exception."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — intentional broad guard
        logger.warning("collector %s failed: %s", getattr(fn, "__name__", "fn"), exc)
        return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────
# CPU / load
# ─────────────────────────────────────────────────────────────────────

def _cpu_info() -> Dict[str, Any]:
    """CPU utilisation, core count and load average."""
    info: Dict[str, Any] = {}

    # Load average — works on every Linux
    try:
        load1, load5, load15 = os.getloadavg()
        info["load"] = [round(load1, 2), round(load5, 2), round(load15, 2)]
    except (OSError, AttributeError):
        info["load"] = None

    # Core count
    try:
        info["cores"] = os.cpu_count() or 0
    except Exception:
        info["cores"] = None

    # Instantaneous utilisation from /proc/stat (sample over 0.2s).
    info["percent"] = _cpu_percent_proc()

    return info


def _cpu_percent_proc(interval: float = 0.2) -> Optional[float]:
    """Compute aggregate CPU % from /proc/stat deltas."""
    try:
        def _snapshot() -> Optional[List[int]]:
            with open("/proc/stat", "r") as fh:
                line = fh.readline()  # "cpu  user nice system idle iowait ..."
            parts = line.split()[1:]
            return [int(x) for x in parts[:4]]  # user, nice, system, idle

        a = _snapshot()
        if a is None:
            return None
        # Busy wait is fine for 200ms.
        import time
        time.sleep(interval)
        b = _snapshot()
        if b is None:
            return None

        idle_a = a[3]
        idle_b = b[3]
        total_a = sum(a)
        total_b = sum(b)

        total_delta = total_b - total_a
        idle_delta = idle_b - idle_a
        if total_delta <= 0:
            return 0.0
        return round((1.0 - idle_delta / total_delta) * 100.0, 2)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────
# Memory / swap
# ─────────────────────────────────────────────────────────────────────

def _meminfo() -> Dict[str, Any]:
    """Parse /proc/meminfo → GB-scale dict."""
    fields = {
        "MemTotal": "total_kb",
        "MemAvailable": "available_kb",
        "MemFree": "free_kb",
        "Cached": "cached_kb",
        "Buffers": "buffers_kb",
        "SwapTotal": "swap_total_kb",
        "SwapFree": "swap_free_kb",
    }
    raw: Dict[str, int] = {v: 0 for v in fields.values()}
    try:
        with open("/proc/meminfo", "r") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in fields:
                    # "  12345 kB"
                    num = rest.strip().split()[0]
                    raw[fields[key]] = int(num)
    except OSError:
        return {"error": "unable to read /proc/meminfo"}

    total = raw["total_kb"]
    available = raw["available_kb"] or raw["free_kb"] + raw["cached_kb"] + raw["buffers_kb"]
    used = max(total - available, 0)
    swap_total = raw["swap_total_kb"]
    swap_used = max(swap_total - raw["swap_free_kb"], 0)

    def gb(kb: int) -> float:
        return round(kb / 1024 / 1024, 2)

    return {
        "total_gb": gb(total),
        "used_gb": gb(used),
        "available_gb": gb(available),
        "cached_gb": gb(raw["cached_kb"] + raw["buffers_kb"]),
        "percent": round((used / total * 100), 2) if total else 0.0,
        "swap_total_gb": gb(swap_total),
        "swap_used_gb": gb(swap_used),
        "swap_percent": round((swap_used / swap_total * 100), 2) if swap_total else 0.0,
    }


# ─────────────────────────────────────────────────────────────────────
# Disk
# ─────────────────────────────────────────────────────────────────────

def _disk() -> List[Dict[str, Any]]:
    """Per-mount usage. Uses shutil.disk_usage for cross-platform safety."""
    mounts: List[Dict[str, Any]] = []

    seen = set()
    # Walk /proc/mounts to find real filesystems (skip tmpfs, sysfs, etc.)
    try:
        with open("/proc/mounts", "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mount, fstype = parts[0], parts[1], parts[2]
                if fstype in ("tmpfs", "devtmpfs", "sysfs", "proc", "cgroup", "cgroup2",
                              "overlay", "squashfs", "fuse.snapfuse", "fuse.gvfsd-fuse"):
                    continue
                if device in seen:
                    continue
                seen.add(device)
                if not os.path.isdir(mount):
                    continue
                try:
                    usage = shutil.disk_usage(mount)
                    mounts.append({
                        "mount": mount,
                        "device": device,
                        "fstype": fstype,
                        "used_gb": round(usage.used / 1024**3, 2),
                        "total_gb": round(usage.total / 1024**3, 2),
                        "free_gb": round(usage.free / 1024**3, 2),
                        "percent": round(usage.used / usage.total * 100, 2) if usage.total else 0.0,
                    })
                except (OSError, PermissionError):
                    continue
    except OSError:
        pass

    # Always ensure at least "/" is reported
    if not any(m["mount"] == "/" for m in mounts):
        try:
            usage = shutil.disk_usage("/")
            mounts.append({
                "mount": "/",
                "device": "/",
                "fstype": "unknown",
                "used_gb": round(usage.used / 1024**3, 2),
                "total_gb": round(usage.total / 1024**3, 2),
                "free_gb": round(usage.free / 1024**3, 2),
                "percent": round(usage.used / usage.total * 100, 2),
            })
        except OSError:
            pass

    return mounts


# ─────────────────────────────────────────────────────────────────────
# Network counters
# ─────────────────────────────────────────────────────────────────────

def _network() -> Dict[str, Any]:
    """Aggregate rx/tx bytes across non-loopback interfaces."""
    total_rx = 0
    total_tx = 0
    interfaces: Dict[str, Dict[str, int]] = {}
    try:
        base = "/sys/class/net"
        for iface in os.listdir(base):
            try:
                # Skip loopback and virtual bridges (keep docker0/veth* — those carry traffic)
                if iface == "lo":
                    continue
                rx_path = os.path.join(base, iface, "statistics/rx_bytes")
                tx_path = os.path.join(base, iface, "statistics/tx_bytes")
                with open(rx_path, "r") as fh:
                    rx = int(fh.read().strip())
                with open(tx_path, "r") as fh:
                    tx = int(fh.read().strip())
                interfaces[iface] = {"rx_bytes": rx, "tx_bytes": tx}
                total_rx += rx
                total_tx += tx
            except (OSError, ValueError):
                continue
    except OSError:
        pass

    return {
        "total_rx_gb": round(total_rx / 1024**3, 3),
        "total_tx_gb": round(total_tx / 1024**3, 3),
        "interfaces": interfaces,
    }


# ─────────────────────────────────────────────────────────────────────
# Docker
# ─────────────────────────────────────────────────────────────────────

def _docker() -> Dict[str, Any]:
    """Container list with status + per-container stats."""
    if not shutil.which("docker"):
        return {"available": False, "containers": []}

    # `docker ps` for the basic list (no formatting surprises, widely available)
    raw = _run(["docker", "ps", "--all", "--format", "{{json .}}"])
    if raw is None:
        return {"available": True, "error": "docker ps failed", "containers": []}

    containers: List[Dict[str, Any]] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        containers.append({
            "id": c.get("ID", ""),
            "name": c.get("Names", ""),
            "image": c.get("Image", ""),
            "status": c.get("Status", ""),
            "state": c.get("State", ""),
            "running": c.get("State", "").lower() == "running",
        })

    # Per-container CPU/RAM via `docker stats --no-stream`
    stats_raw = _run(["docker", "stats", "--no-stream", "--format", "{{json .}}"])
    if stats_raw:
        stats_by_name: Dict[str, Dict[str, Any]] = {}
        for line in stats_raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = s.get("Name", "").lstrip("/")
            cpu_str = s.get("CPUPerc", "0%").rstrip("%")
            mem_usage = s.get("MemUsage", "/")
            mem_used, _, mem_limit = mem_usage.partition("/")
            try:
                cpu_val = float(cpu_str)
            except ValueError:
                cpu_val = 0.0
            stats_by_name[name] = {
                "cpu_percent": cpu_val,
                "mem_used": mem_used.strip(),
                "mem_limit": mem_limit.strip(),
            }
        for c in containers:
            c.update(stats_by_name.get(c["name"], {}))

    return {"available": True, "containers": containers}


# ─────────────────────────────────────────────────────────────────────
# PostgreSQL (direct connection — does NOT use the app's pool)
# ─────────────────────────────────────────────────────────────────────

def _postgres() -> Dict[str, Any]:
    """Connection count, DB sizes, active queries, replication lag."""
    try:
        import psycopg2  # noqa: F401 — re-imported inside to keep top-level light
    except ImportError:
        return {"available": False, "error": "psycopg2 not installed"}

    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "dreampilot")
    user = os.getenv("DB_USER", "admin")
    password = os.getenv("DB_PASSWORD", "")

    import psycopg2
    try:
        conn = psycopg2.connect(
            host=host, port=port, dbname=db_name,
            user=user, password=password,
            connect_timeout=4,
        )
        conn.autocommit = True
    except Exception as exc:
        return {"available": False, "error": f"connection failed: {exc}"}

    def q(sql: str) -> List[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    result: Dict[str, Any] = {"available": True}
    try:
        result["connections"] = q(
            "SELECT count(*) AS n FROM pg_stat_activity"
        )[0]["n"]
    except Exception as exc:
        result["connections"] = None
        result["connections_error"] = str(exc)

    # Move on — `connections` is the only field read from pg_stat_activity above;
    # remaining sections are independent.

    try:
        result["db_sizes"] = q(
            """
            SELECT datname AS database,
                   pg_size_pretty(pg_database_size(datname)) AS size_pretty,
                   pg_database_size(datname) AS size_bytes
            FROM pg_database
            WHERE datistemplate = false
            ORDER BY size_bytes DESC
            LIMIT 10
            """
        )
    except Exception as exc:
        result["db_sizes"] = []
        result["db_sizes_error"] = str(exc)

    try:
        result["active_queries"] = q(
            """
            SELECT pid, state, wait_event_type, application_name,
                   date_trunc('second', now() - query_start) AS duration,
                   LEFT(query, 120) AS query
            FROM pg_stat_activity
            WHERE state != 'idle'
              AND pid != pg_backend_pid()
            ORDER BY query_start ASC
            LIMIT 10
            """
        )
    except Exception as exc:
        result["active_queries"] = []
        result["active_queries_error"] = str(exc)

    try:
        result["replication"] = q(
            """
            SELECT application_name, state, sync_state,
                   pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
            FROM pg_stat_replication
            """
        )
    except Exception:
        # On a standby / no replicas configured → not an error worth surfacing
        result["replication"] = []

    try:
        result["uptime"] = q(
            "SELECT now() - pg_postmaster_start_time() AS uptime"
        )[0]["uptime"]
    except Exception:
        pass

    try:
        conn.close()
    except Exception:
        pass

    return result


# ─────────────────────────────────────────────────────────────────────
# PM2
# ─────────────────────────────────────────────────────────────────────

def _pm2() -> Dict[str, Any]:
    """PM2 process list via `pm2 jlist`."""
    if not shutil.which("pm2"):
        return {"available": False, "processes": []}

    raw = _run(["pm2", "jlist"])
    if raw is None:
        return {"available": True, "error": "pm2 jlist failed", "processes": []}

    try:
        procs = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"available": True, "error": f"pm2 jlist parse failed: {exc}", "processes": []}

    cleaned: List[Dict[str, Any]] = []
    for p in procs:
        mon = p.get("monit") or {}
        pm2_env = p.get("pm2_env") or {}
        cleaned.append({
            "name": p.get("name", ""),
            "status": pm2_env.get("status", ""),
            "restarts": pm2_env.get("restart_time", 0),
            "uptime_ms": pm2_env.get("pm_uptime", 0),
            "unstable_restarts": pm2_env.get("unstable_restarts", 0),
            "cpu": mon.get("cpu", 0),
            "memory_mb": round((mon.get("memory", 0) or 0) / 1024 / 1024, 1),
            "pid": pm2_env.get("pid"),
            "exit_code": pm2_env.get("exit_code"),
        })

    return {"available": True, "processes": cleaned}


# ─────────────────────────────────────────────────────────────────────
# OOM events (kernel log)
# ─────────────────────────────────────────────────────────────────────

def _oom_events() -> Dict[str, Any]:
    """Count OOM kills from the last 24h of kernel logs."""
    if not shutil.which("journalctl"):
        # Fallback: dmesg tail
        dmesg = _run(["dmesg", "--ctime", "--color=never"]) or ""
        if not dmesg:
            return {"available": False, "count_24h": 0}
        matches = re.findall(r"Out of memory|Killed process", dmesg)
        return {"available": True, "source": "dmesg", "count_24h": len(matches)}

    raw = _run(["journalctl", "-k", "--since", "24 hours ago",
                "--grep", "Out of memory|Killed process|oom-killer",
                "--no-pager", "--output=short-iso"])
    if raw is None:
        return {"available": True, "count_24h": 0}

    lines = [ln for ln in raw.splitlines() if ln.strip()
             and not ln.startswith("--")]
    return {
        "available": True,
        "source": "journalctl",
        "count_24h": len(lines),
        "recent": lines[-3:],
    }


# ─────────────────────────────────────────────────────────────────────
# Top processes by CPU and RAM
# ─────────────────────────────────────────────────────────────────────

def _top_procs() -> Dict[str, Any]:
    """Top 5 processes by CPU% and by RAM."""
    raw = _run(["ps", "-eo", "pid,pcpu,pmem,rss,comm", "--no-headers", "--sort=-pcpu"])
    by_cpu: List[Dict[str, Any]] = []
    if raw:
        for line in raw.splitlines()[:5]:
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            try:
                by_cpu.append({
                    "pid": int(parts[0]),
                    "cpu": float(parts[1]),
                    "mem_percent": float(parts[2]),
                    "rss_mb": round(int(parts[3]) / 1024, 1),
                    "name": parts[4].strip(),
                })
            except ValueError:
                continue

    raw = _run(["ps", "-eo", "pid,pcpu,pmem,rss,comm", "--no-headers", "--sort=-rss"])
    by_mem: List[Dict[str, Any]] = []
    if raw:
        for line in raw.splitlines()[:5]:
            parts = line.split(None, 4)
            if len(parts) < 5:
                continue
            try:
                by_mem.append({
                    "pid": int(parts[0]),
                    "cpu": float(parts[1]),
                    "mem_percent": float(parts[2]),
                    "rss_mb": round(int(parts[3]) / 1024, 1),
                    "name": parts[4].strip(),
                })
            except ValueError:
                continue

    return {"by_cpu": by_cpu, "by_mem": by_mem}


# ─────────────────────────────────────────────────────────────────────
# Uptime
# ─────────────────────────────────────────────────────────────────────

def _uptime_hours() -> Optional[float]:
    try:
        with open("/proc/uptime", "r") as fh:
            seconds = float(fh.read().split()[0])
        return round(seconds / 3600, 2)
    except (OSError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────

def collect() -> Dict[str, Any]:
    """
    Collect all host metrics. On-demand only.

    Returns a dict safe to JSON-serialise and serve to the admin dashboard.
    Any single failing collector is isolated — see `_safe`.
    """
    return {
        "hostname": socket.gethostname(),
        "role": os.getenv("DREAMAGENT_ROLE") or "main",
        "ts": datetime.now(timezone.utc).isoformat(),
        "uptime_h": _uptime_hours(),
        "cpu": _safe(_cpu_info),
        "memory": _safe(_meminfo),
        "disk": _safe(_disk),
        "network": _safe(_network),
        "docker": _safe(_docker),
        "postgres": _safe(_postgres),
        "pm2": _safe(_pm2),
        "oom_events": _safe(_oom_events),
        "top_procs": _safe(_top_procs),
    }
