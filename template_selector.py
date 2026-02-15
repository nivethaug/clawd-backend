"""
Template Selector Service

Uses Groq LLM to select the best frontend template from the registry
based on project description and requirements.
"""

import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from groq_service import GroqService

logger = logging.getLogger(__name__)


class TemplateSelector:
    """Service for selecting templates using Groq LLM."""

    # Path to template registry
    TEMPLATE_REGISTRY_PATH = "/root/dreampilot/website/frontend/template-registry.json"

    # System prompt for template selection
    SYSTEM_PROMPT = """You are a frontend template matching expert. Given a project description, select the most suitable template from the available options.

IMPORTANT RULES:
1. Return ONLY the template ID as a single word (e.g., "finance", "crm", "saas")
2. Do NOT include any explanation, reasoning, or additional text
3. Match based on: keywords, features, and category
4. If no perfect match, choose the closest fit or use default fallback

Available templates will be provided in the user message with their:
- id: unique identifier (THIS IS WHAT YOU MUST RETURN)
- repo: GitHub repository URL
- category: template category
- keywords: relevant search terms
- features: included features"""

    def __init__(self):
        """Initialize template selector."""
        self.groq_service: Optional[GroqService] = None
        self.template_registry: Optional[Dict[str, Any]] = None
        self._initialize()

    def _initialize(self) -> None:
        """Initialize Groq service and load template registry."""
        try:
            # Initialize Groq
            self.groq_service = GroqService()
            if self.groq_service.is_configured():
                logger.info("Template selector: Groq service initialized")
            else:
                logger.warning("Template selector: Groq not configured")
                self.groq_service = None

            # Load template registry
            self.template_registry = self._load_registry()
            if self.template_registry:
                logger.info(f"Template selector: Loaded {len(self.template_registry.get('templates', []))} templates")

        except Exception as e:
            logger.error(f"Failed to initialize template selector: {e}")
            self.groq_service = None
            self.template_registry = None

    def _load_registry(self) -> Optional[Dict[str, Any]]:
        """
        Load template registry from JSON file.

        Returns:
            Registry dict or None if loading fails
        """
        try:
            registry_path = Path(self.TEMPLATE_REGISTRY_PATH)
            if not registry_path.exists():
                logger.error(f"Template registry not found at {self.TEMPLATE_REGISTRY_PATH}")
                return None

            with open(registry_path, 'r') as f:
                registry = json.load(f)

            return registry

        except Exception as e:
            logger.error(f"Failed to load template registry: {e}")
            return None

    def is_available(self) -> bool:
        """
        Check if template selector is available.

        Returns:
            True if Groq service is configured and registry is loaded
        """
        return self.groq_service is not None and self.template_registry is not None

    async def select_template(
        self,
        project_name: str,
        project_description: str,
        project_type: str = "website",
    ) -> Dict[str, Any]:
        """
        Select the best template using Groq LLM.

        Args:
            project_name: Name of the project
            project_description: Description of the project
            project_type: Type of project (default: "website")

        Returns:
            Dict with template information:
            {
                "success": True,
                "template": {
                    "id": "saas",
                    "repo": "...",
                    "category": "...",
                    ...
                }
            }
            or
            {
                "success": False,
                "error": "error message",
                "template": {...}  # fallback template if available
            }
        """
        if not self.is_available():
            error = "Template selector not available - Groq not configured or registry missing"
            logger.error(error)
            # Try to return fallback template
            fallback = self._get_fallback_template()
            if fallback:
                return {
                    "success": False,
                    "error": error,
                    "template": fallback
                }
            return {"success": False, "error": error}

        # Build template info for Groq
        templates_info = self._build_templates_info()

        # Build user message
        user_message = f"""Project Information:
- Name: {project_name}
- Description: {project_description}
- Type: {project_type}

Available Templates:
{templates_info}

Select the most suitable template ID for this project."""

        # Build messages array
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

        try:
            # Call Groq API
            template_id = await self.groq_service.generate_chat_completion(
                messages=messages,
                temperature=0.1,  # Low temperature for consistent selection
                max_tokens=50,   # Short response expected
            )

            # Clean the response (strip whitespace, extract first word)
            template_id = template_id.strip().split()[0].lower()

            logger.info(f"Groq selected template: {template_id}")

            # Find template in registry
            template = self._find_template_by_id(template_id)

            if template:
                return {
                    "success": True,
                    "template": template
                }
            else:
                logger.warning(f"Template ID '{template_id}' not found in registry, using fallback")
                fallback = self._get_fallback_template()
                return {
                    "success": False,
                    "error": f"Selected template '{template_id}' not found",
                    "template": fallback
                }

        except Exception as e:
            logger.error(f"Failed to select template with Groq: {e}")
            # Return fallback template
            fallback = self._get_fallback_template()
            if fallback:
                return {
                    "success": False,
                    "error": f"Groq selection failed: {type(e).__name__}",
                    "template": fallback
                }
            return {"success": False, "error": f"Groq selection failed: {type(e).__name__}"}

    def _build_templates_info(self) -> str:
        """
        Build formatted string of template information.

        Returns:
            Formatted string with template details
        """
        if not self.template_registry:
            return "No templates available"

        templates_info = []
        for template in self.template_registry.get("templates", []):
            info = f"""
- ID: {template.get('id')}
  Category: {template.get('category')}
  Keywords: {', '.join(template.get('keywords', []))}
  Features: {', '.join(template.get('features', []))}
"""
            templates_info.append(info)

        return "\n".join(templates_info)

    def _find_template_by_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        """
        Find template in registry by ID.

        Args:
            template_id: Template ID to find

        Returns:
            Template dict or None if not found
        """
        if not self.template_registry:
            return None

        for template in self.template_registry.get("templates", []):
            if template.get("id") == template_id:
                return template

        return None

    def _get_fallback_template(self) -> Optional[Dict[str, Any]]:
        """
        Get fallback template from registry.

        Returns:
            Fallback template dict or None if not available
        """
        if not self.template_registry:
            return None

        # Try to get default fallback from registry
        fallback_id = self.template_registry.get("default_fallback", "saas")
        return self._find_template_by_id(fallback_id)

    def list_templates(self) -> Dict[str, Any]:
        """
        List all available templates.

        Returns:
            Dict with success status and templates list
        """
        if not self.template_registry:
            return {
                "success": False,
                "error": "Template registry not loaded"
            }

        templates = self.template_registry.get("templates", [])
        return {
            "success": True,
            "templates": [
                {
                    "id": t.get("id"),
                    "category": t.get("category"),
                    "repo": t.get("repo"),
                    "keywords": t.get("keywords", []),
                    "features": t.get("features", [])
                }
                for t in templates
            ],
            "default_fallback": self.template_registry.get("default_fallback", "saas")
        }
