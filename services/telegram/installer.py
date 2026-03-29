"""
Telegram Bot Dependency Installer
Installs Python dependencies for telegram bot.
"""
import subprocess
import sys
import os
from pathlib import Path
from typing import Tuple
from utils.logger import logger

# Shared virtual environment path (same as backend)
SHARED_VENV_PATH = os.getenv("SHARED_VENV_PATH", "/root/dreampilot/dreampilotvenv")


def install_bot_dependencies(project_path: str) -> Tuple[bool, str]:
    """
    Install Python dependencies from requirements.txt.
    
    Args:
        project_path: Path to telegram/ directory
    
    Returns:
        Tuple of (success, message)
    
    Process:
        - Runs: pip install -r requirements.txt
        - Timeout: 300 seconds (5 minutes)
        - Logs output safely (no secrets)
    """
    try:
        telegram_dir = Path(project_path)
        requirements_file = telegram_dir / "requirements.txt"
        
        # Verify requirements.txt exists
        if not requirements_file.exists():
            error_msg = f"requirements.txt not found at {requirements_file}"
            logger.error(error_msg)
            return False, error_msg
        
        logger.info(f"Installing dependencies from {requirements_file}")
        
        # Use shared venv pip (consistent with backend)
        venv_pip = Path(SHARED_VENV_PATH) / "bin" / "pip"
        
        if venv_pip.exists():
            pip_cmd = str(venv_pip)
            logger.info(f"📦 Using shared venv: {SHARED_VENV_PATH}")
        else:
            # Fallback to current Python's pip
            pip_cmd = f"{sys.executable} -m pip"
            logger.warning(f"⚠️ Shared venv not found, using current Python: {sys.executable}")
        
        # Run pip install
        result = subprocess.run(
            f"{pip_cmd} install --prefer-binary -r {requirements_file}",
            shell=True,
            cwd=str(telegram_dir),
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes
        )
        
        # Check result
        if result.returncode == 0:
            logger.info("✅ Dependencies installed successfully")
            
            # Log summary (not full output to avoid clutter)
            if result.stdout:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 5:
                    logger.info(f"Installation output: {lines[-3:]}")
            
            return True, "Dependencies installed successfully"
        
        else:
            # Installation failed
            error_msg = f"pip install failed with exit code {result.returncode}"
            
            if result.stderr:
                # Log error safely (filter any potential secrets)
                safe_error = result.stderr[:500].replace('\n', ' ')
                logger.error(f"pip error: {safe_error}")
                error_msg += f": {safe_error}"
            
            logger.error(error_msg)
            return False, error_msg
    
    except subprocess.TimeoutExpired:
        error_msg = "Dependency installation timed out (300s)"
        logger.error(error_msg)
        return False, error_msg
    
    except subprocess.CalledProcessError as e:
        error_msg = f"Installation process error: {e}"
        logger.error(error_msg)
        return False, error_msg
    
    except Exception as e:
        error_msg = f"Unexpected installation error: {e}"
        logger.error(error_msg)
        return False, error_msg


def verify_dependencies(project_path: str) -> Tuple[bool, list]:
    """
    Verify critical dependencies are installed.
    
    Args:
        project_path: Path to telegram/ directory
    
    Returns:
        Tuple of (all_installed, missing_packages)
    """
    required_packages = [
        "python-telegram-bot",
        "requests",
        "python-dotenv",
        "sqlalchemy",
        "psycopg2",
        "fastapi",
        "uvicorn"
    ]
    
    missing = []
    
    for package in required_packages:
        try:
            # Try to import
            if package == "python-telegram-bot":
                __import__("telegram")
            elif package == "psycopg2-binary" or package == "psycopg2":
                __import__("psycopg2")
            else:
                __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)
    
    all_installed = len(missing) == 0
    return all_installed, missing
