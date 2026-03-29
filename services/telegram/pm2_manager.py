"""
Telegram Bot PM2 Manager
Manages PM2 processes for telegram bots.
"""
import subprocess
import json
from typing import Tuple, Dict, Optional
from utils.logger import logger


def start_bot_pm2(project_id: int, project_path: str, port: int) -> Tuple[bool, str]:
    """
    Start telegram bot via PM2.
    
    Args:
        project_id: Project ID
        project_path: Path to telegram/ directory
        port: Port for webhook server
    
    Returns:
        Tuple of (success, message)
    
    Command:
        pm2 start main.py --name tg-bot-{project_id} --interpreter python3
    
    Requirements:
        - Unique process name
        - Do NOT restart all PM2
        - Do NOT affect other projects
    """
    try:
        process_name = f"tg-bot-{project_id}"
        telegram_dir = str(project_path)
        
        logger.info(f"Starting PM2 process: {process_name}")
        
        # PM2 ecosystem config
        ecosystem_config = {
            "name": process_name,
            "script": "main.py",
            "cwd": telegram_dir,
            "interpreter": "python3",
            "env": {
                "PORT": str(port),
                "PROJECT_ID": str(project_id)
            },
            "instances": 1,
            "autorestart": True,
            "watch": False,
            "max_memory_restart": "200M",
            "error_file": f"{telegram_dir}/logs/error.log",
            "out_file": f"{telegram_dir}/logs/out.log",
            "log_file": f"{telegram_dir}/logs/combined.log",
            "time": True
        }
        
        # Create logs directory
        import os
        logs_dir = os.path.join(telegram_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        
        # Start PM2 process
        result = subprocess.run(
            ["pm2", "start", "main.py", 
             "--name", process_name,
             "--interpreter", "python3",
             "--", "--port", str(port)],
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


def stop_bot_pm2(project_id: int) -> Tuple[bool, str]:
    """
    Stop telegram bot PM2 process.
    
    Args:
        project_id: Project ID
    
    Returns:
        Tuple of (success, message)
    """
    try:
        process_name = f"tg-bot-{project_id}"
        
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


def restart_bot_pm2(project_id: int) -> Tuple[bool, str]:
    """
    Restart telegram bot PM2 process.
    
    Args:
        project_id: Project ID
    
    Returns:
        Tuple of (success, message)
    """
    try:
        process_name = f"tg-bot-{project_id}"
        
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


def get_bot_status_pm2(project_id: int) -> Tuple[bool, Dict]:
    """
    Get PM2 status for telegram bot.
    
    Args:
        project_id: Project ID
    
    Returns:
        Tuple of (is_running, status_info)
    """
    try:
        process_name = f"tg-bot-{project_id}"
        
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


def delete_bot_pm2(project_id: int) -> Tuple[bool, str]:
    """
    Delete telegram bot PM2 process.
    
    Args:
        project_id: Project ID
    
    Returns:
        Tuple of (success, message)
    """
    try:
        process_name = f"tg-bot-{project_id}"
        
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
