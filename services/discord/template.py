"""
Discord Bot Template Copier
Copies the discord-bot-template to project directory.
"""
import shutil
from pathlib import Path
from typing import Tuple
from utils.logger import logger


# Template source path
TEMPLATE_SOURCE = Path(__file__).parent.parent.parent / "templates" / "discord-bot-template"


def copy_discord_template(project_path: str) -> Tuple[bool, str]:
    """
    Copy discord bot template to project directory.

    Args:
        project_path: Target project path (e.g., /root/dreampilot/projects/123/)

    Returns:
        Tuple of (success, message_or_path)
        - If success: (True, "Path to discord/ directory")
        - If failed: (False, "Error message")

    Structure created:
        {project_path}/
        └── discord/
            ├── main.py
            ├── config.py
            ├── commands/
            ├── services/
            ├── core/
            ├── models/
            └── utils/
    """
    try:
        # Validate source template exists
        if not TEMPLATE_SOURCE.exists():
            error_msg = f"Template source not found: {TEMPLATE_SOURCE}"
            logger.error(error_msg)
            return False, error_msg

        # Create target path
        target_path = Path(project_path) / "discord"

        # Remove existing discord directory if exists
        if target_path.exists():
            logger.warning(f"Removing existing discord directory: {target_path}")
            shutil.rmtree(target_path)

        # Copy template
        logger.info(f"Copying discord template from {TEMPLATE_SOURCE} to {target_path}")
        shutil.copytree(TEMPLATE_SOURCE, target_path)

        # Verify copy successful
        if not target_path.exists():
            error_msg = "Failed to copy template - target path not created"
            logger.error(error_msg)
            return False, error_msg

        # Verify critical files exist
        critical_files = [
            "main.py",
            "config.py",
            "requirements.txt",
            ".env.example",
            "commands/start.py",
            "services/ai_logic.py",
            "core/database.py",
            "llm/categories/index.json"
        ]

        missing_files = []
        for file_path in critical_files:
            if not (target_path / file_path).exists():
                missing_files.append(file_path)

        if missing_files:
            error_msg = f"Template copy incomplete - missing files: {missing_files}"
            logger.error(error_msg)
            # Cleanup partial copy
            shutil.rmtree(target_path)
            return False, error_msg

        logger.info(f"Discord template copied successfully to {target_path}")
        return True, str(target_path)

    except PermissionError as e:
        error_msg = f"Permission denied copying template: {e}"
        logger.error(error_msg)
        return False, error_msg

    except shutil.Error as e:
        error_msg = f"Copy error: {e}"
        logger.error(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"Unexpected error copying template: {e}"
        logger.error(error_msg)
        return False, error_msg


def verify_template_structure(template_path: str) -> Tuple[bool, list]:
    """
    Verify template has required structure.

    Args:
        template_path: Path to discord/ directory

    Returns:
        Tuple of (is_valid, missing_items)
    """
    template_dir = Path(template_path)

    required_structure = {
        "files": [
            "main.py",
            "config.py",
            "requirements.txt",
            ".env.example"
        ],
        "directories": [
            "commands",
            "services",
            "core",
            "models",
            "utils"
        ]
    }

    missing = []

    # Check files
    for file_name in required_structure["files"]:
        if not (template_dir / file_name).is_file():
            missing.append(f"file: {file_name}")

    # Check directories
    for dir_name in required_structure["directories"]:
        if not (template_dir / dir_name).is_dir():
            missing.append(f"directory: {dir_name}")

    is_valid = len(missing) == 0
    return is_valid, missing
