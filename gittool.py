#!/usr/bin/env python3
"""
Git Tool - Common git operations for AI agent.

This module provides git utilities similar to buildpublish.py pattern.
Used by AI agent when modifying source code to maintain version control.

Usage:
    from gittool import GitTool
    
    git = GitTool("/path/to/project")
    
    # Create feature branch
    git.create_branch("feature/new-login")
    
    # After making changes
    git.add(".")
    git.commit("Add new login page")
    git.push("feature/new-login")
    
    # Or use convenience method
    git.save_changes("Add new login page", "feature/new-login")
"""

import subprocess
import logging
import os
from typing import Optional, List, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


class GitTool:
    """Git operations utility class."""
    
    def __init__(self, project_path: str):
        """
        Initialize GitTool.
        
        Args:
            project_path: Path to git repository
        """
        self.project_path = Path(project_path).resolve()
        self._verify_git_repo()
    
    def _verify_git_repo(self) -> bool:
        """Verify path is a git repository."""
        git_dir = self.project_path / ".git"
        if not git_dir.exists():
            logger.warning(f"[GIT] Not a git repository: {self.project_path}")
            return False
        logger.debug(f"[GIT] Git repository verified: {self.project_path}")
        return True
    
    def _run_git_command(self, args: list, timeout: int = 60) -> Tuple[bool, str]:
        """
        Run git command.
        
        Args:
            args: Command arguments (without 'git')
            timeout: Command timeout in seconds
            
        Returns:
            Tuple of (success, output)
        """
        cmd = ["git"] + args
        logger.info(f"[GIT] Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_path),
                timeout=timeout
            )
            
            output = result.stdout.strip()
            error = result.stderr.strip()
            
            if result.returncode == 0:
                logger.info(f"[GIT] Success: {output[:200] if output else 'OK'}")
                return True, output
            else:
                logger.error(f"[GIT] Failed: {error}")
                return False, error
                
        except subprocess.TimeoutExpired:
            logger.error(f"[GIT] Command timed out after {timeout}s")
            return False, f"Command timed out after {timeout}s"
        except Exception as e:
            logger.error(f"[GIT] Exception: {e}")
            return False, str(e)
    
    # ==================== BRANCH OPERATIONS ====================
    
    def create_branch(self, branch_name: str, switch: bool = True) -> bool:
        """
        Create a new branch.
        
        Args:
            branch_name: Name of the new branch
            switch: Whether to switch to the new branch (default: True)
            
        Returns:
            True if successful
        """
        if switch:
            # Create and switch in one command
            success, output = self._run_git_command(
                ["checkout", "-b", branch_name]
            )
        else:
            # Just create the branch
            success, output = self._run_git_command(
                ["branch", branch_name]
            )
        
        return success
    
    def switch_branch(self, branch_name: str) -> bool:
        """
        Switch to an existing branch.
        
        Args:
            branch_name: Name of the branch to switch to
            
        Returns:
            True if successful
        """
        success, _ = self._run_git_command(["checkout", branch_name])
        return success
    
    def get_current_branch(self) -> Optional[str]:
        """
        Get current branch name.
        
        Returns:
            Current branch name or None if error
        """
        success, output = self._run_git_command(
            ["branch", "--show-current"]
        )
        return output if success else None
    
    def list_branches(self, include_remote: bool = False) -> List[str]:
        """
        List all branches.
        
        Args:
            include_remote: Include remote branches
            
        Returns:
            List of branch names
        """
        if include_remote:
            success, output = self._run_git_command(
                ["branch", "-a"]
            )
        else:
            success, output = self._run_git_command(
                ["branch"]
            )
        
        if success and output:
            # Parse branch names (remove * and whitespace)
            branches = []
            for line in output.split("\n"):
                branch = line.strip().lstrip("* ").strip()
                if branch:
                    branches.append(branch)
            return branches
        return []
    
    def delete_branch(self, branch_name: str, force: bool = False) -> bool:
        """
        Delete a branch.
        
        Args:
            branch_name: Name of the branch to delete
            force: Force delete (for unmerged branches)
            
        Returns:
            True if successful
        """
        flag = "-D" if force else "-d"
        success, _ = self._run_git_command(["branch", flag, branch_name])
        return success
    
    # ==================== SYNC OPERATIONS ====================
    
    def pull(self, remote: str = "origin", branch: str = None) -> bool:
        """
        Pull changes from remote.
        
        Args:
            remote: Remote name (default: origin)
            branch: Branch name (default: current branch)
            
        Returns:
            True if successful
        """
        if branch:
            success, _ = self._run_git_command(
                ["pull", remote, branch],
                timeout=120
            )
        else:
            success, _ = self._run_git_command(
                ["pull", remote],
                timeout=120
            )
        return success
    
    def push(self, branch: str = None, remote: str = "origin", set_upstream: bool = True) -> bool:
        """
        Push changes to remote.
        
        Args:
            branch: Branch name (default: current branch)
            remote: Remote name (default: origin)
            set_upstream: Set upstream tracking (default: True)
            
        Returns:
            True if successful
        """
        args = ["push"]
        
        if set_upstream:
            args.append("-u")
        
        args.append(remote)
        
        if branch:
            args.append(branch)
        
        success, _ = self._run_git_command(args, timeout=120)
        return success
    
    def fetch(self, remote: str = "origin") -> bool:
        """
        Fetch changes from remote.
        
        Args:
            remote: Remote name (default: origin)
            
        Returns:
            True if successful
        """
        success, _ = self._run_git_command(
            ["fetch", remote],
            timeout=120
        )
        return success
    
    # ==================== STAGING & COMMIT ====================
    
    def add(self, files: str = ".", all_files: bool = False) -> bool:
        """
        Stage files for commit.
        
        Args:
            files: Files to add (default: "." for all)
            all_files: Add all files (including deleted)
            
        Returns:
            True if successful
        """
        if all_files:
            success, _ = self._run_git_command(["add", "-A"])
        else:
            success, _ = self._run_git_command(["add", files])
        return success
    
    def commit(self, message: str) -> bool:
        """
        Commit staged changes.
        
        Args:
            message: Commit message
            
        Returns:
            True if successful
        """
        success, _ = self._run_git_command(
            ["commit", "-m", message]
        )
        return success
    
    def add_and_commit(self, message: str, files: str = ".") -> bool:
        """
        Stage and commit in one operation.
        
        Args:
            message: Commit message
            files: Files to add (default: "." for all)
            
        Returns:
            True if successful
        """
        if not self.add(files):
            return False
        return self.commit(message)
    
    # ==================== STATUS & INFO ====================
    
    def status(self) -> Tuple[bool, str]:
        """
        Get git status.
        
        Returns:
            Tuple of (success, status_output)
        """
        return self._run_git_command(["status"])
    
    def has_changes(self) -> bool:
        """
        Check if there are uncommitted changes.
        
        Returns:
            True if there are changes
        """
        success, output = self._run_git_command(
            ["status", "--porcelain"]
        )
        return success and bool(output.strip())
    
    def get_last_commit(self) -> Optional[str]:
        """
        Get last commit hash.
        
        Returns:
            Commit hash or None
        """
        success, output = self._run_git_command(
            ["rev-parse", "HEAD"]
        )
        return output if success else None
    
    def get_log(self, count: int = 10, oneline: bool = True) -> str:
        """
        Get commit log.
        
        Args:
            count: Number of commits to show
            oneline: Use oneline format
            
        Returns:
            Log output
        """
        args = ["log", f"-{count}"]
        if oneline:
            args.append("--oneline")
        
        success, output = self._run_git_command(args)
        return output if success else ""
    
    # ==================== REMOTE OPERATIONS ====================
    
    def add_remote(self, name: str, url: str) -> bool:
        """
        Add a remote.
        
        Args:
            name: Remote name
            url: Remote URL
            
        Returns:
            True if successful
        """
        success, _ = self._run_git_command(
            ["remote", "add", name, url]
        )
        return success
    
    def get_remote_url(self, name: str = "origin") -> Optional[str]:
        """
        Get remote URL.
        
        Args:
            name: Remote name
            
        Returns:
            Remote URL or None
        """
        success, output = self._run_git_command(
            ["remote", "get-url", name]
        )
        return output if success else None
    
    def list_remotes(self) -> List[str]:
        """
        List all remotes.
        
        Returns:
            List of remote names
        """
        success, output = self._run_git_command(["remote"])
        if success and output:
            return output.split("\n")
        return []
    
    # ==================== CONVENIENCE METHODS ====================
    
    def save_changes(self, message: str, branch: str = None, push: bool = True) -> bool:
        """
        Convenience method: add, commit, and optionally push.
        
        Args:
            message: Commit message
            branch: Branch to push (default: current)
            push: Whether to push after commit
            
        Returns:
            True if all operations successful
        """
        # Check for changes
        if not self.has_changes():
            logger.info("[GIT] No changes to save")
            return True
        
        # Create branch if specified and different from current
        if branch:
            current = self.get_current_branch()
            if current and current != branch:
                if not self.create_branch(branch):
                    return False
        
        # Add and commit
        if not self.add_and_commit(message):
            return False
        
        # Push if requested
        if push:
            return self.push(branch)
        
        return True
    
    def quick_save(self, message: str) -> bool:
        """
        Quick save: add all, commit, push to current branch.
        
        Args:
            message: Commit message
            
        Returns:
            True if successful
        """
        return self.save_changes(message, push=True)


# ==================== UTILITY FUNCTIONS ====================

def is_git_repo(path: str) -> bool:
    """Check if path is a git repository."""
    git_dir = Path(path) / ".git"
    return git_dir.exists()


def init_git_repo(path: str, initial_branch: str = "main") -> bool:
    """
    Initialize a new git repository.
    
    Args:
        path: Path for new repository
        initial_branch: Initial branch name
        
    Returns:
        True if successful
    """
    try:
        result = subprocess.run(
            ["git", "init", "-b", initial_branch],
            capture_output=True,
            text=True,
            cwd=path
        )
        return result.returncode == 0
    except Exception as e:
        logger.error(f"[GIT] Error initializing repo: {e}")
        return False
