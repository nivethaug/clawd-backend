"""
Project Manager module for Clawd Backend.
Handles project folder creation, cleanup, and filesystem operations.
"""

import os
import shutil
import re
import subprocess
from datetime import datetime

BASE_PROJECTS_DIR = "/var/lib/openclaw/projects"


class ProjectFileManager:
    """Manages project folder creation and cleanup."""

    def __init__(self, base_dir: str = BASE_PROJECTS_DIR):
        """Initialize with base projects directory."""
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def sanitize_name(self, name: str) -> str:
        """
        Sanitize project name for filesystem use.
        Replaces invalid characters with underscore.
        """
        return re.sub(r'[^\w\s-]', '_', name).strip()

    def generate_folder_name(self, project_id: int, name: str) -> str:
        """
        Generate unique folder name with timestamp.
        Format: <project_id>_<sanitized_name>_<timestamp>
        """
        sanitized = self.sanitize_name(name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{project_id}_{sanitized}_{timestamp}"

    def create_project_folder(self, project_id: int, name: str) -> str:
        """
        Create project folder on filesystem.
        
        Args:
            project_id: Project ID from database
            name: Project name
            
        Returns:
            Absolute path to created folder
            
        Raises:
            OSError: If folder creation fails
        """
        folder_name = self.generate_folder_name(project_id, name)
        folder_path = os.path.join(self.base_dir, folder_name)
        
        os.makedirs(folder_path, exist_ok=False)
        return folder_path

    def create_readme(self, project_path: str) -> bool:
        """
        Create README.md file in project folder.

        Args:
            project_path: Absolute path to project folder

        Returns:
            True if successful, False otherwise
        """
        readme_path = os.path.join(project_path, "README.md")
        readme_content = f"openclaw project folder path: {project_path}"

        try:
            with open(readme_path, 'w') as f:
                f.write(readme_content)
            return True
        except Exception as e:
            print(f"Failed to create README.md: {e}")
            return False

    def create_gitignore(self, project_path: str) -> bool:
        """
        Create .gitignore file in project folder.

        Args:
            project_path: Absolute path to project folder

        Returns:
            True if successful, False otherwise
        """
        gitignore_path = os.path.join(project_path, ".gitignore")
        gitignore_content = """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
venv/
ENV/
env/

# IDEs
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Project specific
node_modules/
.env
"""

        try:
            with open(gitignore_path, 'w') as f:
                f.write(gitignore_content)
            return True
        except Exception as e:
            print(f"Failed to create .gitignore: {e}")
            return False

    def create_changerule(self, project_path: str) -> bool:
        """
        Create changerule.md file in project folder.

        Args:
            project_path: Absolute path to project folder

        Returns:
            True if successful, False otherwise
        """
        changerule_path = os.path.join(project_path, "changerule.md")
        changerule_content = """# Project Change Rules

## Context

This is the project folder for this OpenClaw session. All file operations should be performed within this directory.

## Project Path

The absolute path to this project folder is available as system context.

## Guidelines

- All file operations should be relative to the project folder
- Keep workspace organized and clean
- Document important decisions and changes
"""

        try:
            with open(changerule_path, 'w') as f:
                f.write(changerule_content)
            return True
        except Exception as e:
            print(f"Failed to create changerule.md: {e}")
            return False

    def initialize_git_repo(self, project_path: str) -> bool:
        """
        Initialize Git repository in project folder.

        Args:
            project_path: Absolute path to project folder

        Returns:
            True if successful, False otherwise
        """
        try:
            # Initialize git repository
            subprocess.run(
                ["git", "init"],
                cwd=project_path,
                check=True,
                capture_output=True
            )

            # Configure default branch to main
            subprocess.run(
                ["git", "config", "user.name", "OpenClaw"],
                cwd=project_path,
                check=True,
                capture_output=True
            )

            subprocess.run(
                ["git", "config", "user.email", "openclaw@local"],
                cwd=project_path,
                check=True,
                capture_output=True
            )

            # Configure default branch name to main (for Git < 2.28)
            try:
                subprocess.run(
                    ["git", "checkout", "-b", "main"],
                    cwd=project_path,
                    check=True,
                    capture_output=True
                )
            except subprocess.CalledProcessError:
                # Git might already be on main or use a different branch
                pass

            return True
        except Exception as e:
            print(f"Failed to initialize Git repository: {e}")
            return False

    def create_project_with_git(self, project_id: int, name: str) -> tuple[str, bool]:
        """
        Create project folder with README.md, .gitignore, changerule.md, and Git initialization.

        Args:
            project_id: Project ID from database
            name: Project name

        Returns:
            Tuple of (project_path, success)
            - project_path: Absolute path to created folder (empty if failed)
            - success: True if all files and Git repo created
        """
        project_path = ""

        try:
            # Create folder
            project_path = self.create_project_folder(project_id, name)

            # Create README
            if not self.create_readme(project_path):
                raise Exception("Failed to create README.md")

            # Create .gitignore
            if not self.create_gitignore(project_path):
                raise Exception("Failed to create .gitignore")

            # Create changerule.md
            if not self.create_changerule(project_path):
                raise Exception("Failed to create changerule.md")

            # Initialize Git repository
            if not self.initialize_git_repo(project_path):
                raise Exception("Failed to initialize Git repository")

            return (project_path, True)

        except Exception as e:
            # Cleanup on any error
            if project_path and os.path.exists(project_path):
                self.delete_project_folder(project_path)
            print(f"Project creation failed: {e}")
            return ("", False)

    def delete_project_folder(self, project_path: str) -> bool:
        """
        Delete project folder recursively.
        
        Args:
            project_path: Absolute path to project folder
            
        Returns:
            True if successful, False otherwise
        """
        try:
            if os.path.exists(project_path):
                shutil.rmtree(project_path)
            return True
        except Exception as e:
            print(f"Failed to delete project folder: {e}")
            return False

    def create_project_with_readme(self, project_id: int, name: str) -> tuple[str, bool]:
        """
        Create project folder and README.md atomically.
        
        Args:
            project_id: Project ID from database
            name: Project name
            
        Returns:
            Tuple of (project_path, success)
            - project_path: Absolute path to created folder (empty if failed)
            - success: True if both folder and README created
        """
        project_path = ""
        
        try:
            # Create folder
            project_path = self.create_project_folder(project_id, name)
            
            # Create README
            readme_success = self.create_readme(project_path)
            
            if not readme_success:
                # Rollback folder creation
                self.delete_project_folder(project_path)
                return ("", False)
            
            return (project_path, True)
            
        except Exception as e:
            # Cleanup on any error
            if project_path and os.path.exists(project_path):
                self.delete_project_folder(project_path)
            return ("", False)
