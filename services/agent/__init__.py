"""Automation agent service (project type slug: 'agent').

Evolution of the scheduler family: same central jobs/worker/execution
infrastructure (services/scheduler), plus the capability layer —
proxy actions on connected OAuth accounts, declarative conditions, and
cross-run state. Type-5 scheduler projects are untouched.
"""

from services.agent.worker import run_agent_pipeline  # noqa: F401
