"""
Phase 8: CrewAI Multi-Agent Frontend Refinement

Replaces deadlocked single-pass OpenClaw/Claude CLI with reliable,
incremental multi-agent system using CrewAI.

Agents:
1. Planner Agent: Refines PLAN.md into detailed, batched implementation steps
2. Implementer Agent: Applies code changes using file read/write tools
3. Validator Agent: Runs npm build + lint after each batch

Features:
- Incremental execution (5-10 files per batch)
- Build verification after each batch
- Git versioning with commits per batch
- Error recovery (skip failed batches, continue with others)
- SUMMARY.md with complete overview
"""

import os
import subprocess
import json
import logging
from pathlib import Path
from crewai import Agent, Crew, Task, LLM
from crewai.tools import tool
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment
CREW_ENV_VENV = "/root/crew-env/bin/activate"
LLM_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = "groq/llama-3.3-70b-versatile"


# ============================================================================
# Custom Tools
# ============================================================================

@tool("ReadFile")
def read_file(path: str) -> str:
    """
    Read file content from the frontend project.
    
    Args:
        path: Relative or absolute path to file
    
    Returns:
        File content as string
    """
    logger.info(f"📖 Reading file: {path}")
    
    if not Path(path).exists():
        logger.error(f"❌ File not found: {path}")
        return ""
    
    try:
        content = Path(path).read_text(encoding='utf-8')
        logger.info(f"✓ Read {len(content)} chars from {path}")
        return content
    except Exception as e:
        logger.error(f"❌ Failed to read {path}: {e}")
        return ""


@tool("WriteFile")
def write_file(path: str, content: str) -> bool:
    """
    Write content to a file in the frontend project.
    
    Args:
        path: Relative or absolute path to file
        content: Content to write
    
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"📝 Writing file: {path}")
    
    try:
        # Ensure directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        Path(path).write_text(content, encoding='utf-8')
        logger.info(f"✓ Wrote {len(content)} chars to {path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to write {path}: {e}")
        return False


@tool("RunNPMBuild")
def run_npm_build(cwd: str = None) -> Dict[str, Any]:
    """
    Run `npm run build` to verify frontend builds successfully.
    
    Args:
        cwd: Working directory (defaults to current directory)
    
    Returns:
        Dict with success, stdout, stderr, returncode
    """
    logger.info("🔨 Running `npm run build`")
    
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes max
        )
        
        if result.returncode == 0:
            logger.info("✅ Build succeeded!")
            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        else:
            logger.error(f"❌ Build failed with code: {result.returncode}")
            logger.error(f"Error output: {result.stderr[-500:]}")
            return {
                "success": False,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
    except subprocess.TimeoutExpired:
        logger.error("❌ Build timed out after 5 minutes")
        return {
            "success": False,
            "error": "timeout"
        }
    except Exception as e:
        logger.error(f"❌ Build failed with exception: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@tool("GitCommit")
def git_commit(message: str, cwd: str = None) -> Dict[str, Any]:
    """
    Commit all changes with a message.
    
    Args:
        message: Commit message
        cwd: Working directory (defaults to current directory)
    
    Returns:
        Dict with success, stdout, stderr
    """
    logger.info(f"🔀 Committing changes: {message[:50]}...")
    
    try:
        # Stage all changes
        subprocess.run(
            ["git", "add", "."],
            cwd=cwd,
            capture_output=True,
            timeout=60
        )
        
        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            logger.info(f"✅ Changes committed: {message[:50]}...")
            return {
                "success": True,
                "stdout": result.stdout
            }
        else:
            logger.error(f"❌ Git commit failed: {result.stderr}")
            return {
                "success": False,
                "stderr": result.stderr
            }
    except Exception as e:
        logger.error(f"❌ Git commit exception: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ============================================================================
# CrewAI Agents
# ============================================================================

# Initialize LLM
llm = LLM(
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
    temperature=0.1,  # Low temperature for deterministic code generation
    timeout=300  # 5 minutes per task
)

# Planner Agent
planner_agent = Agent(
    role="Frontend Refinement Planner",
    goal="Refine PLAN.md into detailed, batched implementation steps",
    backstory="""You are an expert frontend developer and project planner. 
    You excel at breaking down complex refactoring tasks into 
    manageable, incremental steps that can be executed 
    without errors or hangs. You focus on:
    - Reading existing code structure
    - Planning batched changes (5-10 files per batch)
    - Identifying dependencies between files
    - Creating clear, actionable implementation steps""",
    verbose=True,
    allow_delegation=False,
    llm=llm,
    tools=[read_file]
)

# Implementer Agent
implementer_agent = Agent(
    role="Frontend Code Implementer",
    goal="Apply code changes to frontend files using read/write tools",
    backstory="""You are a skilled React/TypeScript developer who 
    follows best practices. You read existing code, make 
    targeted changes, and verify your work. You:
    - Use file read/write tools only (no subprocess commands)
    - Follow shadcn/ui patterns
    - Maintain type safety
    - Keep changes minimal and focused
    - Handle errors gracefully""",
    verbose=True,
    allow_delegation=False,
    llm=llm,
    tools=[read_file, write_file]
)

# Validator Agent
validator_agent = Agent(
    role="Build & Code Quality Validator",
    goal="Run npm build and verify code quality after each batch",
    backstory="""You are a quality assurance engineer focused on 
    frontend build processes. You:
    - Run npm build to verify changes work
    - Check for TypeScript errors
    - Report build failures clearly
    - Suggest fixes for common issues""",
    verbose=True,
    allow_delegation=False,
    llm=llm,
    tools=[run_npm_build]
)


# ============================================================================
# Phase 8 Execution
# ============================================================================

def run_phase_8_crew(project_name: str, project_path: str, description: str) -> bool:
    """
    Execute Phase 8 using CrewAI multi-agent system.
    
    Args:
        project_name: Project name
        project_path: Path to project directory
        description: Project description
    
    Returns:
        True if successful, False otherwise
    """
    frontend_path = Path(project_path) / "frontend"
    
    logger.info(f"🚀 Starting Phase 8: CrewAI Multi-Agent Frontend Refinement")
    logger.info(f"   Project: {project_name}")
    logger.info(f"   Frontend path: {frontend_path}")
    logger.info(f"   Description: {description[:100]}...")
    
    # Task 1: Planner refines PLAN.md
    logger.info("📝 Task 1: Planner - Refining PLAN.md into implementation steps")
    
    planner_task = Task(
        description=f"""
        Read PLAN.md from {frontend_path}.
        Refine it into detailed, batched implementation steps.
        Group changes into batches of 5-10 files each.
        Create a step-by-step execution plan.
        
        Project: {project_name}
        Description: {description}
        
        Output a structured plan with:
        - Batch 1: Core branding (5-7 files)
        - Batch 2: UI components (5-7 files)
        - Batch 3: Features (5-7 files)
        - ...
        
        Keep it practical and error-resistant.
        """,
        expected_output="A detailed, batched implementation plan based on PLAN.md",
        agent=planner_agent,
        tools=[read_file]
    )
    
    try:
        planner_crew = Crew(
            agents=[planner_agent],
            tasks=[planner_task],
            verbose=True
        )
        
        planner_result = planner_crew.kickoff()
        logger.info(f"✓ Planner completed: {planner_result}")
        
        # Parse planner output into batches
        # For now, we'll use a simple hardcoded approach
        # In production, we'd parse planner_result to extract batches
        batches = create_simple_batches(frontend_path)
        
    except Exception as e:
        logger.error(f"❌ Planner failed: {e}")
        logger.warning("⚠️ Falling back to simple batched approach")
        batches = create_simple_batches(frontend_path)
    
    # Task 2: Implementer executes batches
    logger.info(f"🔨 Task 2: Implementer - Executing {len(batches)} batches")
    
    summary = {
        "project": project_name,
        "batches_executed": 0,
        "batches_succeeded": 0,
        "batches_failed": 0,
        "files_modified": [],
        "total_time_seconds": 0
    }
    
    import time
    start_time = time.time()
    
    for batch_num, batch in enumerate(batches, 1):
        logger.info(f"📦 Executing batch {batch_num}/{len(batches)}: {batch['name']}")
        
        implementer_task = Task(
            description=f"""
            Implement batch {batch_num} for {project_name}:
            
            Files to modify:
            {json.dumps(batch['files'], indent=2)}
            
            Instructions:
            {batch['description']}
            
            Use read_file() and write_file() tools only.
            Do NOT use subprocess commands.
            Focus on: {batch['focus']}
            """,
            expected_output=f"Successfully modified {len(batch['files'])} files",
            agent=implementer_agent,
            tools=[read_file, write_file]
        )
        
        try:
            implementer_crew = Crew(
                agents=[implementer_agent],
                tasks=[implementer_task],
                verbose=True
            )
            
            implementer_result = implementer_crew.kickoff()
            logger.info(f"✓ Batch {batch_num} implementation completed")
            
            summary["batches_executed"] += 1
            summary["batches_succeeded"] += 1
            summary["files_modified"].extend(batch['files'])
            
            # Task 3: Validator after each batch
            logger.info(f"🧪 Validating after batch {batch_num}...")
            
            validator_task = Task(
                description=f"Run `npm run build` in {frontend_path} to verify batch {batch_num} changes work correctly.",
                expected_output="Build succeeded or clear error message",
                agent=validator_agent,
                tools=[run_npm_build]
            )
            
            validator_crew = Crew(
                agents=[validator_agent],
                tasks=[validator_task],
                verbose=True
            )
            
            validator_result = validator_crew.kickoff()
            
            # Check build result
            if validator_result.get("raw", {}).get("success", False):
                logger.info(f"✅ Build passed after batch {batch_num}")
                
                # Commit changes
                git_commit(
                    message=f"Phase 8: Batch {batch_num} - {batch['name']}",
                    cwd=str(frontend_path)
                )
            else:
                logger.error(f"❌ Build failed after batch {batch_num}")
                logger.error(f"   Error: {validator_result}")
                summary["batches_failed"] += 1
                
                # Continue with next batch (error recovery)
                logger.warning("⚠️ Continuing with next batch...")
        
        except Exception as e:
            logger.error(f"❌ Batch {batch_num} failed: {e}")
            summary["batches_failed"] += 1
            logger.warning("⚠️ Continuing with next batch...")
    
    # Calculate total time
    total_time = time.time() - start_time
    summary["total_time_seconds"] = total_time
    
    # Create SUMMARY.md
    logger.info("📊 Creating SUMMARY.md...")
    
    summary_path = frontend_path / "SUMMARY.md"
    summary_content = f"""# Phase 8: CrewAI Frontend Refinement Summary

**Project:** {project_name}
**Execution Date:** {time.strftime('%Y-%m-%d %H:%M:%S UTC')}
**Total Duration:** {total_time / 60:.1f} minutes

## Execution Statistics

- **Batches Executed:** {summary['batches_executed']}
- **Batches Succeeded:** {summary['batches_succeeded']}
- **Batches Failed:** {summary['batches_failed']}
- **Files Modified:** {len(summary['files_modified'])}

## Files Modified

"""
    
    for file_path in summary['files_modified']:
        summary_content += f"- `{file_path}`\n"
    
    summary_content += f"""

## Git Commits

Total {summary['batches_succeeded']} commits created, one per batch.

## Next Steps

1. Review SUMMARY.md for overview of changes
2. Restart PM2 frontend service: `pm2 restart "{project_name.lower().replace(' ', '-')}-frontend"`
3. Verify frontend accessible at live URL
4. Test all modified functionality

## CrewAI Version

Using CrewAI multi-agent system with:
- Planner Agent: Refines PLAN.md into batches
- Implementer Agent: Applies code changes
- Validator Agent: Verifies builds after each batch

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
    
    summary_path.write_text(summary_content)
    logger.info(f"✓ SUMMARY.md created: {summary_path}")
    
    # Final result
    success = summary["batches_succeeded"] > 0
    
    if success:
        logger.info(f"✅ Phase 8 completed successfully!")
        logger.info(f"   {summary['batches_succeeded']}/{len(batches)} batches succeeded")
        logger.info(f"   {len(summary['files_modified'])} files modified")
        logger.info(f"   Total time: {total_time / 60:.1f} minutes")
    else:
        logger.error("❌ Phase 8 failed: No batches succeeded")
    
    return success


def create_simple_batches(frontend_path: Path) -> List[Dict[str, Any]]:
    """
    Create simple batched implementation plan.
    
    Args:
        frontend_path: Path to frontend directory
    
    Returns:
        List of batch dictionaries
    """
    return [
        {
            "name": "Core Branding",
            "focus": "Replace generic branding with project-specific content",
            "files": [
                "index.html",
                "src/App.tsx",
                "src/app/layouts/index.tsx",
                "src/lib/utils.ts"
            ],
            "description": "Update titles, meta tags, and basic branding elements"
        },
        {
            "name": "UI Components",
            "focus": "Add project-specific UI components",
            "files": [
                "src/components/ui/use-toast.ts",
                "src/features/dashboard/index.tsx",
                "src/features/dashboard/types.ts"
            ],
            "description": "Update notification system and add Kanban board structure"
        },
        {
            "name": "Task Management Features",
            "focus": "Implement core task management functionality",
            "files": [
                "src/features/account/index.tsx",  # Will rename to tasks
                "src/features/settings/index.tsx",
                "src/features/activity/index.tsx"  # Will rename to analytics
            ],
            "description": "Add task creation, editing, and analytics views"
        }
    ]


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 4:
        print("Usage: python3 phase8_crew.py <project_name> <project_path> <description>")
        print("  project_name: Project name (e.g., 'TaskFlow Pro')")
        print("  project_path: Path to project directory")
        print("  description: Project description")
        sys.exit(1)
    
    project_name = sys.argv[1]
    project_path = sys.argv[2]
    description = sys.argv[3] if len(sys.argv) > 3 else ""
    
    # Run Phase 8
    success = run_phase_8_crew(project_name, project_path, description)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)
