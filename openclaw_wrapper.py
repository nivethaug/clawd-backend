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

import sys
import json
import logging
import os
import subprocess
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database configuration
USE_POSTGRES = os.getenv("USE_POSTGRES", "true").lower() == "true"
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"

# PostgreSQL imports
if USE_POSTGRES:
    import psycopg2
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = os.getenv("DB_PORT", "5432")
    DB_NAME = os.getenv("DB_NAME", "dreampilot")
    DB_USER = os.getenv("DB_USER", "admin")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "StrongAdminPass123")

# Rules files
RULES_DIR = Path("/root/dreampilot/website")
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
        self.project_name = project_name
        self.description = description or ""
        self.template_id = template_id
        self.completed_phases = []
        self.failed_phases = []

    def update_status(self, status: str):
        """Update project status in database."""
        try:
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

        # Template already selected via Groq in app.py
        # This phase is just confirmation
        logger.info(f"✓ Project analysis complete")
        logger.info(f"✓ Project name: {self.project_name}")
        logger.info(f"✓ Description: {self.description}")
        logger.info(f"✓ Template: already selected via Groq API")

        self.completed_phases.append("Analyze Project")
        return True

    def phase_2_template_setup(self) -> bool:
        """
        Phase 2: Template Setup

        - Frontend already cloned via fast_wrapper
        - Backend files already created
        - This phase just verifies completion
        """
        logger.info("📋 Phase 2/8: Template Setup")

        # Verify frontend exists
        frontend_path = self.project_path / "frontend"
        if not frontend_path.exists():
            logger.error("❌ Frontend directory not found")
            return False

        # Verify backend exists
        backend_path = self.project_path / "backend"
        if not backend_path.exists():
            logger.error("❌ Backend directory not found")
            return False

        logger.info("✓ Template setup complete")
        logger.info(f"✓ Frontend exists: {frontend_path}")
        logger.info(f"✓ Backend exists: {backend_path}")

        self.completed_phases.append("Template Setup")
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

        - Use OpenClaw AI to intelligently refine frontend source code
        - AI analyzes actual source code structure
        - AI understands project intent from name + description
        - AI removes irrelevant demo/sample content contextually
        - AI modifies existing pages to match real project vision
        - AI adjusts navigation based on implied features
        - AI rewrites homepage hero section to match project
        - AI ensures UI terminology reflects project domain

        ONLY applies to website projects (type_id = 1)
        """
        logger.info("📋 Phase 8/8: AI-Driven Frontend Refinement")

        try:
            # Check if this is a website project (type_id = 1)
            project_type_id = self._get_project_type_id()

            if project_type_id != 1:
                logger.info("✓ Skipping AI frontend refinement (not a website project)")
                logger.info(f"  Project type_id: {project_type_id}")
                self.completed_phases.append("AI Frontend Refinement (Skipped)")
                return True

            # Build AI refinement prompt
            refinement_prompt = self._build_ai_refinement_prompt()

            # Update status to indicate AI refinement is in progress
            self.update_status("ai_provisioning")
            logger.info(f"🔄 Project {self.project_id} status updated to 'ai_provisioning'")

            logger.info(f"🤖 Triggering OpenClaw AI frontend refinement")
            logger.info(f"  Frontend path: {self.frontend_path}")
            logger.info(f"  Project name: {self.project_name}")
            logger.info(f"  Template ID: {self.template_id}")

            # Run OpenClaw AI refinement
            # Working directory: /root/dreampilot/projects/website/{project-name}
            # OpenClaw will modify files inside: frontend/
            result = subprocess.run(
                ["openclaw", "agent",
                 "--local",
                 "--message", refinement_prompt,
                 "--timeout", "1800"],
                cwd=str(self.frontend_path),
                capture_output=True,
                text=True,
                timeout=1860  # 31 minutes max (30 + 1 for buffer)
            )

            # Check result
            if result.returncode != 0:
                logger.error(f"❌ OpenClaw AI refinement failed with code: {result.returncode}")
                logger.error(f"  Error output: {result.stderr[-1000:]}")
                self.update_status("failed")
                logger.info(f"✓ Project {self.project_id} status updated to 'failed'")
                return False

            logger.info(f"✓ OpenClaw AI refinement completed")
            logger.info(f"  Output: {result.stdout[-500:]}")

            # Step 1: Verify build succeeds
            logger.info(f"🔍 Verifying build after AI refinement...")
            build_success = self._verify_frontend_build()

            if not build_success:
                logger.error(f"❌ Build failed after AI refinement")
                self.update_status("failed")
                logger.info(f"✓ Project {self.project_id} status updated to 'failed'")
                return False

            logger.info(f"✓ Build verification successful")

            # Step 2: Restart PM2 frontend service
            service_name = f"{self.project_name.lower().replace(' ', '-')}-frontend"
            if self._restart_pm2_service(service_name):
                logger.info("✓ PM2 frontend service restarted")
            else:
                logger.warning("⚠️ PM2 frontend service restart failed, continuing...")

            self.completed_phases.append("AI Frontend Refinement")
            logger.info("✓ AI-driven frontend refinement completed successfully")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"❌ OpenClaw AI refinement timed out after 30 minutes")
            self.update_status("failed")
            logger.info(f"✓ Project {self.project_id} status updated to 'failed'")
            return False
        except Exception as e:
            logger.error(f"❌ AI frontend refinement failed: {e}")
            logger.error(f"❌ Exception type: {type(e).__name__}")
            logger.error(f"❌ Exception details: {str(e)}", exc_info=True)
            self.update_status("failed")
            logger.info(f"✓ Project {self.project_id} status updated to 'failed'")
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

        Returns:
            True if build successful, False otherwise
        """
        try:
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=self.frontend_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )

            if result.returncode == 0:
                logger.info(f"✓ Frontend build successful")
                return True
            else:
                logger.error(f"❌ Frontend build failed with code: {result.returncode}")
                logger.error(f"  Error: {result.stderr[-1000:]}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Frontend build timed out after 5 minutes")
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
        """Execute all 7 phases in order."""
        try:
            logger.info(f"🚀 Starting OpenClaw infrastructure provisioning for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")

            total_phases = 8
            phases_succeeded = 0

            # Phase 1: Analyze Project
            logger.info(f"📋 Phase 1/{total_phases}: Analyze Project")
            if self.phase_1_analyze_project():
                phases_succeeded += 1
                logger.info(f"✓ Phase 1 completed!")
            else:
                self.failed_phases.append("Analyze Project")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 1")
                return

            # Phase 2: Template Setup
            logger.info(f"📋 Phase 2/{total_phases}: Template Setup")
            if self.phase_2_template_setup():
                phases_succeeded += 1
                logger.info(f"✓ Phase 2 completed!")
            else:
                self.failed_phases.append("Template Setup")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 2")
                return

            # Phase 3: Database Provisioning
            logger.info(f"📋 Phase 3/{total_phases}: Database Provisioning")
            if self.phase_3_database_provisioning():
                phases_succeeded += 1
                logger.info(f"✓ Phase 3 completed!")
            else:
                self.failed_phases.append("Database Provisioning")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 3")
                return

            # Phase 4: Port Allocation
            logger.info(f"📋 Phase 4/{total_phases}: Port Allocation")
            if self.phase_4_port_allocation():
                phases_succeeded += 1
                logger.info(f"✓ Phase 4 completed!")
            else:
                self.failed_phases.append("Port Allocation")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 4")
                return

            # Phase 5: Service Setup
            logger.info(f"📋 Phase 5/{total_phases}: Service Setup")
            if self.phase_5_service_setup():
                phases_succeeded += 1
                logger.info(f"✓ Phase 5 completed!")
            else:
                self.failed_phases.append("Service Setup")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 5")
                return

            # Phase 6: Nginx Routing
            logger.info(f"📋 Phase 6/{total_phases}: Nginx Routing")
            if self.phase_6_nginx_routing():
                phases_succeeded += 1
                logger.info(f"✓ Phase 6 completed!")
            else:
                self.failed_phases.append("Nginx Routing")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 6")
                return

            # Phase 7: Verification
            logger.info(f"📋 Phase 7/{total_phases}: Verification")
            if self.phase_7_verification():
                phases_succeeded += 1
                logger.info(f"✓ Phase 7 completed!")
            else:
                self.failed_phases.append("Verification")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 7")
                return

            # Phase 8: AI-Driven Frontend Refinement
            logger.info(f"📋 Phase 8/{total_phases}: AI-Driven Frontend Refinement")
            if self.phase_8_frontend_ai_refinement():
                phases_succeeded += 1
                logger.info(f"✓ Phase 8 completed!")
            else:
                self.failed_phases.append("AI Frontend Refinement")
                self.update_status("failed")
                logger.error("❌ Initialization failed at phase 8")
                return

            # All phases completed!
            if phases_succeeded == 8:
                logger.info(f"✅ All {total_phases} infrastructure provisioning phases completed successfully!")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed phases: {', '.join(self.completed_phases)}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {phases_succeeded}/{total_phases}, Failed: {', '.join(self.failed_phases)}")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error in OpenClaw wrapper: {e}")
            self.update_status("failed")

        finally:
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
    description = sys.argv[4] if len(sys.argv) > 4 else None
    template_id = sys.argv[5] if len(sys.argv) > 5 else None

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
