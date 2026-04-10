"""
Discord Bot Dependency Installer
Installs Python dependencies for discord bot.
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
        project_path: Path to discord/ directory

    Returns:
        Tuple of (success, message)
    """
    try:
        discord_dir = Path(project_path)
        requirements_file = discord_dir / "requirements.txt"

        if not requirements_file.exists():
            error_msg = f"requirements.txt not found at {requirements_file}"
            logger.error(error_msg)
            return False, error_msg

        logger.info(f"Installing dependencies from {requirements_file}")

        # Use shared venv pip
        venv_pip = Path(SHARED_VENV_PATH) / "bin" / "pip"

        if venv_pip.exists():
            pip_cmd = str(venv_pip)
            logger.info(f"Using shared venv: {SHARED_VENV_PATH}")
        else:
            pip_cmd = f"{sys.executable} -m pip"
            logger.warning(f"Shared venv not found, using current Python: {sys.executable}")

        result = subprocess.run(
            f"{pip_cmd} install --prefer-binary -r {requirements_file}",
            shell=True,
            cwd=str(discord_dir),
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            logger.info("Dependencies installed successfully")

            if result.stdout:
                lines = result.stdout.strip().split('\n')
                if len(lines) > 5:
                    logger.info(f"Installation output: {lines[-3:]}")

            return True, "Dependencies installed successfully"

        else:
            error_msg = f"pip install failed with exit code {result.returncode}"

            if result.stderr:
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
        project_path: Path to discord/ directory

    Returns:
        Tuple of (all_installed, missing_packages)
    """
    required_packages = [
        "discord.py",
        "requests",
        "python-dotenv",
        "sqlalchemy",
        "psycopg2"
    ]

    missing = []

    for package in required_packages:
        try:
            if package == "discord.py":
                __import__("discord")
            elif package == "psycopg2-binary" or package == "psycopg2":
                __import__("psycopg2")
            else:
                __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)

    all_installed = len(missing) == 0
    return all_installed, missing
