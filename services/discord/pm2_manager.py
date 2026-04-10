"""
Discord Bot PM2 Manager
Manages PM2 processes for discord bots.
"""
import subprocess
import sys
import os
import json
from typing import Tuple, Dict, Optional
from utils.logger import logger

# Shared virtual environment path (same as backend)
SHARED_VENV_PATH = os.getenv("SHARED_VENV_PATH", "/root/dreampilot/dreampilotvenv")


def _get_process_name(project_id: int) -> str:
    """Get PM2 process name for a discord bot."""
    return f"dc-bot-{project_id}"


def start_bot_pm2(
    project_id: int,
    project_path: str,
    port: int,
    domain: Optional[str] = None,
    bot_token: Optional[str] = None,
    webhook_url: Optional[str] = None,
    database_url: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Start discord bot via PM2.

    Args:
        project_id: Project ID
        project_path: Path to discord/ directory
        port: Port for health server
        domain: Domain name (for env injection)
        bot_token: Discord bot token (required)
        webhook_url: Not used for Discord (placeholder)
        database_url: Database connection URL (optional)

    Returns:
        Tuple of (success, message)
    """
    try:
        process_name = _get_process_name(project_id)
        discord_dir = str(project_path)

        logger.info(f"Starting PM2 process: {process_name}")

        # Create logs directory
        logs_dir = os.path.join(discord_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)

        # Build environment variables
        env_vars = {
            "PORT": str(port),
            "PROJECT_ID": str(project_id)
        }

        if bot_token:
            env_vars["DISCORD_TOKEN"] = bot_token
            logger.info(f"  DISCORD_TOKEN: ***{bot_token[-6:]}")
        else:
            logger.error("DISCORD_TOKEN is required!")
            return False, "DISCORD_TOKEN is required"

        if database_url:
            env_vars["DATABASE_URL"] = database_url
            logger.info(f"  DATABASE_URL: ***{database_url[-20:]}")

        if domain:
            env_vars["WEBHOOK_DOMAIN"] = domain

        # Use shared venv Python
        venv_python = os.path.join(SHARED_VENV_PATH, "bin", "python")

        if os.path.exists(venv_python):
            interpreter = venv_python
            logger.info(f"Using shared venv: {SHARED_VENV_PATH}")
        else:
            interpreter = sys.executable
            logger.warning(f"Shared venv not found, using current Python: {sys.executable}")

        # Read existing .env file and merge
        env_file_path = os.path.join(discord_dir, ".env")
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key not in env_vars:
                            env_vars[key] = value
            logger.info(f"Loaded existing .env: {env_file_path}")

        # Write back merged env vars
        with open(env_file_path, 'w') as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
        logger.info(f"Updated .env file with {len(env_vars)} variables")

        # Build PM2 start command
        pm2_cmd = [
            "pm2", "start", "main.py",
            "--name", process_name,
            "--interpreter", interpreter,
            "--cwd", discord_dir,
            "--log", f"{discord_dir}/logs/out.log",
            "--error", f"{discord_dir}/logs/error.log",
            "--time",
            "--env", "production"
        ]

        # Start PM2 with environment variables
        process_env = os.environ.copy()
        process_env.update(env_vars)

        result = subprocess.run(
            pm2_cmd,
            cwd=discord_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env=process_env
        )

        if result.returncode == 0:
            logger.info(f"PM2 process started: {process_name}")
            logger.info(f"PM2 output: {result.stdout[:200]}")
            return True, f"Bot started as {process_name}"

        else:
            error_msg = f"PM2 start failed (exit {result.returncode})"
            if result.stderr:
                logger.error(f"PM2 error: {result.stderr[:500]}")
                error_msg += f": {result.stderr[:200]}"
            return False, error_msg

    except subprocess.TimeoutExpired:
        error_msg = "PM2 start command timed out"
        logger.error(error_msg)
        return False, error_msg

    except subprocess.CalledProcessError as e:
        error_msg = f"PM2 process error: {e}"
        logger.error(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"Unexpected PM2 error: {e}"
        logger.error(error_msg)
        return False, error_msg


def stop_bot_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, str]:
    """Stop discord bot PM2 process."""
    try:
        process_name = _get_process_name(project_id)
        logger.info(f"Stopping PM2 process: {process_name}")

        result = subprocess.run(
            ["pm2", "stop", process_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            logger.info(f"PM2 process stopped: {process_name}")
            return True, f"Bot {process_name} stopped"
        else:
            return False, f"PM2 stop failed for {process_name}"

    except Exception as e:
        logger.error(f"Error stopping PM2 process: {e}")
        return False, str(e)


def restart_bot_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, str]:
    """Restart discord bot PM2 process."""
    try:
        process_name = _get_process_name(project_id)
        logger.info(f"Restarting PM2 process: {process_name}")

        result = subprocess.run(
            ["pm2", "restart", process_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            logger.info(f"PM2 process restarted: {process_name}")
            return True, f"Bot {process_name} restarted"
        else:
            return False, f"PM2 restart failed for {process_name}"

    except Exception as e:
        logger.error(f"Error restarting PM2 process: {e}")
        return False, str(e)


def get_bot_status_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, Dict]:
    """Get PM2 status for discord bot."""
    try:
        process_name = _get_process_name(project_id)

        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            processes = json.loads(result.stdout)

            for proc in processes:
                if proc.get("name") == process_name:
                    status_info = {
                        "name": proc.get("name"),
                        "status": proc.get("pm2_env", {}).get("status"),
                        "uptime": proc.get("pm2_env", {}).get("pm_uptime"),
                        "restarts": proc.get("pm2_env", {}).get("restart_time"),
                        "memory": proc.get("monit", {}).get("memory"),
                        "cpu": proc.get("monit", {}).get("cpu"),
                        "pid": proc.get("pid")
                    }
                    is_running = status_info["status"] == "online"
                    return is_running, status_info

            return False, {"status": "not_found", "name": process_name}

        else:
            return False, {"status": "error", "error": "PM2 list failed"}

    except Exception as e:
        logger.error(f"Error getting PM2 status: {e}")
        return False, {"status": "error", "error": str(e)}


def delete_bot_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, str]:
    """Delete discord bot PM2 process."""
    try:
        process_name = _get_process_name(project_id)
        logger.info(f"Deleting PM2 process: {process_name}")

        result = subprocess.run(
            ["pm2", "delete", process_name],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            logger.info(f"PM2 process deleted: {process_name}")
            return True, f"Bot {process_name} deleted"
        else:
            return False, f"PM2 delete failed for {process_name}"

    except Exception as e:
        logger.error(f"Error deleting PM2 process: {e}")
        return False, str(e)
