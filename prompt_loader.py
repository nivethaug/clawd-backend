#!/usr/bin/env python3
"""
Prompt Loader - Load prompts from markdown files

Provides utilities to load and render prompt templates from the prompts/ directory.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Prompts directory
PROMPTS_DIR = Path(__file__).parent / "prompts"


class PromptLoader:
    """Load and render prompts from markdown files."""
    
    def __init__(self, prompts_dir: Optional[Path] = None):
        """
        Initialize prompt loader.
        
        Args:
            prompts_dir: Directory containing prompt markdown files
        """
        self.prompts_dir = prompts_dir or PROMPTS_DIR
        
        if not self.prompts_dir.exists():
            logger.warning(f"Prompts directory not found: {self.prompts_dir}")
    
    def load_prompt(self, prompt_name: str) -> Optional[str]:
        """
        Load raw prompt content from markdown file.
        
        Args:
            prompt_name: Name of prompt file (without .md extension)
        
        Returns:
            Raw prompt content or None if not found
        """
        prompt_path = self.prompts_dir / f"{prompt_name}.md"
        
        if not prompt_path.exists():
            logger.error(f"Prompt file not found: {prompt_path}")
            return None
        
        try:
            content = prompt_path.read_text(encoding='utf-8')
            logger.info(f"Loaded prompt: {prompt_name} ({len(content)} chars)")
            return content
        except Exception as e:
            logger.error(f"Failed to load prompt {prompt_name}: {e}")
            return None
    
    def extract_template(self, content: str) -> Optional[str]:
        """
        Extract template section from prompt markdown.
        
        Looks for ```markdown or ``` code blocks.
        
        Args:
            content: Full markdown content
        
        Returns:
            Template content or None if not found
        """
        import re
        
        # Look for ```markdown ... ``` or ``` ... ```
        pattern = r'```(?:markdown)?\s*\n(.*?)\n```'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            return match.group(1).strip()
        
        # If no code block found, return the entire content
        logger.warning("No template code block found, returning full content")
        return content
    
    def render_prompt(self, prompt_name: str, variables: Dict[str, Any]) -> Optional[str]:
        """
        Load and render a prompt template with variables.
        
        Args:
            prompt_name: Name of prompt file (without .md extension)
            variables: Dictionary of variables to substitute
        
        Returns:
            Rendered prompt or None if failed
        """
        # Load raw prompt
        content = self.load_prompt(prompt_name)
        if not content:
            return None
        
        # Extract template
        template = self.extract_template(content)
        if not template:
            return None
        
        # Substitute variables
        try:
            rendered = template.format(**variables)
            logger.info(f"Rendered prompt: {prompt_name} with {len(variables)} variables")
            return rendered
        except KeyError as e:
            logger.error(f"Missing variable {e} in prompt {prompt_name}")
            return None
        except Exception as e:
            logger.error(f"Failed to render prompt {prompt_name}: {e}")
            return None
    
    def get_prompt_names(self) -> list:
        """
        Get list of available prompt names.
        
        Returns:
            List of prompt names (without .md extension)
        """
        if not self.prompts_dir.exists():
            return []
        
        return [f.stem for f in self.prompts_dir.glob("*.md") if f.stem != "README"]


# Global instance
_loader = None


def get_prompt_loader() -> PromptLoader:
    """Get global prompt loader instance."""
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader


def load_prompt(prompt_name: str) -> Optional[str]:
    """
    Convenience function to load a prompt.
    
    Args:
        prompt_name: Name of prompt file (without .md extension)
    
    Returns:
        Raw prompt content or None if not found
    """
    return get_prompt_loader().load_prompt(prompt_name)


def render_prompt(prompt_name: str, **variables) -> Optional[str]:
    """
    Convenience function to render a prompt.
    
    Args:
        prompt_name: Name of prompt file (without .md extension)
        **variables: Variables to substitute
    
    Returns:
        Rendered prompt or None if failed
    """
    return get_prompt_loader().render_prompt(prompt_name, variables)


# Example usage
if __name__ == "__main__":
    loader = PromptLoader()
    
    print("Available prompts:")
    for name in loader.get_prompt_names():
        print(f"  - {name}")
    
    print("\nLoading page-inference prompt:")
    content = loader.load_prompt("01-page-inference")
    if content:
        print(f"  Loaded {len(content)} characters")
        template = loader.extract_template(content)
        print(f"  Template: {len(template)} characters")
    
    print("\nRendering with variables:")
    rendered = loader.render_prompt("01-page-inference", {
        "goal_description": "Build a CRM system for managing customer relationships"
    })
    if rendered:
        print(f"  Rendered {len(rendered)} characters")
        print(f"  Preview: {rendered[:200]}...")
