"""
ACP Prompt Generator

Generates AI-driven file changes for ACP (Agent Client Protocol).
Replaces OpenClaw agent sessions with faster, safer approach.

Workflow:
1. Generate AI prompts via Groq LLM (2 seconds)
2. Convert prompts to ACP changes
3. Return changes for Phase 8 to apply
"""

import json
import logging
from typing import Dict, List, Any
from groq import Groq

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ACPPromptGenerator:
    """Generates ACP file changes from AI analysis."""

    def __init__(self):
        """Initialize Groq client."""
        self.groq_client = None
        self.model = "llama3-70b-8192"

    def initialize(self) -> bool:
        """Initialize Groq client."""
        try:
            self.groq_client = Groq()
            logger.info("✓ Groq client initialized")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Groq: {e}")
            return False

    def generate_changes(
        self,
        project_name: str,
        description: str,
        template_id: str
    ) -> List[Dict[str, Any]]:
        """
        Generate ACP file changes using AI analysis.

        Args:
            project_name: Project name
            description: Project description
            template_id: Selected template ID

        Returns:
            List of ACP changes (action, path, content)
        """
        try:
            logger.info("🤖 Generating AI customization prompts...")

            # Build prompt for Groq
            prompt = self._build_generation_prompt(
                project_name, description, template_id
            )

            # Call Groq API
            response = self.groq_client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": self._get_system_prompt()
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=2048
            )

            ai_response = response.choices[0].message.content
            logger.info("✓ AI analysis complete")

            # Parse AI response into ACP changes
            changes = self._parse_ai_response(ai_response)

            logger.info(f"✓ Generated {len(changes)} file changes")
            return changes

        except Exception as e:
            logger.error(f"❌ Failed to generate AI prompts: {e}")
            # Return minimal changes (just documentation)
            return self._generate_minimal_changes(project_name)

    def _get_system_prompt(self) -> str:
        """Get system prompt for AI customization."""
        return """You are an expert frontend developer who customizes React applications.

Your task is to analyze a project and generate minimal, targeted file changes to customize the frontend.

RULES:
1. Keep changes minimal - don't rewrite the entire app
2. Focus on branding and terminology (title, hero, navigation)
3. Remove obvious demo/sample content
4. DO NOT break existing functionality
5. DO NOT modify backend files
6. DO NOT modify components/ui/ (shadcn components)
7. Generate valid TypeScript/React code
8. Keep the build working

OUTPUT FORMAT:
Return a JSON object with "changes" array:
{
  "changes": [
    {
      "action": "write",
      "path": "pages/Home.tsx",
      "content": "full file content"
    }
  ]
}

IMPORTANT:
- "path" should be relative to frontend/src/
- "content" should be the complete file content
- Maximum 4 new files allowed by ACP
- Existing files can be modified without limit
"""

    def _build_generation_prompt(
        self,
        project_name: str,
        description: str,
        template_id: str
    ) -> str:
        """Build prompt for Groq API."""
        return f"""Customize this React application for production use.

PROJECT DETAILS:
- Name: {project_name}
- Description: {description}
- Template: {template_id}

ANALYSIS NEEDED:
1. What is the core purpose of this application?
2. What UI terminology should replace demo content?
3. What pages/features are most important?
4. What can be simplified or removed?

GENERATE MINIMAL CHANGES FOR:
1. Update page titles and meta tags
2. Customize hero section with real branding
3. Update navigation menu (keep it simple)
4. Remove obvious demo/sample content
5. Update any placeholder text

FILES TO MODIFY (choose 3-4 max):
- pages/Home.tsx (hero and overview)
- App.tsx (title and meta tags)
- components/Navbar.tsx (if exists)
- pages/[relevant].tsx (1-2 key pages)

Return JSON with changes array. Focus on making it feel like a real production app, not a demo."""

    def _parse_ai_response(self, ai_response: str) -> List[Dict[str, Any]]:
        """Parse AI response into ACP changes."""
        try:
            # Try to parse as JSON
            response_data = json.loads(ai_response)

            if "changes" in response_data:
                changes = response_data["changes"]
                # Validate changes
                validated = []
                for change in changes[:4]:  # Limit to 4 changes
                    if "action" in change and "path" in change and "content" in change:
                        validated.append(change)
                return validated

        except json.JSONDecodeError:
            logger.warning("⚠️ AI response not valid JSON, using minimal changes")
            pass

        # Fallback to minimal changes
        return []

    def _generate_minimal_changes(self, project_name: str) -> List[Dict[str, Any]]:
        """Generate minimal changes (just documentation)."""
        return [{
            "action": "write",
            "path": "ACP_README.md",
            "content": self._generate_acp_readme_content(project_name)
        }]

    def _generate_acp_readme_content(self, project_name: str) -> str:
        """Generate ACP README content."""
        from datetime import datetime
        return f"""# ACP Controlled Frontend Editor

This project is configured for controlled frontend refinement using ACP (Agent Client Protocol).

## About ACP

ACP is integrated directly into DreamPilot project creation workflow (Phase 8).
It provides safe, validated frontend editing with following protections:

### Safety Features
- ✅ Path validation (whitelist `frontend/src/` only)
- ✅ Forbidden paths (backend, components/ui/ protected)
- ✅ File limit (max 4 new files per execution)
- ✅ Snapshot system (backup before modifications)
- ✅ Automatic rollback (restore on validation or build failure)
- ✅ Build gate (npm run build must succeed)
- ✅ Mutation logging (full history tracked)

### Project Status
- **Project Name:** {project_name}
- **Phase 8 Completed:** {datetime.now().isoformat()}
- **ACP Frontend Editor:** ✅ Available and Ready

### How to Use ACP

ACP can be used for future frontend refinements via command line:

```bash
cd /root/clawd-backend
python3 acp_direct.py <project_id> <file_path> <content>
```

Or via API (if enabled):

```bash
POST /projects/{{project_id}}/acp/apply
Content-Type: application/json
{{
  "changes": [
    {{
      "action": "write|modify|remove",
      "path": "src/pages/NewPage.tsx",
      "content": "file content"
    }}
  ]
}}
```

---
ACP Frontend Editor: Integrated, Safe, and Ready for Production
"""


def main():
    """Test ACP prompt generator."""
    generator = ACPPromptGenerator()

    if not generator.initialize():
        print("Failed to initialize Groq client")
        return 1

    # Test with sample project
    changes = generator.generate_changes(
        project_name="Test Project",
        description="A simple SaaS dashboard for task management",
        template_id="saas"
    )

    print(f"\nGenerated {len(changes)} changes:")
    for i, change in enumerate(changes, 1):
        print(f"\n{i}. {change['action']}: {change['path']}")
        print(f"   Content length: {len(change['content'])} chars")

    return 0


if __name__ == "__main__":
    main()
