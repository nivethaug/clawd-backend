"""
Frontend Optimizer - Post-Provisioning Cleanup & Customization

Executes Phase 10: Frontend Optimization & Personalization
Runs AFTER infrastructure provisioning completes, BEFORE status = "ready"

ONLY applies to project_type == "website"
"""

import json
import subprocess
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class FrontendOptimizer:
    """Handles frontend cleanup and customization after provisioning."""

    # Common demo/content pages to remove
    DEMO_PAGES = [
        "blog", "documentation", "demo", "examples", "samples", "showcase",
        "pricing-demo", "features-demo", "test", "testing"
    ]

    # Common demo assets to remove
    DEMO_ASSETS = [
        "demo-images", "sample-data", "mock-data", "placeholder-images"
    ]

    # Protected pages (never remove)
    PROTECTED_PAGES = {
        "home", "index", "dashboard", "login", "signup", "register",
        "profile", "settings", "logout", "about", "contact"
    }

    def __init__(
        self,
        project_id: int,
        project_path: Path,
        project_name: str,
        description: str,
        template_id: str
    ):
        """Initialize frontend optimizer.

        Args:
            project_id: Database project ID
            project_path: Absolute path to project folder
            project_name: Project name
            description: Project description
            template_id: Template ID (e.g., "finance", "crm")
        """
        self.project_id = project_id
        self.project_path = project_path
        self.project_name = project_name
        self.description = description
        self.template_id = template_id
        self.frontend_path = project_path / "frontend"

        # Track changes
        self.pages_removed: List[str] = []
        self.pages_modified: List[str] = []
        self.pages_added: List[str] = []
        self.assets_cleaned: List[str] = []

        # Build analysis
        self.industry_type = self._analyze_industry()
        self.required_pages = self._determine_required_pages()

    def _analyze_industry(self) -> str:
        """Analyze project description to determine industry type.

        Returns:
            Industry category (e.g., "finance", "crm", "saas", "generic")
        """
        desc_lower = self.description.lower()
        name_lower = self.project_name.lower()

        # Finance/Trading
        finance_keywords = ["crypto", "forex", "stocks", "trading", "finance",
                          "invest", "portfolio", "market", "exchange"]
        if any(kw in desc_lower or kw in name_lower for kw in finance_keywords):
            return "finance"

        # CRM/Sales
        crm_keywords = ["crm", "customer", "lead", "pipeline", "deal",
                       "sales", "contact", "opportunity"]
        if any(kw in desc_lower or kw in name_lower for kw in crm_keywords):
            return "crm"

        # Analytics
        analytics_keywords = ["analytics", "dashboard", "report", "metrics",
                          "kpi", "insight", "data", "chart"]
        if any(kw in desc_lower or kw in name_lower for kw in analytics_keywords):
            return "analytics"

        # SaaS/General
        saas_keywords = ["saas", "platform", "app", "management",
                       "admin", "portal", "hub"]
        if any(kw in desc_lower or kw in name_lower for kw in saas_keywords):
            return "saas"

        # Default
        return "generic"

    def _determine_required_pages(self) -> Set[str]:
        """Determine which pages are required based on project description.

        Returns:
            Set of required page names (lowercase)
        """
        required = set()
        desc_lower = self.description.lower()

        # Core pages (always needed)
        required.add("home")
        required.add("dashboard")

        # Industry-specific pages
        if self.industry_type == "finance":
            required.update(["markets", "portfolio", "trades", "wallet"])

        elif self.industry_type == "crm":
            required.update(["leads", "contacts", "deals", "pipeline"])

        elif self.industry_type == "analytics":
            required.update(["reports", "metrics", "charts"])

        elif self.industry_type == "saas":
            required.update(["users", "settings", "activity"])

        # Check description for explicit page requirements
        if "login" in desc_lower or "auth" in desc_lower:
            required.add("login")
        if "signup" in desc_lower or "register" in desc_lower:
            required.add("signup")
        if "profile" in desc_lower:
            required.add("profile")

        return required

    def step_1_analyze_project_context(self) -> bool:
        """STEP 1: Analyze project context.

        Returns:
            True if analysis successful
        """
        try:
            logger.info(f"📋 STEP 1/7: Analyze project context")
            logger.info(f"  Project name: {self.project_name}")
            logger.info(f"  Description: {self.description}")
            logger.info(f"  Template ID: {self.template_id}")
            logger.info(f"  Industry type: {self.industry_type}")
            logger.info(f"  Required pages: {', '.join(sorted(self.required_pages))}")

            # Verify frontend exists
            if not self.frontend_path.exists():
                logger.error(f"❌ Frontend directory not found: {self.frontend_path}")
                return False

            # Check for package.json
            package_json = self.frontend_path / "package.json"
            if not package_json.exists():
                logger.error(f"❌ package.json not found: {package_json}")
                return False

            logger.info(f"✓ Frontend analysis complete")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to analyze project context: {e}")
            return False

    def step_2_remove_unwanted_pages(self) -> bool:
        """STEP 2: Remove unwanted demo pages and components.

        Returns:
            True if removal successful
        """
        try:
            logger.info(f"📋 STEP 2/7: Remove unwanted pages")

            # Find all route/page files
            pages_removed_count = 0

            # Common locations for React/Vite pages
            search_paths = [
                self.frontend_path / "src" / "pages",
                self.frontend_path / "src" / "views",
                self.frontend_path / "src",
            ]

            for search_path in search_paths:
                if not search_path.exists():
                    continue

                for file_path in search_path.rglob("*"):
                    if not file_path.is_file():
                        continue

                    file_name = file_path.stem.lower()

                    # Skip protected pages
                    if file_name in self.PROTECTED_PAGES:
                        continue

                    # Check if it's a demo page
                    if any(demo in file_name for demo in self.DEMO_PAGES):
                        logger.info(f"  Removing demo page: {file_path.name}")
                        file_path.unlink()
                        self.pages_removed.append(str(file_path.relative_to(self.frontend_path)))
                        pages_removed_count += 1

                    # Check if it's a page not in required list
                    elif file_name in self.required_pages:
                        logger.debug(f"  Keeping required page: {file_path.name}")
                    elif file_name not in self.required_pages:
                        # For non-demo pages, only remove if clearly unwanted
                        if any(unwanted in file_name for unwanted in ["demo", "test", "example", "sample"]):
                            logger.info(f"  Removing unwanted page: {file_path.name}")
                            file_path.unlink()
                            self.pages_removed.append(str(file_path.relative_to(self.frontend_path)))
                            pages_removed_count += 1

            logger.info(f"✓ Removed {pages_removed_count} demo/unwanted pages")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to remove unwanted pages: {e}")
            return False

    def step_3_modify_existing_pages(self) -> bool:
        """STEP 3: Modify existing pages with project branding.

        Returns:
            True if modifications successful
        """
        try:
            logger.info(f"📋 STEP 3/7: Modify existing pages with branding")

            # Files to update with branding
            brandable_files = [
                "index.html",
                "App.tsx", "App.jsx",
                "main.tsx", "main.jsx",
                "package.json",
                "README.md",
                ".env.example"
            ]

            modifications_count = 0

            for file_name in brandable_files:
                file_path = self.frontend_path / file_name
                if not file_path.exists():
                    continue

                try:
                    content = file_path.read_text()
                    original_content = content

                    # Update branding placeholders
                    content = re.sub(
                        r"FinFlow|SaaS Template|Template App|Demo App",
                        self.project_name,
                        content,
                        flags=re.IGNORECASE
                    )

                    # Update meta title
                    if file_name in ["index.html", "App.tsx", "App.jsx", "main.tsx", "main.jsx"]:
                        content = re.sub(
                            r"<title>.*?</title>",
                            f"<title>{self.project_name}</title>",
                            content
                        )

                    # Update package.json name
                    if file_name == "package.json":
                        try:
                            package_data = json.loads(content)
                            package_data["name"] = self.project_name.lower().replace(" ", "-")
                            package_data["description"] = self.description
                            content = json.dumps(package_data, indent=2)
                        except json.JSONDecodeError:
                            pass

                    # Update README
                    if file_name == "README.md":
                        content = f"# {self.project_name}\n\n{self.description}\n\n"
                        content += f"Frontend template: {self.template_id}\n\n"
                        content += "## Setup\n\n"
                        content += "```bash\nnpm install\nnpm run build\nnpm run dev\n```\n"

                    # Write back if changed
                    if content != original_content:
                        file_path.write_text(content)
                        logger.info(f"  Updated branding in: {file_name}")
                        self.pages_modified.append(file_name)
                        modifications_count += 1

                except Exception as e:
                    logger.warning(f"  Failed to update {file_name}: {e}")
                    continue

            logger.info(f"✓ Modified {modifications_count} files with branding")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to modify existing pages: {e}")
            return False

    def step_4_add_minimal_required_page(self) -> bool:
        """STEP 4: Add minimal required page (if clearly needed).

        Returns:
            True if successful (even if no pages added)
        """
        try:
            logger.info(f"📋 STEP 4/7: Add minimal required pages (if needed)")

            # Check if dashboard exists (critical page)
            dashboard_paths = [
                self.frontend_path / "src" / "pages" / "Dashboard.tsx",
                self.frontend_path / "src" / "pages" / "Dashboard.jsx",
                self.frontend_path / "src" / "views" / "Dashboard.tsx",
                self.frontend_path / "src" / "views" / "Dashboard.jsx",
                self.frontend_path / "src" / "Dashboard.tsx",
                self.frontend_path / "src" / "Dashboard.jsx",
            ]

            dashboard_exists = any(p.exists() for p in dashboard_paths)

            if not dashboard_exists and "dashboard" in self.required_pages:
                # Create minimal dashboard
                pages_dir = self.frontend_path / "src" / "pages"
                pages_dir.mkdir(parents=True, exist_ok=True)

                dashboard_file = pages_dir / "Dashboard.tsx"
                dashboard_content = f"""import React from 'react';

const Dashboard: React.FC = () => {{
  return (
    <div className="dashboard">
      <h1>Welcome to {self.project_name}</h1>
      <p>{self.description}</p>
      <div className="dashboard-content">
        {{/* Dashboard content */}}
      </div>
    </div>
  );
}};

export default Dashboard;
"""

                dashboard_file.write_text(dashboard_content)
                self.pages_added.append("Dashboard.tsx")
                logger.info(f"  Added minimal dashboard page")

            else:
                logger.info(f"  No new pages needed (dashboard exists)")

            logger.info(f"✓ Required pages check complete")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to add required page: {e}")
            return False

    def step_5_clean_package(self) -> bool:
        """STEP 5: Clean package and demo assets.

        Returns:
            True if cleanup successful
        """
        try:
            logger.info(f"📋 STEP 5/7: Clean package and demo assets")

            assets_removed_count = 0

            # Remove demo asset directories
            for demo_asset in self.DEMO_ASSETS:
                demo_path = self.frontend_path / demo_asset
                if demo_path.exists() and demo_path.is_dir():
                    import shutil
                    shutil.rmtree(demo_path)
                    logger.info(f"  Removed demo assets: {demo_asset}")
                    self.assets_cleaned.append(demo_asset)
                    assets_removed_count += 1

            # Remove demo images in public/
            public_path = self.frontend_path / "public"
            if public_path.exists():
                for item in public_path.iterdir():
                    if item.is_file():
                        item_lower = item.name.lower()
                        if any(demo in item_lower for demo in ["demo", "sample", "test", "placeholder"]):
                            item.unlink()
                            logger.info(f"  Removed demo image: {item.name}")
                            self.assets_cleaned.append(f"public/{item.name}")
                            assets_removed_count += 1

            logger.info(f"✓ Removed {assets_removed_count} demo assets")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to clean package: {e}")
            return False

    def step_6_verify_build(self) -> bool:
        """STEP 6: Verify build succeeds.

        Returns:
            True if build successful
        """
        try:
            logger.info(f"📋 STEP 6/7: Verify build")

            # Run npm run build
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=self.frontend_path,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes
            )

            if result.returncode == 0:
                logger.info(f"✓ Build successful")
                logger.info(f"  Output: {result.stdout[-500:]}")
                return True
            else:
                logger.error(f"❌ Build failed with code: {result.returncode}")
                logger.error(f"  Error: {result.stderr[-1000:]}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Build timed out after 5 minutes")
            return False
        except Exception as e:
            logger.error(f"❌ Build verification failed: {e}")
            return False

    def step_7_logging(self) -> bool:
        """STEP 7: Log all changes.

        Returns:
            Always True
        """
        try:
            logger.info(f"📋 STEP 7/7: Logging optimization results")
            logger.info(f"=" * 60)
            logger.info(f"FRONTEND OPTIMIZATION COMPLETE - Project {self.project_id}")
            logger.info(f"=" * 60)
            logger.info(f"Pages removed ({len(self.pages_removed)}):")
            for page in self.pages_removed:
                logger.info(f"  - {page}")
            logger.info(f"")
            logger.info(f"Pages modified ({len(self.pages_modified)}):")
            for page in self.pages_modified:
                logger.info(f"  - {page}")
            logger.info(f"")
            logger.info(f"Pages added ({len(self.pages_added)}):")
            for page in self.pages_added:
                logger.info(f"  - {page}")
            logger.info(f"")
            logger.info(f"Assets cleaned ({len(self.assets_cleaned)}):")
            for asset in self.assets_cleaned:
                logger.info(f"  - {asset}")
            logger.info(f"")
            logger.info(f"Branding updated:")
            logger.info(f"  - Name: {self.project_name}")
            logger.info(f"  - Description: {self.description}")
            logger.info(f"  - Industry: {self.industry_type}")
            logger.info(f"=" * 60)

            return True

        except Exception as e:
            logger.error(f"❌ Failed to log optimization results: {e}")
            return True  # Don't fail on logging errors

    def run_optimization(self) -> bool:
        """Run all optimization steps in order.

        Returns:
            True if all steps successful
        """
        try:
            logger.info(f"🚀 Starting frontend optimization for project {self.project_id}")
            logger.info(f"📁 Frontend path: {self.frontend_path}")

            # Step 1: Analyze
            if not self.step_1_analyze_project_context():
                return False

            # Step 2: Remove unwanted pages
            if not self.step_2_remove_unwanted_pages():
                return False

            # Step 3: Modify existing pages
            if not self.step_3_modify_existing_pages():
                return False

            # Step 4: Add required pages
            if not self.step_4_add_minimal_required_page():
                return False

            # Step 5: Clean package
            if not self.step_5_clean_package():
                return False

            # Step 6: Verify build
            if not self.step_6_verify_build():
                return False

            # Step 7: Log results
            self.step_7_logging()

            logger.info(f"✅ Frontend optimization completed successfully!")
            return True

        except Exception as e:
            logger.error(f"💥 Frontend optimization failed: {e}")
            return False

    def restart_pm2_service(self, service_name: str) -> bool:
        """Restart PM2 frontend service after optimization.

        Args:
            service_name: PM2 service name (e.g., "myproject-frontend")

        Returns:
            True if restart successful
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
