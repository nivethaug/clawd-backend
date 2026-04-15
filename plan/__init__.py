"""
Plan mode prompt dispatcher — routes to the correct project-type plan builder.
"""

from typing import Optional


def build_plan_prompt(
    project_type: str,
    user_message: str,
    session_context: str,
    project_path: str,
    project_name: str,
    existing_plan: Optional[str] = None,
) -> str:
    """Dispatch to the right project-type plan prompt builder."""

    if project_type == 'telegram':
        from plan.plan_telegram import build_telegram_plan_prompt
        return build_telegram_plan_prompt(
            user_message=user_message,
            session_context=session_context,
            project_path=project_path,
            project_name=project_name,
            existing_plan=existing_plan,
        )
    elif project_type == 'discord':
        from plan.plan_discord import build_discord_plan_prompt
        return build_discord_plan_prompt(
            user_message=user_message,
            session_context=session_context,
            project_path=project_path,
            project_name=project_name,
            existing_plan=existing_plan,
        )
    elif project_type == 'scheduler':
        from plan.plan_scheduler import build_scheduler_plan_prompt
        return build_scheduler_plan_prompt(
            user_message=user_message,
            session_context=session_context,
            project_path=project_path,
            project_name=project_name,
            existing_plan=existing_plan,
        )
    else:
        from plan.plan_website import build_website_plan_prompt
        return build_website_plan_prompt(
            user_message=user_message,
            session_context=session_context,
            project_path=project_path,
            project_name=project_name,
            existing_plan=existing_plan,
        )
