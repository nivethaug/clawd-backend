#!/usr/bin/env python3
"""Admin system health — VPS monitoring (RAM, storage, CPU, uptime, Docker).

Admin-only. Shows infrastructure health for main + all workers.
Never exposes Claude Code sessions, user data, or credentials.
"""
import logging
import os
import subprocess
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

logger = logging.getLogger("api.system_health")
router = APIRouter()


def _require_admin(authorization: Optional[str]) -> int:
    from utils.auth_helpers import get_user_id_from_token
    user_id = get_user_id_from_token(authorization)
    from app import require_admin
    require_admin(user_id)
    return user_id


def _get_system_stats() -> dict:
    """Local system stats via /proc and df."""
    import shutil
    import time

    # Memory
    meminfo = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split(":")
            if len(parts) == 2:
                meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])  # KB

    total_mb = meminfo.get("MemTotal", 0) // 1024
    available_mb = meminfo.get("MemAvailable", 0) // 1024
    used_mb = total_mb - available_mb
    buffers_mb = meminfo.get("Buffers", 0) // 1024
    cache_mb = meminfo.get("Cached", 0) // 1024
    swap_total_mb = meminfo.get("SwapTotal", 0) // 1024
    swap_free_mb = meminfo.get("SwapFree", 0) // 1024
    swap_used_mb = swap_total_mb - swap_free_mb

    # Storage
    disk = shutil.disk_usage("/")
    disk_total_gb = disk.total // (1024**3)
    disk_used_gb = disk.used // (1024**3)
    disk_free_gb = disk.free // (1024**3)

    # CPU load
    load1, load5, load15 = os.getloadavg()
    cpu_count = os.cpu_count() or 1

    # Uptime
    with open("/proc/uptime") as f:
        uptime_seconds = float(f.read().split()[0])
    uptime_days = int(uptime_seconds // 86400)
    uptime_hours = int((uptime_seconds % 86400) // 3600)

    # OOM check (kernel log)
    oom_count = 0
    try:
        result = subprocess.run(
            ["dmesg", "--time-format", "iso", "|", "grep", "-c", "Out of memory"],
            capture_output=True, text=True, timeout=5, shell=True,
        )
        oom_count = int(result.stdout.strip() or 0)
    except Exception:
        pass

    return {
        "memory": {
            "total_mb": total_mb,
            "used_mb": used_mb,
            "available_mb": available_mb,
            "buffers_mb": buffers_mb,
            "cache_mb": cache_mb,
            "swap_total_mb": swap_total_mb,
            "swap_used_mb": swap_used_mb,
            "usage_pct": round(100 * used_mb / total_mb, 1) if total_mb else 0,
        },
        "storage": {
            "total_gb": disk_total_gb,
            "used_gb": disk_used_gb,
            "free_gb": disk_free_gb,
            "usage_pct": round(100 * disk_used_gb / disk_total_gb, 1) if disk_total_gb else 0,
        },
        "cpu": {
            "cores": cpu_count,
            "load_1m": round(load1, 2),
            "load_5m": round(load5, 2),
            "load_15m": round(load15, 2),
            "load_pct": round(100 * load1 / cpu_count, 1) if cpu_count else 0,
        },
        "uptime": {
            "days": uptime_days,
            "hours": uptime_hours,
            "seconds": int(uptime_seconds),
        },
        "oom_events": oom_count,
    }


def _get_docker_stats() -> list:
    """Running Docker containers with resource usage."""
    try:
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format",
             "{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}|{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        containers = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                containers.append({
                    "name": parts[0],
                    "memory": parts[1],
                    "cpu": parts[2],
                    "status": parts[3],
                })
        return containers
    except Exception:
        return []


def _get_remote_stats(host: str, timeout: int = 10) -> dict:
    """Fetch stats from a remote worker via SSH."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={timeout}",
             "root@" + host,
             "python3 -c \""
             "import os,shutil;"
             "m={};" 
             "[m.update({p.split(':')[0].strip():int(p.split(':')[1].strip().split()[0])}) for p in open('/proc/meminfo') if ':' in p];"
             "t=m.get('MemTotal',0)//1024;a=m.get('MemAvailable',0)//1024;"
             "d=shutil.disk_usage('/');"
             "l=os.getloadavg();"
             "u=float(open('/proc/uptime').read().split()[0]);"
             "print(f'{t}|{a}|{d.total//(1024**3)}|{d.used//(1024**3)}|{l[0]:.2f}|{os.cpu_count()}|{int(u//86400)}|{int((u%86400)//3600)}')"
             "\""],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|")
            if len(parts) >= 8:
                total, avail, dt, du, load, cores, days, hours = parts
                total, avail = int(total), int(avail)
                return {
                    "memory": {
                        "total_mb": total,
                        "used_mb": total - avail,
                        "available_mb": avail,
                        "usage_pct": round(100 * (total - avail) / total, 1) if total else 0,
                    },
                    "storage": {
                        "total_gb": int(dt),
                        "used_gb": int(du),
                        "free_gb": int(dt) - int(du),
                        "usage_pct": round(100 * int(du) / int(dt), 1) if int(dt) else 0,
                    },
                    "cpu": {
                        "cores": int(cores),
                        "load_1m": float(load),
                        "load_pct": round(100 * float(load) / int(cores), 1),
                    },
                    "uptime": {"days": int(days), "hours": int(hours)},
                }
    except Exception as exc:
        logger.warning("[HEALTH] remote stats failed for %s: %s", host, exc)
    return {"error": "unreachable"}


@router.get("/api/admin/system-health")
async def system_health(authorization: Optional[str] = Header(None)):
    """Full infrastructure health: main + shared worker + all dedicated workers."""
    _require_admin(authorization)

    from database_adapter import get_db
    from services.worker_registry import list_nodes

    # Main VPS stats
    main_stats = _get_system_stats()
    main_docker = _get_docker_stats()

    # Shared worker stats (via SSH)
    shared_ip = "187.55.225.39"
    shared_stats = _get_remote_stats(shared_ip)
    shared_docker = []
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
             f"root@{shared_ip}",
             "docker stats --no-stream --format '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}|{{.Status}}'"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                shared_docker.append({
                    "name": parts[0], "memory": parts[1],
                    "cpu": parts[2], "status": parts[3],
                })
    except Exception:
        pass

    # Dedicated workers from registry
    dedicated = []
    for node_id, node in list_nodes().items():
        if node.get("is_shared"):
            continue
        ip = node.get("server_ip") or ""
        if not ip:
            continue
        stats = _get_remote_stats(ip)
        dedicated.append({
            "id": node_id,
            "name": node.get("name", node_id),
            "ip": ip,
            "status": node.get("status", "unknown"),
            "stats": stats,
        })

    return {
        "main": {
            "name": "Main VPS",
            "ip": "195.200.14.37",
            "role": "api + frontend + postgres",
            "stats": main_stats,
            "docker": main_docker,
        },
        "shared_worker": {
            "name": "Shared Worker",
            "ip": shared_ip,
            "role": "project builds + deployments",
            "stats": shared_stats,
            "docker": shared_docker,
        },
        "dedicated_workers": dedicated,
        "timestamp": os.uname().machine,
    }
