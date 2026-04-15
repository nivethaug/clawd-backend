"""
Shared plan mode logic — base template, approval flow, ai_index checklist.
"""

from typing import Optional


PLAN_TEMPLATE = """# Plan: {title}

## Description
{description}

## Steps
{steps}

## ai_index Update Checklist
{ai_index_checklist}

## Open Questions
{open_questions}

## Complexity
- **Level**: {complexity_level}
- **Estimated files changed**: {file_count}
"""

CLARIFICATION_RULE = """**CLARIFICATION RULE:** If the user's request has multiple interpretations, ask up to 2 rounds of clarification questions. After that, proceed with your best understanding."""

FIRST_TIME_INSTRUCTIONS = """## PLAN MODE — FIRST TIME (No plan file exists yet)

You are in **Plan Mode**. Your job is to analyze the user's request and create a detailed plan BEFORE making any code changes.

**RULES:**
1. **DO NOT make any code changes** — only analyze and plan
2. Read the relevant source files to understand the current state
3. Present a structured plan with:
   - **Description** — What will be done and why
   - **Steps** — Ordered list of changes with target files
   - **ai_index Update Checklist** — Which ai_index files need updating and what symbols to add/modify
   - **Open Questions** — Anything ambiguous that needs user input
   - **Complexity** — Low / Medium / High assessment
4. Ask the user for approval with: **"Do you approve this plan? Reply 'yes' to approve, or suggest modifications."**
5. **DO NOT create the plan file yet** — just present it in chat
6. If the user replies with feedback (not "yes" / "approve"), refine the plan and ask again
7. Only after explicit approval ("yes" / "approve" / "go ahead") should you create the plan file

**When the user approves:**
1. Create the `plans/` directory if it doesn't exist: `{project_path}/plans/`
2. Save the plan as: `{project_path}/plans/plan_YYYYMMDD_HHMMSS.md`
   - Use Python datetime: `from datetime import datetime`
   - Filename format: `plan_{{datetime.now().strftime('%Y%m%d_%H%M%S')}}.md`
3. Tell the user: "The plan has been saved. Next Steps: Please switch to **Dream Mode** to execute this plan."
"""

CONTINUE_INSTRUCTIONS = """## PLAN MODE — CONTINUE (Existing plan found)

You are in **Plan Mode** with an existing approved plan. Here is the current plan:

---BEGIN EXISTING PLAN---
{existing_plan}
---END EXISTING PLAN---

**RULES:**
1. **DO NOT make any code changes** — only discuss the plan
2. Review the existing plan and the user's new message
3. If the user wants modifications, update the plan accordingly and re-save to the same file
4. If the user approves, confirm and tell them to switch to **Dream Mode** to execute
5. If no existing plan is approved yet, continue refining and asking for approval

**If you need to save a new plan file:**
- Path: `{project_path}/plans/plan_YYYYMMDD_HHMMSS.md`
- Use Python: `from datetime import datetime` → `plan_{{datetime.now().strftime('%Y%m%d_%H%M%S')}}.md`

{clarification_rule}
"""


def build_base_plan_prompt(
    user_message: str,
    session_context: str,
    project_name: str,
    project_path: str,
    existing_plan: Optional[str] = None,
    project_specific_context: str = "",
) -> str:
    """
    Build the base plan mode prompt shared across all project types.
    """
    context_section = ""
    if session_context:
        context_section = f"""## CONVERSATION HISTORY

{session_context}

---
"""

    if existing_plan:
        mode_instructions = CONTINUE_INSTRUCTIONS.format(
            existing_plan=existing_plan,
            clarification_rule=CLARIFICATION_RULE,
            project_path=project_path,
        )
    else:
        mode_instructions = FIRST_TIME_INSTRUCTIONS.format(project_path=project_path)

    return f"""You are a friendly AI assistant helping a user plan changes for their **{project_name}** project.

---

{mode_instructions}

{project_specific_context}

---

{context_section}

## USER'S REQUEST

{user_message}
"""
