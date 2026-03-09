#!/usr/bin/env python3
"""
Frontend Optimizer - Rule-Based Branding for DreamPilot

Fast, deterministic branding that works across all templates.
Runs before AI refinement in Phase 9 to ensure guaranteed branding.
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FrontendOptimizer:
    """
    Rule-based frontend optimizer for guaranteed template branding.

    Detects template structure and applies consistent branding
    across all templates (saas, finance, ecommerce, etc.)
    """

    def __init__(self, frontend_path: str, project_name: str, description: str):
        """
        Initialize optimizer.

        Args:
            frontend_path: Absolute path to frontend directory
            project_name: Project name for branding
            description: Project description for meta tags
        """
        self.frontend_path = Path(frontend_path).resolve()
        self.project_name = project_name
        self.description = description
        self.changes = []

        logger.info(f"Frontend Optimizer initialized")
        logger.info(f"  Frontend path: {self.frontend_path}")
        logger.info(f"  Project name: {project_name}")
        logger.info(f"  Description: {description[:100]}...")

    def run(self) -> Dict[str, any]:
        """
        Execute full optimization pipeline.

        Returns:
            Dict with success status and changes made
        """
        logger.info("🔧 Starting Frontend Optimizer...")

        try:
            # Step 1: Optimize index.html
            self._optimize_index_html()

            # Step 2: Optimize main page
            self._optimize_main_page()

            # Step 3: Optimize sidebar
            self._optimize_sidebar()

            # Step 4: Optimize metadata files
            self._optimize_metadata()

            logger.info(f"✅ Frontend Optimizer complete: {len(self.changes)} files modified")
            return {
                "success": True,
                "changes": self.changes,
                "files_modified": len(self.changes)
            }

        except Exception as e:
            logger.error(f"❌ Frontend Optimizer failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "changes": self.changes
            }

    def _optimize_index_html(self):
        """Update index.html title and meta tags."""
        index_file = self.frontend_path / "index.html"
        if not index_file.exists():
            logger.debug("  index.html not found - skipping")
            return

        logger.info(f"  Optimizing index.html...")

        with open(index_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Title replacements
        title_replacements = [
            (r'<title>Lovable App</title>', f'<title>{self.project_name}</title>'),
            (r'<title>.*?</title>', f'<title>{self.project_name}</title>'),
        ]

        for pattern, replacement in title_replacements:
            if re.search(pattern, content, re.IGNORECASE):
                content = re.sub(pattern, replacement, content, flags=re.IGNORECASE)
                logger.debug(f"    Replaced title pattern: {pattern}")

        # Meta description
        meta_desc_pattern = r'<meta name="description" content=".*?"/>'
        if re.search(meta_desc_pattern, content):
            content = re.sub(
                meta_desc_pattern,
                f'<meta name="description" content="{self.description[:160]}" />',
                content
            )
            logger.debug(f"    Updated meta description")

        # OG title
        og_title_pattern = r'<meta property="og:title" content=".*?"/>'
        if re.search(og_title_pattern, content):
            content = re.sub(
                og_title_pattern,
                f'<meta property="og:title" content="{self.project_name}" />',
                content
            )
            logger.debug(f"    Updated og:title")

        # Twitter meta
        twitter_title_pattern = r'<meta name="twitter:title" content=".*?"/>'
        if re.search(twitter_title_pattern, content):
            content = re.sub(
                twitter_title_pattern,
                f'<meta name="twitter:title" content="{self.project_name}" />',
                content
            )
            logger.debug(f"    Updated twitter:title")

        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(content)

        self.changes.append(str(index_file.relative_to(self.frontend_path.parent)))
        logger.info(f"  ✅ index.html optimized")

    def _optimize_main_page(self):
        """Find and optimize main dashboard page."""
        src_path = self.frontend_path / "src"

        # Common main page locations
        main_page_patterns = [
            src_path / "pages" / "Dashboard.tsx",
            src_path / "pages" / "Home.tsx",
            src_path / "pages" / "Index.tsx",
            src_path / "app" / "page.tsx",
        ]

        main_page = None
        for pattern in main_page_patterns:
            if pattern.exists():
                main_page = pattern
                break

        if not main_page:
            logger.debug("  Main page not found - skipping")
            return

        logger.info(f"  Optimizing main page: {main_page.name}...")

        with open(main_page, 'r', encoding='utf-8') as f:
            content = f.read()

        # Hero title replacements
        hero_patterns = [
            (r'<h1[^>]*>Dashboard</h1>', f'<h1>{self.project_name}</h1>'),
            (r'<h1[^>]*>.*?Dashboard.*?</h1>', f'<h1>{self.project_name}</h1>'),
        ]

        for pattern, replacement in hero_patterns:
            if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
                content = re.sub(pattern, replacement, content, flags=re.IGNORECASE | re.DOTALL)
                logger.debug(f"    Replaced hero title pattern")

        # Subtitle/description replacements
        subtitle_patterns = [
            (r'<p[^>]*>Overview of your financial health</p>', f'<p>{self.description[:100]}</p>'),
            (r'<p[^>]*class="[^"]*text-muted-foreground[^"]*"[^>]*>.*?</p>', f'<p class="text-muted-foreground">{self.description[:100]}</p>'),
        ]

        for pattern, replacement in subtitle_patterns:
            if re.search(pattern, content, re.IGNORECASE | re.DOTALL):
                content = re.sub(pattern, replacement, content, flags=re.IGNORECASE | re.DOTALL)
                logger.debug(f"    Replaced subtitle pattern")

        with open(main_page, 'w', encoding='utf-8') as f:
            f.write(content)

        self.changes.append(str(main_page.relative_to(self.frontend_path.parent)))
        logger.info(f"  ✅ Main page optimized")

    def _optimize_sidebar(self):
        """Find and optimize sidebar components."""
        src_path = self.frontend_path / "src"

        # Common sidebar locations
        sidebar_patterns = [
            src_path / "layouts" / "FloatingSidebar.tsx",
            src_path / "layouts" / "Sidebar.tsx",
            src_path / "components" / "Sidebar.tsx",
            src_path / "components" / "Navigation.tsx",
        ]

        for sidebar_path in sidebar_patterns:
            if not sidebar_path.exists():
                continue

            logger.info(f"  Optimizing sidebar: {sidebar_path.name}...")

            with open(sidebar_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Brand name replacements
            brand_patterns = [
                (r'>Finance</', f'>{self.project_name}</'),
                (r'>Lovable App</', f'>{self.project_name}</'),
                (r'>SaaS</', f'>{self.project_name}</'),
            ]

            for pattern, replacement in brand_patterns:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    logger.debug(f"    Replaced brand pattern: {pattern}")

            # Logo icon replacements (customize based on project)
            logo_patterns = [
                (r'className="[^"]*font-bold[^"]*"[^>]*>F</span>', f'className="font-bold">{self._get_logo_icon()}</span>'),
                (r'className="[^"]*font-bold[^"]*"[^>]*>S</span>', f'className="font-bold">{self._get_logo_icon()}</span>'),
            ]

            for pattern, replacement in logo_patterns:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    logger.debug(f"    Replaced logo icon")

            with open(sidebar_path, 'w', encoding='utf-8') as f:
                f.write(content)

            self.changes.append(str(sidebar_path.relative_to(self.frontend_path.parent)))
            logger.info(f"  ✅ Sidebar optimized")

    def _optimize_metadata(self):
        """Optimize metadata/config files."""
        src_path = self.frontend_path / "src"

        # Common metadata locations
        meta_patterns = [
            src_path / "lib" / "meta.ts",
            src_path / "lib" / "site.ts",
            src_path / "config" / "site.ts",
            src_path / "constants" / "app.ts",
        ]

        for meta_path in meta_patterns:
            if not meta_path.exists():
                continue

            logger.info(f"  Optimizing metadata: {meta_path.name}...")

            with open(meta_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Look for common patterns
            patterns_to_replace = [
                (r'name:\s*".*?"', f'name: "{self.project_name}"'),
                (r'title:\s*".*?"', f'title: "{self.project_name}"'),
                (r'description:\s*".*?"', f'description: "{self.description[:160]}"'),
            ]

            modified = False
            for pattern, replacement in patterns_to_replace:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    modified = True
                    logger.debug(f"    Replaced metadata pattern")

            if modified:
                with open(meta_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                self.changes.append(str(meta_path.relative_to(self.frontend_path.parent)))
                logger.info(f"  ✅ Metadata optimized")

    def _get_logo_icon(self) -> str:
        """Get appropriate logo icon based on project name."""
        name_lower = self.project_name.lower()

        # Crypto projects
        if any(word in name_lower for word in ['crypto', 'bitcoin', 'ethereum', 'blockchain', 'defi']):
            return '₿'

        # Finance projects
        if any(word in name_lower for word in ['finance', 'bank', 'money', 'payment', 'cash']):
            return '💰'

        # E-commerce projects
        if any(word in name_lower for word in ['shop', 'store', 'market', 'cart', 'ecommerce']):
            return '🛒'

        # SaaS projects
        if any(word in name_lower for word in ['saas', 'dashboard', 'platform', 'app']):
            return '⚡'

        # Analytics projects
        if any(word in name_lower for word in ['analytics', 'insights', 'data', 'metrics']):
            return '📊'

        # Default: first letter
        return self.project_name[0].upper()


def main():
    """CLI entry point for testing."""
    import sys

    if len(sys.argv) < 4:
        print("Usage: python3 frontend_optimizer.py <frontend_path> <project_name> <description>")
        sys.exit(1)

    frontend_path = sys.argv[1]
    project_name = sys.argv[2]
    description = sys.argv[3]

    optimizer = FrontendOptimizer(frontend_path, project_name, description)
    result = optimizer.run()

    if result["success"]:
        print(f"\n✅ Frontend Optimizer completed successfully!")
        print(f"   Files modified: {result['files_modified']}")
        print(f"   Changes: {', '.join(result['changes'])}")
        sys.exit(0)
    else:
        print(f"\n❌ Frontend Optimizer failed: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
