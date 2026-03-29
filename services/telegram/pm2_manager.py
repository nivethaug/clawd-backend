"""
Telegram Bot PM2 Manager
Manages PM2 processes for telegram bots.
"""
import subprocess
import sys
import os
import json
from typing import Tuple, Dict, Optional
from utils.logger import logger

# Shared virtual environment path (same as backend)
SHARED_VENV_PATH = os.getenv("SHARED_VENV_PATH", "/root/dreampilot/dreampilotvenv")


def start_bot_pm2(project_id: int, project_path: str, port: int, domain: Optional[str] = None) -> Tuple[bool, str]:
    """
    Start telegram bot via PM2.
    
    Args:
        project_id: Project ID
        project_path: Path to telegram/ directory
        port: Port for webhook server
        domain: Domain name (preferred for PM2 naming)
    
    Returns:
        Tuple of (success, message)
    
    Command:
        pm2 start main.py --name {domain}-bot --interpreter python3
    
    Requirements:
        - Unique process name
        - Do NOT restart all PM2
        - Do NOT affect other projects
    """
    try:
        # Use domain if available, otherwise fall back to project_id
        process_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
        telegram_dir = str(project_path)
        
        logger.info(f"Starting PM2 process: {process_name}")
        
        # Create logs directory
        logs_dir = os.path.join(telegram_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # Load environment variables from .env file in telegram directory
        env_file_path = os.path.join(telegram_dir, ".env")
        env_vars = {}  # Start fresh for PM2 env
        
        # Load .env file if it exists
        if os.path.exists(env_file_path):
            logger.info(f"📦 Loading environment from: {env_file_path}")
            with open(env_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
                        # Log important vars (mask sensitive values)
                        if key.strip() == 'BOT_TOKEN':
                            logger.info(f"  BOT_TOKEN: ***{value.strip()[-6:]}")
                        elif key.strip() in ['WEBHOOK_URL', 'PORT']:
                            logger.info(f"  {key.strip()}: {value.strip()}")
        else:
            logger.warning(f"⚠️ No .env file found at: {env_file_path}")
        
        # Add runtime variables (these override .env if needed)
        env_vars["PORT"] = str(port)
        env_vars["PROJECT_ID"] = str(project_id)
        
        # Use shared venv Python (same as installer.py)
        venv_python = os.path.join(SHARED_VENV_PATH, "bin", "python")
        
        if os.path.exists(venv_python):
            interpreter = venv_python
            logger.info(f"📦 Using shared venv: {SHARED_VENV_PATH}")
        else:
            # Fallback to current Python
            interpreter = sys.executable
            logger.warning(f"⚠️ Shared venv not found, using current Python: {sys.executable}")
        
        # Create ecosystem.config.json for PM2 (proper way to pass env vars)
        ecosystem_config = {
            "name": process_name,
            "script": "main.py",
            "cwd": telegram_dir,
            "interpreter": interpreter,
            "instances": 1,
            "autorestart": True,
            "watch": False,
            "max_memory_restart": "200M",
            "env": env_vars,  # All environment variables including BOT_TOKEN
            "error_file": f"{telegram_dir}/logs/error.log",
            "out_file": f"{telegram_dir}/logs/out.log",
            "log_date_format": "YYYY-MM-DD HH:mm:ss Z"
        }
        
        # Write ecosystem config file
        ecosystem_path = os.path.join(telegram_dir, "ecosystem.config.json")
        with open(ecosystem_path, 'w') as f:
            json.dump({"apps": [ecosystem_config]}, f, indent=2)
        logger.info(f"📝 Created ecosystem config: {ecosystem_path}")
        
        # Start PM2 using ecosystem config (this properly passes env vars)
        result = subprocess.run(
            ["pm2", "start", ecosystem_path],
            cwd=telegram_dir,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"✅ PM2 process started: {process_name}")
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
    """
    Stop telegram bot PM2 process.
    
    Args:
        project_id: Project ID
        domain: Domain name (preferred for PM2 naming)
    
    Returns:
        Tuple of (success, message)
    """
    try:
        # Use domain if available, otherwise fall back to project_id
        process_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
        
        logger.info(f"Stopping PM2 process: {process_name}")
        
        result = subprocess.run(
            ["pm2", "stop", process_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"✅ PM2 process stopped: {process_name}")
            return True, f"Bot {process_name} stopped"
        else:
            error_msg = f"PM2 stop failed for {process_name}"
            logger.error(error_msg)
            return False, error_msg
    
    except Exception as e:
        error_msg = f"Error stopping PM2 process: {e}"
        logger.error(error_msg)
        return False, error_msg


def restart_bot_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, str]:
    """
    Restart telegram bot PM2 process.
    
    Args:
        project_id: Project ID
        domain: Domain name (preferred for PM2 naming)
    
    Returns:
        Tuple of (success, message)
    """
    try:
        # Use domain if available, otherwise fall back to project_id
        process_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
        
        logger.info(f"Restarting PM2 process: {process_name}")
        
        result = subprocess.run(
            ["pm2", "restart", process_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"✅ PM2 process restarted: {process_name}")
            return True, f"Bot {process_name} restarted"
        else:
            error_msg = f"PM2 restart failed for {process_name}"
            logger.error(error_msg)
            return False, error_msg
    
    except Exception as e:
        error_msg = f"Error restarting PM2 process: {e}"
        logger.error(error_msg)
        return False, error_msg


def get_bot_status_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, Dict]:
    """
    Get PM2 status for telegram bot.
    
    Args:
        project_id: Project ID
        domain: Domain name (preferred for PM2 naming)
    
    Returns:
        Tuple of (is_running, status_info)
    """
    try:
        # Use domain if available, otherwise fall back to project_id
        process_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
        
        # Get PM2 list in JSON format
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            processes = json.loads(result.stdout)
            
            # Find our process
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
            
            # Process not found
            return False, {"status": "not_found", "name": process_name}
        
        else:
            return False, {"status": "error", "error": "PM2 list failed"}
    
    except Exception as e:
        logger.error(f"Error getting PM2 status: {e}")
        return False, {"status": "error", "error": str(e)}


def delete_bot_pm2(project_id: int, domain: Optional[str] = None) -> Tuple[bool, str]:
    """
    Delete telegram bot PM2 process.
    
    Args:
        project_id: Project ID
        domain: Domain name (preferred for PM2 naming)
    
    Returns:
        Tuple of (success, message)
    """
    try:
        # Use domain if available, otherwise fall back to project_id
        process_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
        
        logger.info(f"Deleting PM2 process: {process_name}")
        
        result = subprocess.run(
            ["pm2", "delete", process_name],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            logger.info(f"✅ PM2 process deleted: {process_name}")
            return True, f"Bot {process_name} deleted"
        else:
            error_msg = f"PM2 delete failed for {process_name}"
            logger.error(error_msg)
            return False, error_msg
    
    except Exception as e:
        error_msg = f"Error deleting PM2 process: {e}"
        logger.error(error_msg)
        return False, error_msg
