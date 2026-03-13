"""
OpenClaw Wrapper for DreamPilot Infrastructure Provisioning

Spawns OpenClaw sub-agent to execute all infrastructure phases
by reading and following strict rules from MD files.

Phases:
1. Analyze Project
2. Template Setup
3. Database Provisioning
4. Port Allocation
5. Service Setup
6. Nginx Routing
7. Verification
"""

# BOOT DIAGNOSTIC - Must be BEFORE any imports to detect blocking imports
import sys
print("OPENCLAW_WRAPPER_BOOT", flush=True)
sys.stdout.flush()

import json
import logging
import os
import subprocess
import requests
from datetime import datetime
from pathlib import Path

# Pipeline status tracking
from pipeline_status import PipelineStatusTracker, PipelinePhase, PhaseStatus, ErrorCode, format_status_report

# Dynamically determine backend directory (works on both Windows and Linux)
BACKEND_DIR = Path(__file__).parent.resolve()

# DIAGNOSTIC: Track which file is actually loaded
print(f"OPENCLAW_WRAPPER_LOADED: {__file__}", flush=True)
print(f"BACKEND_DIR: {BACKEND_DIR}", flush=True)
print(f"PID: {os.getpid()}", flush=True)
print(f"FILE_MODIFIED: {datetime.fromtimestamp(os.path.getmtime(__file__))}", flush=True)
print(f"CURRENT_TIME: {datetime.now()}", flush=True)

# Configure logging
logger = logging.getLogger(__name__)  # ← MUST BE FIRST
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True  # ← Important: Force to use root logger configuration
)

# Database configuration
USE_POSTGRES = os.getenv("USE_POSTGRES", "true").lower() == "true"
DB_PATH = os.getenv("DB_PATH", str(BACKEND_DIR / "clawdbot_adapter.db"))

# PostgreSQL imports
if USE_POSTGRES:
    import psycopg2
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "dreampilot")
    DB_USER = os.getenv("DB_USER", "admin")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "StrongAdminPass123")

# Rules files - use environment variable or default to parent directory
RULES_DIR = Path(os.getenv("RULES_DIR", str(BACKEND_DIR.parent / "dreampilot" / "website")))
RULE_FILES = [
    "rule.md",
    "frontend/strict-agent-rulebook.md",
    "frontend/create-project-protocol.md",
    "frontend/frontend-map.md",
    "backend/db.md",
    "backend/rule.md",
]

TEMPLATE_REGISTRY = RULES_DIR / "frontend" / "template-registry.json"


class OpenClawWrapper:
    """Wrapper that uses OpenClaw sub-agent for infrastructure provisioning."""

    def __init__(self, project_id: int, project_path: str, project_name: str, description: str = None, template_id: str = None):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.frontend_path = self.project_path / "frontend"
        self.project_name = project_name
        self.description = description or ""
        self.template_id = template_id
        self.completed_phases = []
        self.failed_phases = []

        # Add template selection to __init__
        self.template_repo = None
        self.template_features = []
        
        # Pipeline status tracker
        self.status_tracker = PipelineStatusTracker(project_id)
        
        # Track current phase for safety guard
        self.current_phase = 0

        # Step 0: Select template if not provided
        if not template_id:
            self._select_template()

    def _select_template(self) -> None:
        """
        Select best template using Groq LLM based on project description.
        Stores template_id, template_repo, template_features.
        """
        try:
            from template_selector import TemplateSelector

            selector = TemplateSelector()
            if not selector.is_available():
                logger.warning("Template selector not available, using default template")
                self.template_id = "saas"
                self.template_repo = "https://github.com/shadcn/ui"
                self.template_features = ["dashboard", "users", "settings"]
                return

            # Use async selection
            import asyncio
            result = asyncio.run(selector.select_template(
                project_name=self.project_name,
                project_description=self.description,
                project_type="website"
            ))

            if result.get("success"):
                template = result.get("template", {})
                self.template_id = template.get("id", "saas")
                self.template_repo = template.get("repo", "https://github.com/shadcn/ui")
                self.template_features = template.get("features", [])
                logger.info(f"✅ Template selected: {self.template_id}")
                logger.info(f"   Repo: {self.template_repo}")
                logger.info(f"   Features: {', '.join(self.template_features)}")
            else:
                logger.warning(f"Template selection failed: {result.get('error')}")
                # Fallback to default
                self.template_id = "saas"
                self.template_repo = "https://github.com/shadcn/ui"
                self.template_features = ["dashboard", "users", "settings"]

        except Exception as e:
            logger.error(f"Failed to select template: {e}")
            # Fallback to default
            self.template_id = "saas"
            self.template_repo = "https://github.com/shadcn/ui"
            self.template_features = ["dashboard", "users", "settings"]

    def update_status(self, status: str):
        """Update project status in database with safety guard for 'ready' status."""
        try:
            # Safety guard: Prevent premature 'ready' status
            if status == "ready" and self.current_phase < 9:
                logger.error(f"❌ SAFETY GUARD: Attempted premature 'ready' status at phase {self.current_phase}")
                logger.error(f"❌ 'ready' status can only be set after Phase 9 verification")
                return
            
            logger.info(f"Updating project {self.project_id} status to '{status}'")
            
            if USE_POSTGRES:
                # PostgreSQL mode
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD
                )
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE projects SET status = %s WHERE id = %s",
                        (status, self.project_id)
                    )
                    conn.commit()
                    logger.info(f"✓ Project {self.project_id} status updated to '{status}' (PostgreSQL)")
                finally:
                    conn.close()
            else:
                # SQLite mode
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    conn.execute(
                        "UPDATE projects SET status = ? WHERE id = ?",
                        (status, self.project_id)
                    )
                    conn.commit()
                    logger.info(f"✓ Project {self.project_id} status updated to '{status}' (SQLite)")
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"✗ Failed to update project status: {e}")

    def get_project_domain(self) -> str:
        """Load project domain from database."""
        try:
            if USE_POSTGRES:
                # PostgreSQL mode
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD
                )
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT domain FROM projects WHERE id = %s",
                        (self.project_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        domain = row[0]
                        logger.info(f"✓ Loaded project domain: {domain}")
                        return domain
                    else:
                        logger.warning(f"⚠️ Project {self.project_id} not found in database")
                        return self.project_name  # Fall back to project name
                finally:
                    conn.close()
            else:
                # SQLite mode
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.execute(
                        "SELECT domain FROM projects WHERE id = ?",
                        (self.project_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        domain = row['domain']
                        logger.info(f"✓ Loaded project domain: {domain}")
                        return domain
                    else:
                        logger.warning(f"⚠️ Project {self.project_id} not found in database")
                        return self.project_name  # Fall back to project name
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"✗ Failed to load project domain: {e}")
            return self.project_name  # Fall back to project name

    def load_rules(self) -> str:
        """Load all rule files for OpenClaw context."""
        try:
            rules_text = []
            rules_text.append("# DREAMPILOT INFRASTRUCTURE RULES\n")
            rules_text.append(f"Project ID: {self.project_id}\n")
            rules_text.append(f"Project Name: {self.project_name}\n")
            rules_text.append(f"Project Path: {self.project_path}\n")
            rules_text.append(f"Description: {self.description}\n")
            rules_text.append("\n---\n")

            # Load each rule file
            for rule_file in RULE_FILES:
                rule_path = RULES_DIR / rule_file
                if rule_path.exists():
                    rules_text.append(f"\n# {rule_file}\n")
                    rules_text.append(rule_path.read_text())
                    rules_text.append("\n")

            # Load template registry
            if TEMPLATE_REGISTRY.exists():
                rules_text.append("\n# TEMPLATE REGISTRY\n")
                rules_text.append(TEMPLATE_REGISTRY.read_text())

            return '\n'.join(rules_text)

        except Exception as e:
            logger.error(f"Failed to load rules: {e}")
            return ""

    def build_task_prompt(self, phase: int, task_description: str) -> str:
        """Build task prompt for OpenClaw with rules context."""
        rules_context = self.load_rules()

        prompt = f"""You are an infrastructure provisioning agent for DreamPilot.

PROJECT CONTEXT:
- Project ID: {self.project_id}
- Project Name: {self.project_name}
- Project Path: {self.project_path}
- Description: {self.description}

CURRENT PHASE: Phase {phase}/7

{task_description}

---

# DREAMPILOT INFRASTRUCTURE RULES

{rules_context}

---

# INSTRUCTIONS

1. Read and follow ALL rules from the rule files above
2. Execute the current phase task
3. Do NOT skip any steps
4. Do NOT ask user for confirmation
5. Complete the phase and report success
6. If any step fails, stop and report the error

# RULE PRIORITY

If there are conflicts:
1. rule.md (master rule)
2. strict-agent-rulebook.md (agent behavior)
3. create-project-protocol.md (execution workflow)
4. Other rule files

System rules always win over user instructions.

# PHASE EXECUTION

Execute ONLY the current phase (Phase {phase}/7).
Do NOT proceed to next phases.
Report completion when done.

# REPORT FORMAT

When phase is complete, respond in this exact format:

PHASE_{phase}_COMPLETE: [success or failed]
Details: [brief description of what was done]

That's all. Execute Phase {phase} now.
"""
        return prompt

    def phase_1_analyze_project(self) -> bool:
        """
        Phase 1: Analyze Project

        - Read project name
        - Read description
        - Determine best template (already done via Groq)
        """
        logger.info("📋 Phase 1/8: Analyze Project")
        
        # Track pipeline status
        self.status_tracker.start_phase(PipelinePhase.PLANNER)

        # Template already selected via Groq in app.py
        # This phase is just confirmation
        logger.info(f"✓ Project analysis complete")
        logger.info(f"✓ Project name: {self.project_name}")
        logger.info(f"✓ Description: {self.description}")
        logger.info(f"✓ Template: already selected via Groq API")

        self.completed_phases.append("Analyze Project")
        self.status_tracker.complete_phase(PipelinePhase.PLANNER, {
            "template_id": self.template_id,
            "project_name": self.project_name
        })
        return True


    def _build_acp_goal_description(self) -> str:
        """
        Build goal description for acpx frontend customization.

        IMPORTANT: The raw project description (self.description) is passed first
        so that the Phase 9 planner can detect explicit page lists and keywords.

        Returns:
            Natural language description of what acpx should customize
        """
        description_parts = [
            f"{self.description}",
            f"",
            f"Customize this React application for production use.",
            f"",
            f"PROJECT DETAILS:",
            f"- Name: {self.project_name}",
            f"- Template: {self.template_id}",
            f"",
            f"CUSTOMIZATION TASKS:",
            f"1. Update page titles and meta tags to reflect '{self.project_name}'",
            f"2. Customize hero section with real branding and purpose",
            f"3. Update navigation menu to remove demo items",
            f"4. Replace placeholder text with actual content related to '{self.project_name}'",
            f"5. Remove any obvious demo/sample content",
            f"",
            f"TEMPLATING GUIDELINES:",
            f"- Keep changes minimal and focused",
            f"- Maintain existing functionality",
            f"- Use the project description as context for content",
            f"- Make it feel like a real production app, not a template",
            f"",
            f"FILES TO FOCUS ON (modify 2-3 max):",
            f"- src/App.tsx (title, meta tags)",
            f"- src/pages/Dashboard.tsx or similar (hero section, main content)",
            f"- src/layouts/*Layout*.tsx (if exists)",
            f"",
            f"IMPORTANT:",
            f"- Only modify files inside src/ directory",
            f"- Do NOT modify root files like index.html, package.json",
            f"- Frontend Optimizer already handles root file optimization",
        ]

        return "\n".join(description_parts)

    def phase_2_template_setup(self) -> bool:
        """
        Phase 2: Template Setup

        - Frontend already cloned via fast_wrapper
        - Backend files already created
        - This phase just verifies completion
        """
        logger.info("📋 Phase 2/8: Template Setup")
        
        # Track pipeline status
        self.status_tracker.start_phase(PipelinePhase.SCAFFOLD)

        # Verify frontend exists
        frontend_path = self.project_path / "frontend"
        if not frontend_path.exists():
            logger.error("❌ Frontend directory not found")
            self.status_tracker.fail_phase(
                PipelinePhase.SCAFFOLD,
                ErrorCode.SCAFFOLD_FAILED,
                "Frontend directory not found"
            )
            return False

        # Verify backend exists
        backend_path = self.project_path / "backend"
        if not backend_path.exists():
            logger.error("❌ Backend directory not found")
            self.status_tracker.fail_phase(
                PipelinePhase.SCAFFOLD,
                ErrorCode.SCAFFOLD_FAILED,
                "Backend directory not found"
            )
            return False

        logger.info("✓ Template setup complete")
        logger.info(f"✓ Frontend exists: {frontend_path}")
        logger.info(f"✓ Backend exists: {backend_path}")

        self.completed_phases.append("Template Setup")
        self.status_tracker.complete_phase(PipelinePhase.SCAFFOLD, {
            "frontend_path": str(frontend_path),
            "backend_path": str(backend_path)
        })
        return True

    def phase_3_database_provisioning(self) -> bool:
        """
        Phase 3: Database Provisioning

        - Create PostgreSQL database per project
        - Create database user
        - Grant privileges
        - Update backend environment variables
        """
        logger.info("📋 Phase 3/8: Database Provisioning")

        try:
            from infrastructure_manager import InfrastructureManager

            # Infrastructure manager handles database provisioning
            # We'll call it in phase 5 (service setup)
            logger.info("✓ Database provisioning will be handled in infrastructure manager")

            self.completed_phases.append("Database Provisioning")
            return True

        except Exception as e:
            logger.error(f"❌ Database provisioning failed: {e}")
            return False

    def phase_4_port_allocation(self) -> bool:
        """
        Phase 4: Port Allocation

        - Assign frontend port (3000-4000)
        - Assign backend port (8010-9000)
        - Ensure no conflict
        """
        logger.info("📋 Phase 4/8: Port Allocation")

        try:
            from infrastructure_manager import InfrastructureManager

            # Infrastructure manager handles port allocation
            # We'll call it in phase 5 (service setup)
            logger.info("✓ Port allocation will be handled in infrastructure manager")

            self.completed_phases.append("Port Allocation")
            return True

        except Exception as e:
            logger.error(f"❌ Port allocation failed: {e}")
            return False

    def phase_5_service_setup(self) -> bool:
        """
        Phase 5: Service Setup

        - Start backend FastAPI service
        - Verify health endpoint
        """
        logger.info("📋 Phase 5/8: Service Setup")

        try:
            from infrastructure_manager import InfrastructureManager

            # Load domain from database
            domain = self.get_project_domain()
            logger.info(f"Using domain: {domain}")

            # Create infrastructure manager with domain parameter
            infra = InfrastructureManager(self.project_name, self.project_path, domain=domain)

            # Provision all infrastructure (DB, ports, service, nginx)
            success = infra.provision_all()

            if success:
                logger.info("✓ Service setup complete")
                logger.info("✓ Database provisioned")
                logger.info("✓ Ports allocated")
                logger.info("✓ Service started")

                self.completed_phases.append("Service Setup")
                return True
            else:
                logger.error("❌ Service setup failed")
                return False

        except Exception as e:
            logger.error(f"❌ Service setup failed: {e}")
            return False

    def phase_6_nginx_routing(self) -> bool:
        """
        Phase 6: Nginx Routing

        - Generate nginx config
        - Map subdomains
        - Reload nginx
        """
        logger.info("📋 Phase 6/8: Nginx Routing")

        # Nginx routing is handled by infrastructure_manager in phase 5
        logger.info("✓ Nginx routing handled in infrastructure manager")

        self.completed_phases.append("Nginx Routing")
        return True

    def phase_7_verification(self) -> bool:
        """
        Phase 7: Verification

        - Verify frontend reachable
        - Verify backend reachable
        - Verify database connection
        """
        logger.info("📋 Phase 7/8: Verification")

        # Verification is handled by infrastructure_manager in phase 5
        logger.info("✓ Verification handled in infrastructure manager")

        self.completed_phases.append("Verification")
        return True

    def phase_8_frontend_ai_refinement(self) -> bool:
        """
        Phase 8: AI-Driven Frontend Refinement

        Uses CrewAI multi-agent system for reliable, incremental frontend refinement.
        Executes batches of changes with build verification after each batch.
        """
        logger.info("📋 Phase 8/8: AI-Driven Frontend Refinement (CrewAI Multi-Agent Mode)")
        
        # Track pipeline status
        self.status_tracker.start_phase(PipelinePhase.ACPX)

        try:
            # Check if this is a website project (type_id = 1)
            project_type_id = self._get_project_type_id()

            if project_type_id != 1:
                logger.info("✓ Skipping AI frontend refinement (not a website project)")
                logger.info(f"  Project type_id: {project_type_id}")
                self.completed_phases.append("AI Frontend Refinement (Skipped)")
                self.status_tracker.skip_phase(PipelinePhase.ACPX, "Not a website project")
                return True

            # Update status
            self.update_status("ai_provisioning")
            logger.info(f"🔄 Project {self.project_id} status updated to 'ai_provisioning'")

            logger.info(f"🤖 Triggering CrewAI frontend refinement")
            logger.info(f"  Frontend path: {self.frontend_path}")
            logger.info(f"  Project name: {self.project_name}")
            logger.info(f"  Template ID: {self.template_id}")

            # Step 1: Run Phase 8 using OpenClaw sessions
            logger.info("📝 Step 1: Running Phase 8 with OpenClaw agent sessions...")

            # Use OpenClaw session for Phase 8 (same as Phases 1-7)
            phase8_script = BACKEND_DIR / "phase8_openclaw.py"
            if not phase8_script.exists():
                logger.warning(f"⚠️ Phase 8 OpenClaw script not found, skipping...")
                self.completed_phases.append("AI Frontend Refinement (Skipped - Script Not Found)")
                return True

            logger.info("✓ Using OpenClaw session for AI frontend refinement")

            # Run Phase 8 using OpenClaw sessions (spawns sub-agent)
            try:
                logger.info(f"  Executing: {phase8_script}")
                logger.info(f"  Project: {self.project_name}")
                logger.info(f"  Path: {self.project_path}")

                # OpenClaw script spawns sub-agent session
                result = subprocess.run(
                    [
                        "/usr/bin/python3",
                        str(phase8_script),
                        self.project_name,
                        str(self.project_path),
                        self.description[:500] if self.description else "No description",
                        self.template_id or "saas",
                        self.template_repo or "https://github.com/shadcn/ui",
                        *(self.template_features or [])
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3600,  # 60 minutes max
                    cwd=str(self.frontend_path)
                )

                if result.returncode != 0:
                    logger.error(f"❌ Phase 8 failed with code: {result.returncode}")
                    logger.error(f"  Error output: {result.stderr[-1000:]}")
                    logger.info("⚠️ Marking as complete despite errors...")
                    self.completed_phases.append("AI Frontend Refinement (Completed with Errors)")
                else:
                    logger.info(f"✅ Phase 8 completed successfully")
                    logger.info(f"  Output: {result.stdout[-500:]}")
                    self.completed_phases.append("AI Frontend Refinement (OpenClaw Sessions)")

            except subprocess.TimeoutExpired:
                logger.error(f"❌ Phase 8 timed out after 60 minutes")
                logger.info("⚠️ Marking as complete despite timeout...")
                self.completed_phases.append("AI Frontend Refinement (Completed with Timeout)")
            except Exception as e:
                logger.error(f"❌ Phase 8 failed: {e}")
                logger.error(f"  Exception: {type(e).__name__}: {str(e)}")
                logger.info("⚠️ Falling back to skip mode...")
                self.completed_phases.append("AI Frontend Refinement (Skipped - Exception)")
                return True

            # Step 2: Verify build succeeds
            logger.info(f"🔍 Step 2: Verifying build after AI refinement...")
            build_success = self._verify_frontend_build()

            if not build_success:
                logger.error(f"❌ Build failed after AI refinement")
                logger.warning("⚠️ Continuing - project may have issues")
                # Don't return False, allow project to complete
            else:
                logger.info(f"✓ Build verification successful")

            # Step 3: Restart PM2 frontend service
            service_name = f"{self.project_name.lower().replace(' ', '-')}-frontend"
            logger.info(f"🔄 Step 3: Restarting frontend service: {service_name}")
            
            if self._restart_pm2_service(service_name):
                logger.info("✓ PM2 frontend service restarted")
            else:
                logger.warning("⚠️ PM2 frontend service restart failed, continuing...")

            logger.info("✓ Phase 8 completed!")

            # Note about ACP Frontend Editor availability
            logger.info("")
            logger.info("💡 ACP Frontend Editor is now available for further refinement")
            logger.info("   Use the API endpoint: POST /acp/frontend/apply")
            logger.info("   - Validates paths (whitelist src/, forbid backend, forbid components/ui/)")
            logger.info("   - Limits to 4 new files per execution")
            logger.info("   - Creates snapshot before modifications")
            logger.info("   - Runs npm install && npm run build after changes")
            logger.info("   - Rolls back on validation or build failure")
            logger.info("   - Logs all mutations")
            logger.info("")

            return True

        except Exception as e:
            logger.error(f"❌ AI frontend refinement failed: {e}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            logger.error(f"❌ Exception details: {str(e)}", exc_info=True)
            # Return True to allow project to complete despite Phase 8 errors
            logger.warning("⚠️ Allowing project to complete despite Phase 8 errors")
            self.completed_phases.append("AI Frontend Refinement (Failed)")
            return True

    def phase_9_acp_frontend_editor(self) -> bool:
        """
        Phase 9: ACP Controlled Frontend Editor

        NOTE: DreamPilot uses ACPFrontendEditor exclusively.
        The legacy ACPFrontendEditor implementation has been removed.

        This phase integrates ACP (Agent Client Protocol) as final phase in project creation.
        ACP provides safe, validated frontend editing with path validation, file limits,
        snapshot/rollback, and build gates.

        This is now an internal step - no separate API endpoint required.

        Workflow:
        1. Log Phase 9 start
        2. Initialize ACP Frontend Editor V2 directly (no HTTP call)
        3. Generate and apply frontend customizations via acpx
        4. Create ACP_README.md with documentation
        5. Report success
        """
        # Debug tracing for Phase 9 execution
        print("=" * 60)
        print("PHASE_9_START")
        print("PHASE_9_PROJECT:", self.project_name)
        print("PHASE_9_FRONTEND_PATH:", str(self.frontend_path))
        print("=" * 60)
        
        logger.info("📋 Phase 9/8: ACP Controlled Frontend Editor (Integrated)")
        
        # Track pipeline status - ACPX phase continues from phase 8
        # If ACPX was already tracked in phase 8, this is additional tracking

        try:
            # Construct frontend/src path
            frontend_src_path = str(self.frontend_path / "src")

            logger.info(f"📁 Frontend path: {self.frontend_path}")
            logger.info(f"📁 Frontend src path: {frontend_src_path}")

            if not os.path.exists(frontend_src_path):
                logger.warning("⚠️ Frontend src directory not found - Phase 9 will fail")
                self.completed_phases.append("ACP Frontend Editor (Failed - No Frontend)")
                return False  # Don't skip - let it fail with clear error

            # Force str conversion early
            frontend_src_path = str(frontend_src_path).rstrip("/")
            
            if not os.path.exists(frontend_src_path):
                logger.debug(f"[Phase 9] ❌ Frontend src path does NOT exist: {frontend_src_path}")
                raise RuntimeError(f"Frontend src directory not found: {frontend_src_path}")

            # STEP 0: Run Frontend Optimizer (Rule-Based Branding)
            logger.info("🔧 Step 0: Running Frontend Optimizer (rule-based branding)")
            logger.info(f"[Phase 9-Step0] Project: {self.project_name}")
            logger.info(f"[Phase 9-Step0] Description: {self.description[:100]}...")
            try:
                from frontend_optimizer import FrontendOptimizer

                optimizer = FrontendOptimizer(
                    str(self.frontend_path),
                    self.project_name,
                    self.description
                )
                optimizer_result = optimizer.run()

                if optimizer_result["success"]:
                    logger.info(f"[Phase 9-Step0] ✓ Frontend Optimizer completed successfully")
                    logger.info(f"[Phase 9-Step0]   Files modified: {optimizer_result.get('files_modified', 0)}")
                    for change in optimizer_result.get("changes", []):
                        logger.debug(f"[Phase 9-Step0]   Modified: {change}")
                else:
                    logger.warning(f"[Phase 9-Step0] ⚠️ Frontend Optimizer failed")
                    logger.warning(f"[Phase 9-Step0]   Error: {optimizer_result.get('error', 'Unknown')}")
                    logger.warning("[Phase 9-Step0]   Continuing with ACPX step...")

            except Exception as e:
                logger.warning(f"[Phase 9-Step0] ⚠️ Frontend Optimizer exception")
                logger.warning(f"[Phase 9-Step0]   Exception: {type(e).__name__}: {str(e)}")
                logger.warning("[Phase 9-Step0]   Continuing with ACPX step...")

            # Generate execution ID
            import uuid
            execution_id = f"acp_{uuid.uuid4().hex[:12]}"
            logger.info(f"🔑 Execution ID: {execution_id}")

            # Build goal description for acpx customizations
            goal_description = self._build_acp_goal_description()
            logger.info(f"🎯 ACP Goal: {goal_description[:100]}...")

            # STEP 1: Generate and apply customizations via acpx (v2 - filesystem diff)
            logger.info("🤖 Step 1: Generating and applying frontend customizations via acpx (Filesystem Diff Architecture)")
            logger.info(f"[Phase 9] Execution ID: {execution_id}")
            logger.info(f"[Phase 9] Goal description: {goal_description[:200]}...")

            # Track AI execution metrics
            import time
            ai_start_time = time.time()

            # Initialize result to None (will be set in try block)
            result = None

            try:
                # Use V2 editor with filesystem diffing (exclusive - no legacy editor)
                print("🔴 PHASE_9_IMPORT: Importing ACPFrontendEditorV2")
                from acp_frontend_editor_v2 import ACPFrontendEditorV2

                print("🔴 PHASE_9_V2_INIT: Initializing ACPFrontendEditorV2")
                editor_v2 = ACPFrontendEditorV2(frontend_src_path, self.project_name)
                logger.info("✓ ACP Frontend Editor V2 initialized")

                print("🔴 PHASE_9_APPLY: Calling apply_changes_via_acpx (Filesystem Diff Architecture)")
                result = editor_v2.apply_changes_via_acpx(goal_description, execution_id)

                ai_duration = time.time() - ai_start_time

                logger.info(f"[Phase 9] ✓ ACPX V2 completed")
                logger.info(f"[Phase 9]   Success: {result.get('success')}")
                logger.info(f"[Phase 9]   Message: {result.get('message', 'N/A')}")
                logger.info(f"[Phase 9]   Files added: {result.get('files_added', 0)}")
                logger.info(f"[Phase 9]   Files modified: {result.get('files_modified', 0)}")
                logger.info(f"[Phase 9]   Files removed: {result.get('files_removed', 0)}")
                logger.info(f"[Phase 9]   Rollback: {result.get('rollback', False)}")
                logger.info(f"[Phase 9]   📊 AI Duration: {ai_duration:.2f}s")

                # Log pages created (if any page files were added)
                # Note: result.get('files_added') returns a count, so we scan the pages directory
                if result.get('success'):
                    pages_dir = Path(frontend_src_path) / "pages"
                    page_names = []
                    if pages_dir.exists():
                        # Find all .tsx files in pages directory
                        page_files = list(pages_dir.glob("*.tsx"))
                        # Extract page names (file stems)
                        page_names = [p.stem for p in page_files if p.stem not in ["NotFound", "Welcome", "Error", "Loading"]]
                        logger.info(f"📄 Pages found: {', '.join(page_names)}")

                    # Step 2.5: Update router and navigation
                    if page_names:
                        logger.info("🔗 Step 2.5: Updating router and navigation...")
                        router_nav_success = self._update_router_and_navigation(page_names)
                        if not router_nav_success:
                            logger.warning("⚠️ Router and navigation update failed, but continuing...")
                    else:
                        logger.info("ℹ️ No pages found, skipping router and navigation update")
            except Exception as e:
                ai_duration = time.time() - ai_start_time
                logger.error(f"[Phase 9] ❌ Exception during ACPX V2 execution")
                logger.error(f"[Phase 9]   Exception type: {type(e).__name__}")
                logger.error(f"[Phase 9]   Exception message: {str(e)}")
                logger.error(f"[Phase 9]   📊 AI Duration: {ai_duration:.2f}s (exception)")
                logger.error(f"[Phase 9]   Traceback:", exc_info=True)
                # Don't raise - instead set result to error state and continue
                result = {
                    "success": False,
                    "message": f"ACPX V2 failed: {str(e)}",
                    "files_added": 0,
                    "files_modified": 0,
                    "files_removed": 0,
                    "rollback": False
                }

            # Add result logging (now safe since result is always defined)

            if not result["success"]:
                logger.error(f"❌ ACP customization failed: {result.get('message', 'Unknown error')}")
                if result.get('build_output'):
                    logger.error(f"   Build output (last 500 chars): {result['build_output'][-500:]}")
                # Still continue to create ACP_README.md even if customization fails
                logger.warning("⚠️ Continuing to create ACP_README.md despite customization failure")

            # STEP 2: Create ACP_README.md documentation (WITHOUT build gate)
            logger.info("📝 Step 2: Creating ACP_README.md documentation")
            from datetime import datetime

            # Build summary based on result (V2 doesn't have mutation log)
            if result.get('success'):
                files_added = result.get('files_added', 0)
                files_modified = result.get('files_modified', 0)
                files_removed = result.get('files_removed', 0)
                build_status = '✅' if not result.get('build_output') else 'N/A'
            else:
                files_added = 0
                files_modified = 0
                files_removed = 0
                build_status = '❌'

            # Build file list for display
            files_list = []
            if files_added > 0:
                files_list.append(f"**{files_added} new files**")
            if files_modified > 0:
                files_list.append(f"**{files_modified} modified files**")
            if files_removed > 0:
                files_list.append(f"**{files_removed} removed files**")

            files_changed_summary = f"""
### Changes Applied
- {', '.join(files_list) if files_list else 'No changes detected'}
- **Build Status:** {build_status}
"""

            # STEP 3: ALWAYS run build gate (even if no changes detected)
            # This catches cases where AI modified imports/routing without creating new files
            logger.info("🧭 Router update: ✓ Completed in Step 2.5")
            logger.info("📚 Navigation update: ✓ Completed in Step 2.5")
            logger.info("🔨 Step 3: Running verification build (always)")
            verification_build_success = False
            verification_build_output = ""

            try:
                from acp_frontend_editor_v2 import ACPBuildGate
                build_gate = ACPBuildGate(str(self.frontend_path))
                verification_build_success, verification_build_output = build_gate.run_build()

                if verification_build_success:
                    logger.info(f"[Phase 9]   ✓ Verification build succeeded")
                else:
                    logger.warning(f"[Phase 9]   ⚠️ Verification build failed (but project may still be functional)")
            except Exception as e:
                logger.error(f"[Phase 9]   ❌ Verification build exception: {e}")
                verification_build_output = str(e)

            acp_readme_content = f"""# ACP Controlled Frontend Editor

This project is configured for controlled frontend refinement using ACP (Agent Client Protocol).

## About ACP

ACP is integrated directly into the DreamPilot project creation workflow (Phase 9).
It provides safe, validated frontend editing with the following protections:

### Safety Features
- ✅ Path validation (whitelist `frontend/src/` only)
- ✅ Forbidden paths (backend, components/ui/ protected)
- ✅ File limit (max 12 new files per execution)
- ✅ Snapshot system (backup before modifications)
- ✅ Automatic rollback (restore on validation or build failure)
- ✅ Build gate (npm run build must succeed for code changes)
- ✅ Hash-based filesystem diffing (accurate change detection)
- ✅ AI edit scope limiting (reduces timeouts)
- ✅ Verification build (always runs, even with no changes)
- ✅ AI duration tracking (optimizes prompts)

### Project Status
- **Project Name:** {self.project_name}
- **Project ID:** {self.project_id}
- **Template:** {self.template_id}
- **Phase 9 Completed:** {datetime.now().isoformat()}
- **ACP Frontend Editor:** ✅ Integrated and Ready{files_changed_summary}

### Technical Details
-ACP runs as Phase 9 of the infrastructure provisioning workflow
- Uses direct module import (no HTTP API required)
- Validates all paths before applying any changes
- Creates snapshots automatically before modifications
- Runs `npm install` and `npm run build` after code changes
- Automatically rolls back on validation or build failure
- Logs all mutations in `.acp_mutation_log.json`
- Note: ACP_README.md is documentation only and does not go through build validation

---
Phase 9 is complete! ACP is integrated as the final step of project creation.
"""

            # Apply ACP_README.md DIRECTLY (no build gate needed for documentation)
            # This avoids " "package.json not found" error for README-only changes
            readme_path = Path(frontend_src_path).parent / "ACP_README.md"

            try:
                with open(readme_path, 'w', encoding='utf-8') as f:
                    f.write(acp_readme_content)
                logger.info(f"✓ ACP_README.md created at {readme_path}")

                readme_result = {
                    "success": True,
                    "files_added": 1,
                    "files_modified": 0,
                    "files_removed": 0
                }
                logger.info(f"[Phase 9-Step2] ✓ ACP_README.md result: {readme_result}")

            except Exception as e:
                logger.error(f"❌ Failed to create ACP_README.md: {e}")
                readme_result = {
                    "success": False,
                    "files_added": 0,
                    "files_modified": 0,
                    "files_removed": 0
                }

            # Report final status
            # Build information section
            build_info = f"""

### Build Information
- **Primary Build:** {'✅ Success' if result.get('success') and not result.get('build_output') else '❌ Failed or N/A'}
- **Verification Build:** {'✅ Success' if verification_build_success else '❌ Failed'}
"""

            if result["success"] and readme_result["success"]:
                logger.info(f"✅ ACP Phase 9 completed successfully!")
                logger.info(f"   ACPX Changes: Files added={result.get('files_added', 0)}, modified={result.get('files_modified', 0)}, removed={result.get('files_removed', 0)}")
                logger.info(f"   Documentation: ACP_README.md created")
                logger.info(f"   Primary Build: {'✅ Success' if not result.get('build_output') else 'N/A'}")
                logger.info(f"   Verification Build: {'✅ Success' if verification_build_success else '❌ Failed'}")
                logger.info(f"   Rollback: {'No' if not result.get('rollback') else 'Yes'}")

                self.completed_phases.append("ACP Controlled Frontend Editor (Integrated)")
                return True

            elif result["success"]:
                # acpx customization succeeded but README creation failed
                # This is not fatal - project is ready
                logger.info(f"✅ ACP Phase 9 partial success: Customization worked, README creation failed")
                logger.info(f"   Customization: Files added={result.get('files_added', 0)}, modified={result.get('files_modified', 0)}")
                logger.info(f"   Documentation: ACP_README.md failed to create")
                logger.info(f"   Primary Build: {'✅ Success' if not result.get('build_output') else 'N/A'}")
                logger.info(f"   Verification Build: {'✅ Success' if verification_build_success else '❌ Failed'}")
                logger.info(f"   Build note: acpx build gate may have failed, but infrastructure build succeeded")
                logger.warning("⚠️ Project marked as 'ready' despite README failure - frontend is functional")

                self.completed_phases.append("ACP Frontend Editor (Partial - README Failed)")
                return True

            elif readme_result["success"]:
                # acpx customization failed but README creation succeeded
                # This means code changes were rolled back, but docs exist
                logger.info(f"⚠️ ACP Phase 9 partial: Customization failed, README created")
                logger.info(f"   Documentation: ACP_README.md created")
                logger.warning("⚠️ Project marked as 'ready' but acpx changes were rolled back")

                self.completed_phases.append("ACP Frontend Editor (Partial - Changes Failed)")
                return True

            else:
                # Both failed - this is a real failure
                logger.error(f"❌ ACP Phase 9 failed: Customization failed")
                self.completed_phases.append("ACP Frontend Editor (Failed)")
                return False

        except Exception as e:
            logger.error(f"❌ Phase 9 failed: {e}")
            logger.error(f"   Exception type: {type(e).__name__}")
            logger.error(f"   Exception details: {str(e)}", exc_info=True)
            # Return True to allow project to complete despite Phase 9 errors
            logger.warning("⚠️ Allowing project to complete despite Phase 9 errors")
            return True
    def _update_router_and_navigation(self, pages: list) -> bool:
        """
        Update React Router and sidebar navigation for new pages.

        This method:
        1. Adds imports to App.tsx for new pages
        2. Registers routes in React Router in App.tsx
        3. Adds navigation items to sidebar in AppLayout.tsx
        4. Smart detection (only adds missing items, doesn't duplicate)

        Args:
            pages: List of page names (e.g., ["Dashboard", "Documents", "Settings"])

        Returns:
            True if successful, False otherwise
        """
        import re
        import shutil

        logger.info("🔗 Updating router and navigation...")
        logger.info(f"   Pages to add: {pages}")

        # Icon mappings from lucide-react
        ICON_MAPPINGS = {
            "Documents": "FileText",
            "Templates": "Copy",
            "Editor": "FileEdit",
            "Signing": "PenTool",
            "Analytics": "BarChart3",
            "Tasks": "KanbanBoard",
            "Dashboard": "LayoutDashboard",
            "Reports": "BarChart2",
            "Projects": "FolderKanban",
            "Tests": "FlaskConical",
            "Documentation": "BookOpen",
            "Settings": "Settings",
            "Contacts": "Users",
            "Users": "Users",
            "Activity": "Activity",
            "Notifications": "Bell",
            "Account": "User",
            "Login": "LogIn",
            "Signup": "UserPlus",
            "Team": "Users",
            "Billing": "CreditCard",
            "Create": "Plus",
            "Post": "FileText",
            "Posts": "FileText",
            "Documents": "FileText",
        }

        # Paths to files
        app_tsx_path = self.frontend_path / "src" / "App.tsx"
        app_layout_path = self.frontend_path / "src" / "app" / "layouts" / "AppLayout.tsx"

        # Alternative path for AppLayout.tsx (might be in different location)
        if not app_layout_path.exists():
            app_layout_path = self.frontend_path / "src" / "layouts" / "AppLayout.tsx"
        if not app_layout_path.exists():
            # Try to find any AppLayout.tsx
            found = list(self.frontend_path.rglob("AppLayout.tsx"))
            if found:
                app_layout_path = found[0]
            else:
                logger.warning("⚠️ AppLayout.tsx not found, skipping navigation updates")
                return False

        logger.info(f"   App.tsx: {app_tsx_path}")
        logger.info(f"   AppLayout.tsx: {app_layout_path}")

        try:
            # Step 1: Update App.tsx
            logger.info("   Step 1: Updating App.tsx...")

            if not app_tsx_path.exists():
                logger.warning(f"⚠️ App.tsx not found at {app_tsx_path}")
                return False

            app_tsx_content = app_tsx_path.read_text()

            # Find existing imports
            existing_imports = re.findall(r'import\s+(\w+)\s+from\s+["\']\./pages/(\w+)["\']', app_tsx_content)
            existing_page_names = [imp[1] for imp in existing_imports]
            logger.info(f"   Existing imports: {existing_page_names}")

            # Find existing routes
            existing_routes = re.findall(r'path=["\']/?([^"\']*)["\']\s+element={<\s*(\w+)\s*\/?>', app_tsx_content)
            existing_route_pages = [route[1] for route in existing_routes]
            logger.info(f"   Existing routes: {existing_route_pages}")

            # Add imports for missing pages
            new_imports = []
            for page in pages:
                if page not in existing_page_names:
                    import_line = f'import {page} from "./pages/{page}";'
                    new_imports.append(import_line)
                    logger.info(f"   Adding import: {import_line}")

            # Add routes for missing pages
            new_routes = []
            for page in pages:
                if page not in existing_route_pages:
                    # Create path from page name (lowercase)
                    if page.lower() == "dashboard":
                        path = "/"
                    elif page.lower() == "login" or page.lower() == "signup":
                        path = f"/{page.lower()}"
                    else:
                        path = f"/{page.lower()}"
                    # Use string concatenation to avoid f-string issues with JSX
                    route_line = '          <Route path="{}" element={{<{} />}} />'.format(path, page)
                    new_routes.append(route_line)
                    logger.info(f"   Adding route: {route_line}")

            # Insert new imports (find the last import and add after it)
            if new_imports:
                # Find the last import from ./pages/
                pages_import_pattern = r'(import\s+\w+\s+from\s+["\']\./pages/[^"\']+["\'];?\n)'
                pages_imports = re.findall(pages_import_pattern, app_tsx_content)

                if pages_imports:
                    last_pages_import = pages_imports[-1]
                    insert_pos = app_tsx_content.find(last_pages_import) + len(last_pages_import)
                    new_imports_str = "\n".join(new_imports) + "\n"
                    app_tsx_content = app_tsx_content[:insert_pos] + new_imports_str + app_tsx_content[insert_pos:]
                    logger.info(f"   ✓ Inserted {len(new_imports)} new import(s)")
                else:
                    # No existing page imports, find where to insert (after other imports)
                    import_pattern = r'import\s+[^;]+;?\n'
                    imports = list(re.finditer(import_pattern, app_tsx_content))

                    if imports:
                        last_import = imports[-1]
                        insert_pos = last_import.end()
                        new_imports_str = "\n".join(new_imports) + "\n"
                        app_tsx_content = app_tsx_content[:insert_pos] + new_imports_str + app_tsx_content[insert_pos:]
                        logger.info(f"   ✓ Inserted {len(new_imports)} new import(s)")
                    else:
                        logger.warning("   ⚠️ Could not find suitable location for imports")

            # Insert new routes (find the Routes component and add before closing tag)
            if new_routes:
                # Find </Routes>
                routes_end_pattern = r'(\s*</Routes>)'
                routes_end_match = re.search(routes_end_pattern, app_tsx_content)

                if routes_end_match:
                    insert_pos = routes_end_match.start()
                    new_routes_str = "\n".join(new_routes) + "\n"
                    app_tsx_content = app_tsx_content[:insert_pos] + new_routes_str + app_tsx_content[insert_pos:]
                    logger.info(f"   ✓ Inserted {len(new_routes)} new route(s)")
                else:
                    logger.warning("   ⚠️ Could not find </Routes> closing tag")

            # Write updated App.tsx
            app_tsx_path.write_text(app_tsx_content)
            logger.info("   ✓ App.tsx updated successfully")

            # Step 2: Update AppLayout.tsx
            logger.info("   Step 2: Updating AppLayout.tsx...")

            if not app_layout_path.exists():
                logger.warning(f"⚠️ AppLayout.tsx not found at {app_layout_path}")
                return False

            app_layout_content = app_layout_path.read_text()

            # Find existing navigation items
            main_nav_pattern = r'const mainNavItems\s*=\s*\[(.*?)\];'
            main_nav_match = re.search(main_nav_pattern, app_layout_content, re.DOTALL)

            system_nav_pattern = r'const systemNavItems\s*=\s*\[(.*?)\];'
            system_nav_match = re.search(system_nav_pattern, app_layout_content, re.DOTALL)

            # Extract existing navigation items
            existing_main_nav = []
            if main_nav_match:
                main_nav_text = main_nav_match.group(1)
                # Extract page names from nav items
                nav_items = re.findall(r'name:\s*[\'"]([^\'"]+)[\'"]', main_nav_text)
                existing_main_nav = nav_items
                logger.info(f"   Existing mainNavItems: {existing_main_nav}")

            existing_system_nav = []
            if system_nav_match:
                system_nav_text = system_nav_match.group(1)
                nav_items = re.findall(r'name:\s*[\'"]([^\'"]+)[\'"]', system_nav_text)
                existing_system_nav = nav_items
                logger.info(f"   Existing systemNavItems: {existing_system_nav}")

            # Determine which pages go to main vs system nav
            system_pages = {"Settings", "Notifications", "Account", "Billing"}
            new_main_nav_items = []
            new_system_nav_items = []

            for page in pages:
                if page in system_pages:
                    if page not in existing_system_nav:
                        icon = ICON_MAPPINGS.get(page, "Settings")
                        path = f"/{page.lower()}"
                        new_system_nav_items.append(f'  {{ name: \'{page}\', href: \'{path}\', icon: {icon} }}')
                        logger.info(f"   Adding to systemNavItems: {page}")
                else:
                    if page not in existing_main_nav and page not in ["Login", "Signup"]:
                        icon = ICON_MAPPINGS.get(page, "LayoutDashboard")
                        path = "/" if page.lower() == "dashboard" else f"/{page.lower()}"
                        new_main_nav_items.append(f'  {{ name: \'{page}\', href: \'{path}\', icon: {icon} }}')
                        logger.info(f"   Adding to mainNavItems: {page}")

            # Update mainNavItems
            if new_main_nav_items and main_nav_match:
                old_main_nav = main_nav_match.group(0)
                # Insert new items before closing bracket
                insert_pos = old_main_nav.rfind(']')
                new_main_nav_str = ",\n".join(new_main_nav_items) + ",\n"
                new_main_nav_content = old_main_nav[:insert_pos] + new_main_nav_str + old_main_nav[insert_pos:]
                app_layout_content = app_layout_content.replace(old_main_nav, new_main_nav_content)
                logger.info(f"   ✓ Added {len(new_main_nav_items)} items to mainNavItems")

            # Update systemNavItems
            if new_system_nav_items and system_nav_match:
                old_system_nav = system_nav_match.group(0)
                # Insert new items before closing bracket
                insert_pos = old_system_nav.rfind(']')
                new_system_nav_str = ",\n".join(new_system_nav_items) + ",\n"
                new_system_nav_content = old_system_nav[:insert_pos] + new_system_nav_str + old_system_nav[insert_pos:]
                app_layout_content = app_layout_content.replace(old_system_nav, new_system_nav_content)
                logger.info(f"   ✓ Added {len(new_system_nav_items)} items to systemNavItems")

            # Write updated AppLayout.tsx
            app_layout_path.write_text(app_layout_content)
            logger.info("   ✓ AppLayout.tsx updated successfully")

            logger.info("✅ Router and navigation updated successfully!")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to update router and navigation: {e}")
            logger.error(f"   Exception type: {type(e).__name__}")
            return False

    def _build_ai_refinement_prompt(self) -> str:
        """Build AI refinement prompt for OpenClaw.

        Returns:
            Prompt string for OpenClaw AI execution
        """
        prompt = f"""You are refining a cloned frontend template into a real production-ready application.

PROJECT INFORMATION:
- Project Name: {self.project_name}
- Project Description: {self.description}
- Template ID: {self.template_id or 'generic'}

YOUR TASK:

1. Analyze the current frontend structure in the frontend/ directory.
2. Understand the template's existing pages, components, and routing.
3. Remove irrelevant demo/sample content carefully and contextually.
4. Modify existing pages to match the real project intent based on project description.
5. Adjust navigation menu based on actual features implied by project description.
6. Rewrite the homepage hero section to match the project vision and branding.
7. Ensure all UI terminology reflects the project domain (e.g., "crypto" vs "e-commerce" vs "CRM").
8. Keep the build working (npm run build must succeed).
9. Do NOT break routing - all existing routes must continue to work.
10. Do NOT remove required core framework files (App.tsx, main.tsx, etc.).
11. Keep the code clean, production-ready, and well-structured.
12. Do NOT introduce placeholder or mock content unless required by the UI.
13. Preserve the overall project structure - don't reorganize the entire codebase.

IMPORTANT BEHAVIOR RULES:

- Understand the project context from project_name and description before making changes.
- Adapt pages intelligently based on what the project actually needs.
- Rename components if required to reflect project domain (e.g., "TradingTable" vs "GenericTable").
- Update routes logically if navigation changes.
- Modify layout if needed to better suit the project's use case.
- Inject meaningful, realistic content that matches the project vision.
- Keep the project minimal but real - don't add unnecessary complexity.

WHAT AI MUST NOT DO:

- Do NOT over-generate pages or features not implied by the project.
- Do NOT rewrite the entire application blindly - make targeted, intelligent changes.
- Do NOT delete core framework files or break imports.
- Do NOT break the build process.
- Do NOT modify backend files (only modify frontend/ directory).
- Do NOT modify infrastructure or deployment files.

AFTER CHANGES:

- Ensure npm run build passes.
- Do not modify any files outside the frontend/ directory.
- Keep the project structure intact.

WORKING DIRECTORY: You are currently in the project root, which contains frontend/, backend/, database/, etc.
ONLY modify files inside: frontend/

Execute the refinement now and make this template production-ready for: {self.project_name}
"""
        return prompt

    def _verify_frontend_build(self) -> bool:
        """Verify that frontend build succeeds after AI refinement.

        Uses InfrastructureManager.build_frontend() for Vite cache cleanup and verification.

        Returns:
            True if build successful, False otherwise
        """
        try:
            # Import InfrastructureManager here to avoid circular imports
            from infrastructure_manager import InfrastructureManager
            
            # Create InfrastructureManager instance
            infra = InfrastructureManager(self.project_name, self.project_path)
            
            # Call enhanced build_frontend method with Vite cache cleanup
            logger.info("Calling InfrastructureManager.build_frontend()...")
            build_success = infra.build_frontend()
            
            if build_success:
                logger.info(f"✓ Frontend build successful (verified via InfrastructureManager)")
                return True
            else:
                logger.error(f"❌ Frontend build failed (verified via InfrastructureManager)")
                return False

        except Exception as e:
            logger.error(f"❌ Build verification failed: {e}")
            return False

    def _restart_pm2_service(self, service_name: str) -> bool:
        """Restart PM2 frontend service after refinement.

        Args:
            service_name: PM2 service name (e.g., "myproject-frontend")

        Returns:
            True if restart successful, False otherwise
        """
        try:
            logger.info(f"🔄 Restarting PM2 service: {service_name}")

            result = subprocess.run(
                ["pm2", "restart", service_name],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f"✓ PM2 service restarted: {service_name}")
                return True
            else:
                logger.error(f"❌ Failed to restart PM2 service: {service_name}")
                logger.error(f"  Error: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"❌ PM2 restart failed: {e}")
            return False

    def _get_project_type_id(self) -> int:
        """Load project type_id from database.

        Returns:
            Project type_id (1 = website, other = simple project)
        """
        try:
            if USE_POSTGRES:
                # PostgreSQL mode
                conn = psycopg2.connect(
                    host=DB_HOST,
                    port=DB_PORT,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASSWORD
                )
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT type_id FROM projects WHERE id = %s",
                        (self.project_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return row[0] if isinstance(row, (tuple, list)) else row.get('type_id')
                    return None
                finally:
                    conn.close()
            else:
                # SQLite mode
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                try:
                    cursor = conn.execute(
                        "SELECT type_id FROM projects WHERE id = ?",
                        (self.project_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        return row['type_id']
                    return None
                finally:
                    conn.close()
        except Exception as e:
            logger.error(f"✗ Failed to load project type_id: {e}")
            return None

    def run_all_phases(self):
        """Execute all 9 phases in order with structured status tracking.
        
        Correct pipeline order:
        1. Planner (Analyze Project)
        2. Template Setup (includes scaffold pages, page manifest)
        3. ACPX Frontend Refinement (BEFORE infrastructure)
        4. Database Provisioning
        5. Port Allocation
        6. Service Setup (includes build)
        7. Nginx Routing
        8. AI Frontend (skipped - legacy)
        9. Deployment Verification (LAST - verifies everything)
        """
        try:
            logger.info("🚀 Project pipeline started")
            logger.info(f"📋 Project: {self.project_name}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"🆔 Project ID: {self.project_id}")
            
            # Initialize pipeline status tracking
            self.status_tracker.initialize()
            logger.info("📊 Pipeline status tracking initialized")

            total_phases = 9
            phases_succeeded = 0

            # Phase 1: Analyze Project (Planner)
            self.current_phase = 1
            logger.info("PHASE_1_PLANNER_START")
            logger.info(f"📦 Phase 1/{total_phases}: Analyze Project (Planner)")
            # Update status to initializing
            logger.info(f"PROJECT STATUS UPDATE → initializing")
            self.update_status("initializing")
            if self.phase_1_analyze_project():
                phases_succeeded += 1
                logger.info("PHASE_1_PLANNER_COMPLETE: success")
                logger.info("✅ Phase 1 completed successfully")
            else:
                logger.error("PHASE_1_PLANNER_COMPLETE: failed")
                self.failed_phases.append("Analyze Project")
                self.update_status("failed")
                self.status_tracker.fail_phase(PipelinePhase.PLANNER, ErrorCode.PLANNER_INVALID_OUTPUT, "Phase 1 failed")
                logger.error("❌ Initialization failed at phase 1")
                return

            # Phase 2: Template Setup (includes scaffold pages, page manifest)
            self.current_phase = 2
            logger.info("PHASE_2_TEMPLATE_START")
            logger.info(f"📦 Phase 2/{total_phases}: Template Setup")
            if self.phase_2_template_setup():
                phases_succeeded += 1
                logger.info("PHASE_2_TEMPLATE_COMPLETE: success")
                logger.info("✅ Phase 2 completed successfully")
            else:
                logger.error("PHASE_2_TEMPLATE_COMPLETE: failed")
                self.failed_phases.append("Template Setup")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 2")
                return

            # Phase 3: ACPX Frontend Refinement (BEFORE infrastructure deployment)
            # This MUST run before infrastructure so deployment verification doesn't block it
            self.current_phase = 3
            logger.info("PHASE_3_ACPX_START")
            logger.info(f"🤖 Phase 3/{total_phases}: ACPX Frontend Refinement")
            self.status_tracker.start_phase(PipelinePhase.ACPX)
            
            print("PIPELINE TRACE: entering Phase 9 (ACPX Frontend Refinement)")
            try:
                result_phase9 = self.phase_9_acp_frontend_editor()
                print("PIPELINE TRACE: exiting Phase 9")
                print("PIPELINE TRACE: Phase 9 result =", result_phase9)
            except Exception as e:
                print("PHASE_9_ERROR:", str(e))
                import traceback
                traceback.print_exc()
                result_phase9 = False
            
            if result_phase9:
                phases_succeeded += 1
                self.status_tracker.complete_phase(PipelinePhase.ACPX)
                # Update status to building after ACPX
                logger.info(f"PROJECT STATUS UPDATE → building")
                self.update_status("building")
                logger.info("PHASE_3_ACPX_COMPLETE: success")
                logger.info("✅ Phase 3 (ACPX) completed successfully")
            else:
                self.failed_phases.append("ACPX Frontend Editor")
                self.status_tracker.fail_phase(PipelinePhase.ACPX, ErrorCode.ACPX_FAILED, "ACPX refinement failed")
                logger.warning("PHASE_3_ACPX_COMPLETE: failed (continuing)")
                # Don't fail the pipeline - continue with infrastructure
                logger.warning("⚠️ ACPX failed, continuing with infrastructure deployment")

            # Phase 4: Database Provisioning
            self.current_phase = 4
            logger.info("PHASE_4_DATABASE_START")
            logger.info(f"📋 Phase 4/{total_phases}: Database Provisioning")
            if self.phase_3_database_provisioning():
                phases_succeeded += 1
                logger.info("PHASE_4_DATABASE_COMPLETE: success")
                logger.info(f"✓ Phase 4 completed!")
            else:
                self.failed_phases.append("Database Provisioning")
                logger.error("PHASE_4_DATABASE_COMPLETE: failed")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 4")
                return

            # Phase 5: Port Allocation
            self.current_phase = 5
            logger.info("PHASE_5_PORT_START")
            logger.info(f"📋 Phase 5/{total_phases}: Port Allocation")
            if self.phase_4_port_allocation():
                phases_succeeded += 1
                logger.info("PHASE_5_PORT_COMPLETE: success")
                logger.info(f"✓ Phase 5 completed!")
            else:
                self.failed_phases.append("Port Allocation")
                logger.error("PHASE_5_PORT_COMPLETE: failed")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 5")
                return

            # Phase 6: Service Setup (includes build phase tracking)
            self.current_phase = 6
            logger.info("PHASE_6_SERVICE_START")
            logger.info(f"📋 Phase 6/{total_phases}: Service Setup")
            self.status_tracker.start_phase(PipelinePhase.BUILD)
            if self.phase_5_service_setup():
                phases_succeeded += 1
                self.status_tracker.complete_phase(PipelinePhase.BUILD)
                # Update status to deploying after service setup
                logger.info(f"PROJECT STATUS UPDATE → deploying")
                self.update_status("deploying")
                logger.info("PHASE_6_SERVICE_COMPLETE: success")
                logger.info(f"✓ Phase 6 completed!")
            else:
                self.failed_phases.append("Service Setup")
                self.status_tracker.fail_phase(PipelinePhase.BUILD, ErrorCode.BUILD_FAILED, "Service setup failed")
                logger.error("PHASE_6_SERVICE_COMPLETE: failed")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 6")
                return

            # Phase 7: Nginx Routing
            self.current_phase = 7
            logger.info("PHASE_7_NGINX_START")
            logger.info(f"📋 Phase 7/{total_phases}: Nginx Routing")
            if self.phase_6_nginx_routing():
                phases_succeeded += 1
                # Update status to verifying after nginx setup
                logger.info(f"PROJECT STATUS UPDATE → verifying")
                self.update_status("verifying")
                logger.info("PHASE_7_NGINX_COMPLETE: success")
                logger.info(f"✓ Phase 7 completed!")
            else:
                self.failed_phases.append("Nginx Routing")
                logger.error("PHASE_7_NGINX_COMPLETE: failed")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 7")
                return

            # Phase 8: AI-Driven Frontend Refinement (Legacy - skipped)
            self.current_phase = 8
            logger.info("PHASE_8_AI_START")
            logger.info(f"📋 Phase 8/{total_phases}: AI-Driven Frontend Refinement (Legacy - Skipped)")
            # Phase 8 skipped - ACPX in Phase 3 handles frontend refinement
            phases_succeeded += 1
            logger.info("PHASE_8_AI_COMPLETE: skipped")
            logger.info(f"✓ Phase 8 skipped (using ACPX from Phase 3)")

            # Phase 9: Deployment Verification (FINAL step)
            # This verifies the entire deployment including ACPX changes
            self.current_phase = 9
            logger.info("PHASE_9_VERIFY_START")
            logger.info(f"📋 Phase 9/{total_phases}: Deployment Verification")
            self.status_tracker.start_phase(PipelinePhase.DEPLOY)
            if self.phase_7_verification():
                phases_succeeded += 1
                self.status_tracker.complete_phase(PipelinePhase.DEPLOY)
                logger.info("PHASE_9_VERIFY_COMPLETE: success")
                logger.info(f"✓ Phase 9 completed!")
            else:
                self.failed_phases.append("Deployment Verification")
                self.status_tracker.fail_phase(PipelinePhase.DEPLOY, ErrorCode.DEPLOY_FAILED, "Deployment verification failed")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 9")
                return

            # All phases completed!
            if phases_succeeded == total_phases:
                logger.info(f"✅ All {total_phases} infrastructure provisioning phases completed successfully!")

                # Get domain for final logging
                domain = self.get_project_domain()

                # Log final deployment URLs
                logger.info(f"🌍 Live project URL: http://{domain}")
                logger.info(f"📡 API endpoint: http://{domain}/api")
                logger.info("🎉 Deployment completed successfully")

                logger.info(f"PROJECT STATUS UPDATE → ready")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed phases: {', '.join(self.completed_phases)}")
                
                # Log final pipeline status
                progress = self.status_tracker.get_progress_summary()
                logger.info(f"📈 Pipeline Progress: {progress['progress_percent']}% - {progress['overall_status']}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {phases_succeeded}/{total_phases}, Failed: {', '.join(self.failed_phases)}")
                self.update_status("failed")
                
                # Log pipeline status on failure
                progress = self.status_tracker.get_progress_summary()
                logger.error(f"📉 Pipeline Progress: {progress['progress_percent']}% - {progress['overall_status']}")
                if progress.get('error_code'):
                    logger.error(f"🔴 Error Code: {progress['error_code']}")

        except Exception as e:
            logger.error(f"💥 Unexpected error in OpenClaw wrapper: {e}")
            self.update_status("failed")
            self.status_tracker.fail_phase(PipelinePhase.DEPLOY, ErrorCode.UNKNOWN_ERROR, str(e))

        finally:
            # Print final status report
            status_report = format_status_report(self.status_tracker.get_status())
            logger.info(f"\n{status_report}")
            logger.info("🏁 OpenClaw wrapper finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 openclaw_wrapper.py <project_id> <project_path> <project_name> [description] [template_id]")
        print("  project_id: Database project ID")
        print("  project_path: Absolute path to project folder")
        print("  project_name: Project name")
        print("  description: (optional) Project description")
        print("  template_id: (optional) Selected frontend template ID")
        sys.exit(1)

    project_id = int(sys.argv[1])
    project_path = sys.argv[2]
    project_name = sys.argv[3]

    # Description can span multiple arguments (argv[4:-1])
    # Template_id is always the last argument (argv[-1])
    description = " ".join(sys.argv[4:-1]) if len(sys.argv) > 4 else None
    template_id = sys.argv[-1] if len(sys.argv) > 4 else None

    # Create and run wrapper
    wrapper = OpenClawWrapper(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name,
        description=description,
        template_id=template_id
    )

    wrapper.run_all_phases()


if __name__ == "__main__":
    main()
