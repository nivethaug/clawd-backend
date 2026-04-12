#!/usr/bin/env python3
"""
Git Workflow Manager
Enforces strict branching rules and manages Pull Requests programmatically.
This replaces direct gh CLI usage with a controlled, validated workflow.
"""

import subprocess
import sys
import os
import json
from datetime import datetime
from typing import Optional, Dict, List

class GitWorkflowError(Exception):
    """Custom exception for git workflow errors."""
    pass

class GitWorkflowManager:
    """Manages git branching and PR workflow with strict rules."""

    def __init__(self, repo_path: str = None):
        """Initialize the workflow manager."""
        self.repo_path = repo_path or os.getcwd()
        self.original_branch = self._get_current_branch()
        self.feature_branch = None
        self.pr_number = None

    def _run_command(self, command: List[str], capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess:
        """Run a shell command safely."""
        try:
            result = subprocess.run(
                command,
                cwd=self.repo_path,
                capture_output=capture_output,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            if check:
                raise GitWorkflowError(f"Command failed: {' '.join(command)}\nError: {e.stderr}")
            return e

    def _get_current_branch(self) -> str:
        """Get the current git branch."""
        result = self._run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
        return result.stdout.strip()

    def _is_main_branch(self, branch: str) -> bool:
        """Check if branch is main or master."""
        return branch in ['main', 'master']

    def _check_git_status(self) -> Dict[str, any]:
        """Check git status for uncommitted changes."""
        result = self._run_command(['git', 'status', '--porcelain'])
        has_changes = bool(result.stdout.strip())

        # Check if branch is ahead of origin
        ahead_result = self._run_command(['git', 'status', '-sb'])
        ahead = 'ahead' in ahead_result.stdout

        return {
            'has_uncommitted_changes': has_changes,
            'is_ahead_of_origin': ahead
        }

    def validate_repo_state(self) -> bool:
        """Validate repository is ready for workflow."""
        status = self._check_git_status()

        if status['has_uncommitted_changes']:
            raise GitWorkflowError("❌ You have uncommitted changes. Please commit or stash them first.")

        if not self._is_main_branch(self.original_branch):
            print(f"⚠️  Warning: You're on '{self.original_branch}', not 'main'")
            response = input("Continue anyway? (y/N): ")
            if response.lower() != 'y':
                return False

        return True

    def create_branch(self, branch_type: str = 'feature', branch_name: str = None) -> str:
        """
        Create a new branch from main.

        Args:
            branch_type: Type of branch (feature, fix, refactor, etc.)
            branch_name: Optional custom branch name

        Returns:
            Name of the created branch
        """
        if not branch_name:
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            branch_name = f"{branch_type}/task-{timestamp}"

        # Ensure we're on main first
        if not self._is_main_branch(self.original_branch):
            print(f"🔄 Switching to main branch...")
            self._run_command(['git', 'checkout', 'main'])
            self._run_command(['git', 'pull', 'origin', 'main'])

        # Create and checkout new branch
        print(f"🌿 Creating new branch: {branch_name}")
        self._run_command(['git', 'checkout', '-b', branch_name])

        self.feature_branch = branch_name
        print(f"✅ Branch '{branch_name}' created successfully")
        return branch_name

    def commit_changes(self, commit_message: str = None) -> str:
        """
        Commit changes with automatic message generation.

        Args:
            commit_message: Optional custom commit message

        Returns:
            Commit hash
        """
        status = self._check_git_status()

        if not status['has_uncommitted_changes']:
            print("ℹ️  No changes to commit")
            return None

        # Stage all changes
        print("📝 Staging changes...")
        self._run_command(['git', 'add', '-A'])

        # Generate commit message if not provided
        if not commit_message:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
            commit_message = f"Update - {timestamp}\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

        # Commit changes
        print("💾 Committing changes...")
        result = self._run_command(['git', 'commit', '-m', commit_message])

        # Get commit hash
        hash_result = self._run_command(['git', 'rev-parse', 'HEAD'])
        commit_hash = hash_result.stdout.strip()[:8]

        print(f"✅ Changes committed: {commit_hash}")
        return commit_hash

    def push_branch(self) -> bool:
        """Push the feature branch to remote."""
        if not self.feature_branch:
            raise GitWorkflowError("❌ No feature branch to push. Create one first.")

        print(f"📤 Pushing branch '{self.feature_branch}' to remote...")
        self._run_command(['git', 'push', '-u', 'origin', self.feature_branch])
        print("✅ Branch pushed successfully")
        return True

    def create_pull_request(self, title: str = None, body: str = None) -> int:
        """
        Create a pull request using gh CLI.

        Args:
            title: PR title
            body: PR description body

        Returns:
            Pull request number
        """
        if not self.feature_branch:
            raise GitWorkflowError("❌ No feature branch. Create one first.")

        # Generate PR title if not provided
        if not title:
            title = f"Update from {self.feature_branch}"

        # Generate PR body if not provided
        if not body:
            body = f"""## Summary
This PR includes changes from feature branch `{self.feature_branch}`.

## Changes
- Updates and improvements

## Test Plan
- [ ] Tested on local environment
- [ ] Tested on live site
- [ ] Verified no console errors
- [ ] Verified no network failures

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""

        print(f"🔨 Creating pull request...")

        # Use gh CLI to create PR
        pr_body_file = f"/tmp/pr_body_{self.feature_branch.replace('/', '_')}.txt"
        with open(pr_body_file, 'w') as f:
            f.write(body)

        try:
            result = self._run_command([
                'gh', 'pr', 'create',
                '--title', title,
                '--body-file', pr_body_file,
                '--base', 'main'
            ])

            # Extract PR number from output
            output = result.stdout
            if 'github.com' in output:
                # Parse PR URL to get number
                pr_url = output.strip()
                self.pr_number = pr_url.split('/')[-1]
                print(f"✅ Pull request created: #{self.pr_number}")
                print(f"🔗 {pr_url}")
                return int(self.pr_number)
            else:
                raise GitWorkflowError("Could not parse PR URL from gh output")

        finally:
            # Clean up temp file
            if os.path.exists(pr_body_file):
                os.remove(pr_body_file)

    def check_pr_status(self) -> Dict[str, any]:
        """Check the status of the pull request."""
        if not self.pr_number:
            raise GitWorkflowError("❌ No pull request to check.")

        result = self._run_command([
            'gh', 'pr', 'view', str(self.pr_number),
            '--json', 'title,state,mergeable,reviewDecision'
        ])

        pr_data = json.loads(result.stdout)
        return pr_data

    def merge_pull_request(self, merge_method: str = 'merge') -> bool:
        """
        Merge the pull request.

        Args:
            merge_method: How to merge (merge, squash, rebase)
        """
        if not self.pr_number:
            raise GitWorkflowError("❌ No pull request to merge.")

        print(f"🔀 Merging pull request #{self.pr_number}...")

        # Check PR status first
        status = self.check_pr_status()
        print(f"   PR Status: {status['state']}")
        print(f"   Mergeable: {status.get('mergeable', 'unknown')}")

        # Merge the PR
        self._run_command([
            'gh', 'pr', 'merge', str(self.pr_number),
            '--merge',  # Always use merge commit
            '--delete-branch'  # Delete branch after merge
        ])

        print("✅ Pull request merged successfully")
        return True

    def cleanup_branch(self) -> bool:
        """Clean up: switch back to main and pull latest changes."""
        print("🧹 Cleaning up...")

        # Switch back to main
        print("   Switching to main...")
        self._run_command(['git', 'checkout', 'main'])

        # Pull latest changes
        print("   Pulling latest changes...")
        self._run_command(['git', 'pull', 'origin', 'main'])

        # Delete local feature branch if it still exists
        if self.feature_branch:
            try:
                self._run_command([
                    'git', 'branch', '-D', self.feature_branch
                ], check=False)
                print(f"   Deleted local branch '{self.feature_branch}'")
            except:
                pass  # Branch might not exist locally

        print("✅ Cleanup complete")
        return True

    def complete_workflow(self, title: str = None, body: str = None, commit_message: str = None) -> Dict[str, any]:
        """
        Execute the complete workflow: commit → push → create PR → merge → cleanup.

        Args:
            title: PR title
            body: PR body
            commit_message: Commit message

        Returns:
            Dictionary with workflow results
        """
        result = {
            'success': False,
            'commit': None,
            'pr_number': None,
            'error': None
        }

        try:
            # Step 1: Commit changes
            commit = self.commit_changes(commit_message)
            result['commit'] = commit

            # Step 2: Push branch
            self.push_branch()

            # Step 3: Create PR
            pr_number = self.create_pull_request(title, body)
            result['pr_number'] = pr_number

            # Step 4: Ask for approval
            print("\n" + "="*60)
            print("⏸️  WAITING FOR YOUR APPROVAL")
            print("="*60)
            print(f"📋 Pull Request #{pr_number} is ready for review")
            print(f"🔗 View PR: gh pr view {pr_number}")
            print("\nAre you satisfied with the current changes?")
            response = input("Confirm approval to merge (y/N): ")

            if response.lower() != 'y':
                print("❌ Merge cancelled. PR remains open for manual review.")
                return result

            # Step 5: Merge PR
            self.merge_pull_request()

            # Step 6: Cleanup
            self.cleanup_branch()

            result['success'] = True
            print("\n✅ Workflow completed successfully!")

        except Exception as e:
            result['error'] = str(e)
            print(f"\n❌ Workflow failed: {e}")

        return result


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
