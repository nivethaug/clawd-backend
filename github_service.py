#!/usr/bin/env python3
"""
GitHub Service - GitHub repository operations using gh CLI.

This module provides GitHub integration for project creation and management.
Uses the 'gh' CLI which is already authenticated on the server.

Usage:
    from github_service import GitHubService
    
    gh = GitHubService()
    repo_url = gh.create_repository("my-project")
    gh.push_to_github("/path/to/project", "main")
    gh.delete_repository("owner/my-project")
"""

import subprocess
import logging
import re
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class GitHubService:
    """GitHub operations using gh CLI."""
    
    def __init__(self):
        """Initialize GitHub service."""
        self._check_gh_cli()
    
    def _check_gh_cli(self) -> bool:
        """Check if gh CLI is available and authenticated."""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                logger.info("[GITHUB] gh CLI authenticated")
                return True
            else:
                logger.warning(f"[GITHUB] gh CLI not authenticated: {result.stderr}")
                return False
        except FileNotFoundError:
            logger.error("[GITHUB] gh CLI not found")
            return False
        except Exception as e:
            logger.error(f"[GITHUB] Error checking gh CLI: {e}")
            return False
    
    def _run_gh_command(self, args: list, cwd: str = None, timeout: int = 60) -> Tuple[bool, str]:
        """
        Run gh CLI command.
        
        Args:
            args: Command arguments (without 'gh')
            cwd: Working directory
            timeout: Command timeout in seconds
            
        Returns:
            Tuple of (success, output)
        """
        cmd = ["gh"] + args
        logger.info(f"[GITHUB] Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=timeout
            )
            
            output = result.stdout.strip()
            error = result.stderr.strip()
            
            if result.returncode == 0:
                logger.info(f"[GITHUB] Success: {output[:200]}")
                return True, output
            else:
                logger.error(f"[GITHUB] Failed: {error}")
                return False, error
                
        except subprocess.TimeoutExpired:
            logger.error(f"[GITHUB] Command timed out after {timeout}s")
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            logger.error(f"[GITHUB] Exception: {e}")
            return False, str(e)
    
    def sanitize_repo_name(self, name: str) -> str:
        """
        Convert project name to valid GitHub repo name.
        
        Rules:
        - Lowercase only
        - Alphanumeric and hyphens
        - No consecutive hyphens
        - Max 100 characters
        
        Args:
            name: Original project name
            
        Returns:
            Sanitized repo name
        """
        # Convert to lowercase
        name = name.lower()
        
        # Replace spaces and underscores with hyphens
        name = name.replace(" ", "-").replace("_", "-")
        
        # Remove invalid characters (keep alphanumeric and hyphens)
        name = re.sub(r"[^a-z0-9-]", "", name)
        
        # Remove consecutive hyphens
        name = re.sub(r"-+", "-", name)
        
        # Remove leading/trailing hyphens
        name = name.strip("-")
        
        # Limit length
        name = name[:100]
        
        # Ensure not empty
        if not name:
            name = "unnamed-project"
        
        return name
    
    def create_repository(self, name: str, public: bool = True, description: str = "") -> Optional[str]:
        """
        Create a new GitHub repository.
        
        Args:
            name: Repository name (will be sanitized)
            public: True for public repo, False for private
            description: Repository description
            
        Returns:
            Repository URL if successful, None otherwise
        """
        repo_name = self.sanitize_repo_name(name)
        visibility = "--public" if public else "--private"
        
        args = [
            "repo", "create",
            repo_name,
            visibility,
            "--description", description or f"Project: {name}"
        ]
        
        success, output = self._run_gh_command(args, timeout=30)
        
        if success:
            # Output is the repo URL
            return output
        else:
            # Check if repo already exists
            if "already exists" in output.lower():
                logger.warning(f"[GITHUB] Repo {repo_name} already exists, returning existing URL")
                return f"https://github.com/{self._get_username()}/{repo_name}"
            return None
    
    def add_remote(self, project_path: str, repo_url: str, remote_name: str = "origin") -> bool:
        """
        Add remote to local git repository.
        
        Args:
            project_path: Path to local git repository
            repo_url: GitHub repository URL
            remote_name: Remote name (default: origin)
            
        Returns:
            True if successful
        """
        try:
            # Check if remote already exists
            result = subprocess.run(
                ["git", "remote", "get-url", remote_name],
                capture_output=True,
                text=True,
                cwd=project_path
            )
            
            if result.returncode == 0:
                # Remote exists, update it
                logger.info(f"[GITHUB] Updating existing remote {remote_name}")
                result = subprocess.run(
                    ["git", "remote", "set-url", remote_name, repo_url],
                    capture_output=True,
                    text=True,
                    cwd=project_path
                )
            else:
                # Add new remote
                logger.info(f"[GITHUB] Adding remote {remote_name}: {repo_url}")
                result = subprocess.run(
                    ["git", "remote", "add", remote_name, repo_url],
                    capture_output=True,
                    text=True,
                    cwd=project_path
                )
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"[GITHUB] Error adding remote: {e}")
            return False
    
    def push_to_github(self, project_path: str, branch: str = "main", remote_name: str = "origin") -> bool:
        """
        Push local repository to GitHub.
        
        Args:
            project_path: Path to local git repository
            branch: Branch name to push (default: main, auto-detected if not found)
            remote_name: Remote name (default: origin)
            
        Returns:
            True if successful
        """
        try:
            # Step 0: Configure git to use gh CLI for authentication
            logger.info(f"[GITHUB] Configuring git to use gh CLI for authentication")
            subprocess.run(
                ["gh", "auth", "setup-git"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Step 1: Check if there are any commits
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=10
            )
            
            has_commits = result.returncode == 0
            
            if not has_commits:
                # No commits yet - make initial commit
                logger.info(f"[GITHUB] No commits found, creating initial commit")
                
                # Add all files
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=project_path,
                    capture_output=True,
                    timeout=30
                )
                
                # Create initial commit
                result = subprocess.run(
                    ["git", "commit", "-m", "Initial commit"],
                    capture_output=True,
                    text=True,
                    cwd=project_path,
                    timeout=30
                )
                
                if result.returncode != 0:
                    logger.warning(f"[GITHUB] Initial commit failed (might be empty): {result.stderr}")
                else:
                    logger.info(f"[GITHUB] Created initial commit")
            
            # Step 2: Detect actual branch name
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=10
            )
            
            actual_branch = result.stdout.strip() if result.returncode == 0 else ""
            
            # If no branch (detached HEAD or no commits), try to get default or use 'main'
            if not actual_branch:
                # Check for existing branches
                result = subprocess.run(
                    ["git", "branch"],
                    capture_output=True,
                    text=True,
                    cwd=project_path,
                    timeout=10
                )
                
                if result.returncode == 0:
                    branches = result.stdout.strip()
                    # Parse branch names (remove * prefix)
                    for line in branches.split('\n'):
                        line = line.strip().lstrip('* ')
                        if line:
                            actual_branch = line
                            break
                
                # Still no branch? Rename to main
                if not actual_branch:
                    actual_branch = "main"
                    subprocess.run(
                        ["git", "checkout", "-b", actual_branch],
                        cwd=project_path,
                        capture_output=True,
                        timeout=10
                    )
            
            logger.info(f"[GITHUB] Using branch: {actual_branch}")
            
            # Step 3: Push with upstream tracking
            logger.info(f"[GITHUB] Pushing {actual_branch} to {remote_name}")
            result = subprocess.run(
                ["git", "push", "-u", remote_name, actual_branch],
                capture_output=True,
                text=True,
                cwd=project_path,
                timeout=120  # 2 minutes for push
            )
            
            if result.returncode == 0:
                logger.info(f"[GITHUB] Successfully pushed to {remote_name}/{actual_branch}")
                return True
            else:
                logger.error(f"[GITHUB] Push failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("[GITHUB] Push timed out")
            return False
        except Exception as e:
            logger.error(f"[GITHUB] Error pushing: {e}")
            return False
    
    def delete_repository(self, repo_name: str) -> bool:
        """
        Delete a GitHub repository.
        
        Args:
            repo_name: Full repo name (owner/repo) or just repo name
            
        Returns:
            True if successful
        """
        # If just repo name, prepend username
        if "/" not in repo_name:
            username = self._get_username()
            if not username:
                logger.error("[GITHUB] Cannot determine username for deletion")
                return False
            repo_name = f"{username}/{repo_name}"
        
        logger.info(f"[GITHUB] Deleting repository: {repo_name}")
        
        # Use --yes to skip confirmation
        args = ["repo", "delete", repo_name, "--yes"]
        
        success, output = self._run_gh_command(args, timeout=30)
        
        if success:
            logger.info(f"[GITHUB] ✓ Successfully deleted {repo_name}")
            return True
        else:
            # Check if repo doesn't exist (already deleted)
            if "not found" in output.lower() or "does not exist" in output.lower():
                logger.info(f"[GITHUB] Repository {repo_name} not found (already deleted?)")
                return True  # Consider success if already gone
            logger.error(f"[GITHUB] ✗ Failed to delete {repo_name}: {output}")
            return False
    
    def _get_username(self) -> Optional[str]:
        """Get authenticated GitHub username."""
        try:
            result = subprocess.run(
                ["gh", "api", "user", "-q", ".login"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"[GITHUB] Error getting username: {e}")
        return None
    
    def get_repo_url(self, repo_name: str) -> Optional[str]:
        """
        Get full repository URL.
        
        Args:
            repo_name: Repository name (with or without owner)
            
        Returns:
            Full GitHub URL
        """
        if "/" in repo_name:
            return f"https://github.com/{repo_name}"
        
        username = self._get_username()
        if username:
            return f"https://github.com/{username}/{repo_name}"
        return None
    
    def repository_exists(self, repo_name: str) -> bool:
        """
        Check if a repository exists.
        
        Args:
            repo_name: Repository name (with or without owner)
            
        Returns:
            True if repository exists
        """
        if "/" not in repo_name:
            username = self._get_username()
            if username:
                repo_name = f"{username}/{repo_name}"
            else:
                return False
        
        args = ["repo", "view", repo_name]
        success, _ = self._run_gh_command(args, timeout=10)
        return success


# Singleton instance
_github_service = None


def get_github_service() -> GitHubService:
    """Get singleton GitHub service instance."""
    global _github_service
    if _github_service is None:
        _github_service = GitHubService()
    return _github_service
