#!/usr/bin/env python3
"""
Git Workflow Manager — API Client
Calls the backend API to commit, push, and manage git operations.
All git operations happen server-side; this is a thin HTTP client.
"""

import os
import sys
import json
from typing import Optional, Dict, List

try:
    import urllib.request
    import urllib.error
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


class GitWorkflowError(Exception):
    """Custom exception for git workflow errors."""
    pass


class GitWorkflowManager:
    """Thin API client for git commit/push/rollback operations."""

    def __init__(self, repo_path: str, project_id: int = None, session_id: int = None):
        """
        Initialize the workflow manager.

        Args:
            repo_path: Path to the git repository (kept for backward compat, not used for git ops)
            project_id: Project ID for API calls
            session_id: Session ID for API calls (used to find the assistant message to tag)
        """
        self.repo_path = repo_path or os.getcwd()
        self.project_id = project_id
        self.session_id = session_id
        self.backend_url = os.environ.get('BACKEND_URL', f"http://localhost:{os.getenv('PORT', '8002')}")
        self._last_commit = None

    def _api_call(self, method: str, path: str, data: dict = None) -> dict:
        """Make an HTTP API call to the backend."""
        url = f"{self.backend_url}{path}"
        headers = {"Content-Type": "application/json"}
        body = json.dumps(data).encode() if data else None

        if _HAS_REQUESTS:
            if method == "GET":
                resp = requests.get(url, params=data)
            elif method == "POST":
                resp = requests.post(url, json=data)
            else:
                raise GitWorkflowError(f"Unsupported method: {method}")
            return resp.json()

        elif _HAS_URLLIB:
            if method == "GET":
                if data:
                    query = "&".join(f"{k}={v}" for k, v in data.items())
                    url = f"{url}?{query}"
                req = urllib.request.Request(url)
            elif method == "POST":
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            else:
                raise GitWorkflowError(f"Unsupported method: {method}")

            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                error_body = e.read().decode() if e.fp else str(e)
                raise GitWorkflowError(f"API error {e.code}: {error_body}")
            except urllib.error.URLError as e:
                raise GitWorkflowError(f"Cannot connect to backend at {url}: {e}")

        else:
            raise GitWorkflowError("No HTTP library available. Install requests or use Python 3+.")

    def commit_and_push(self, message: str) -> dict:
        """
        Commit and push changes via backend API.
        Backend finds the latest assistant message in this session and
        updates it with commit_hash for UI rollback.

        Args:
            message: Commit message (used as git commit -m)

        Returns:
            { 'success': bool, 'commit_hash': str, 'message_id': int, 'status': str }
        """
        if not self.project_id:
            raise GitWorkflowError("project_id is required. Pass it to GitWorkflowManager().")
        if not self.session_id:
            raise GitWorkflowError("session_id is required. Pass it to GitWorkflowManager().")

        result = self._api_call("POST", f"/projects/{self.project_id}/commits", {
            "session_id": self.session_id,
            "message": message,
            "auto_push": True
        })

        self._last_commit = result
        return result

    def rollback(self, message_id: int = None) -> dict:
        """
        Rollback a specific commit by message_id.

        Args:
            message_id: The message_id to rollback. Defaults to last commit.

        Returns:
            { 'success': bool, 'commit_hash': str, 'message_id': int, 'reverted_message_id': int }
        """
        if not self.project_id:
            raise GitWorkflowError("project_id is required.")

        target_id = message_id
        if target_id is None:
            if not self._last_commit or 'message_id' not in self._last_commit:
                raise GitWorkflowError("No previous commit to rollback. Pass message_id explicitly.")
            target_id = self._last_commit['message_id']

        result = self._api_call("POST", f"/projects/{self.project_id}/commits/{target_id}/rollback")
        return result

    def get_history(self, limit: int = 20) -> list:
        """
        Get commit history for this project.

        Args:
            limit: Max number of commits to return

        Returns:
            List of commit records
        """
        if not self.project_id:
            raise GitWorkflowError("project_id is required.")

        result = self._api_call("GET", f"/projects/{self.project_id}/commits", {"limit": limit})
        return result.get("commits", [])

    # --- Backward compat (deprecated) ---

    def complete_workflow(self, message: str = None) -> dict:
        """
        DEPRECATED: Use commit_and_push() instead.
        Kept for backward compatibility with existing prompts.
        """
        return self.commit_and_push(message or "Changes applied")

    def create_branch(self, *args, **kwargs):
        """DEPRECATED: Branching is no longer supported."""
        raise GitWorkflowError("Branching is no longer supported. Use commit_and_push() to commit directly to main.")

    def push_branch(self, *args, **kwargs):
        """DEPRECATED: Use commit_and_push() instead."""
        raise GitWorkflowError("Branching is no longer supported. Use commit_and_push() to commit directly to main.")

    def create_pull_request(self, *args, **kwargs):
        """DEPRECATED: PRs are no longer supported."""
        raise GitWorkflowError("Pull requests are no longer supported. Use commit_and_push() to commit directly to main.")

    def merge_pull_request(self, *args, **kwargs):
        """DEPRECATED: PRs are no longer supported."""
        raise GitWorkflowError("Pull requests are no longer supported. Use commit_and_push() to commit directly to main.")

    def cleanup_branch(self, *args, **kwargs):
        """DEPRECATED: Branching is no longer supported."""
        raise GitWorkflowError("Branching is no longer supported. No cleanup needed.")


def main():
    """CLI interface for the git workflow manager."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Git Workflow Manager - Enforce branching rules and manage PRs'
    )
    parser.add_argument(
        'action',
        choices=['start', 'commit', 'push', 'pr', 'merge', 'complete', 'status'],
        help='Action to perform'
    )
    parser.add_argument('--branch-type', default='feature',
                       help='Type of branch (feature, fix, refactor)')
    parser.add_argument('--branch-name', help='Custom branch name')
    parser.add_argument('--title', help='PR title')
    parser.add_argument('--body', help='PR body')
    parser.add_argument('--commit-message', help='Commit message')

    args = parser.parse_args()

    try:
        manager = GitWorkflowManager()

        if args.action == 'start':
            manager.validate_repo_state()
            branch = manager.create_branch(args.branch_type, args.branch_name)
            print(f"✅ Ready to work on branch: {branch}")

        elif args.action == 'commit':
            manager.commit_changes(args.commit_message)

        elif args.action == 'push':
            manager.push_branch()

        elif args.action == 'pr':
            manager.create_pull_request(args.title, args.body)

        elif args.action == 'merge':
            manager.merge_pull_request()

        elif args.action == 'complete':
            manager.complete_workflow(args.title, args.body, args.commit_message)

        elif args.action == 'status':
            if manager.pr_number:
                status = manager.check_pr_status()
                print(json.dumps(status, indent=2))
            else:
                print("No active pull request")

    except GitWorkflowError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Workflow cancelled by user")
        sys.exit(1)


if __name__ == '__main__':
    main()
