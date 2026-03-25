"""
Project Resolver
Resolve project from user text/active_project using fuzzy matching
"""

import logging
from difflib import get_close_matches
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    """Result of project resolution."""
    status: str  # "resolved" | "selection" | "not_found"
    project: Optional[Dict[str, Any]] = None
    candidates: Optional[List[Dict[str, Any]]] = None
    message: str = ""


class ProjectResolver:
    """
    Resolve project from user text or active session.
    
    Uses fuzzy matching via difflib.get_close_matches() with 0.6 cutoff.
    """
    
    def resolve(
        self,
        user_text: str,
        projects: List[Dict[str, Any]],
        active_project: Optional[Dict[str, Any]] = None,
        explicit_project_id: Optional[str] = None
    ) -> ResolutionResult:
        """
        Resolve project from various inputs.
        
        Priority:
        1. Explicit project_id in args (validate exists)
        2. Active project from session
        3. Fuzzy match against user_text
        
        Args:
            user_text: User's message text
            projects: List of all projects from DB
            active_project: Currently active project from session
            explicit_project_id: Project ID explicitly provided in tool args
            
        Returns:
            ResolutionResult with status and project/candidates
        """
        logger.debug(f"[PROJECT-RESOLVER] Resolving project (explicit={explicit_project_id}, active={active_project})")
        
        # 1. Check explicit project_id
        if explicit_project_id:
            project = self._find_by_id(explicit_project_id, projects)
            if project:
                logger.info(f"[PROJECT-RESOLVER] Found project by explicit ID: {project['domain']}")
                return ResolutionResult(
                    status="resolved",
                    project=project,
                    message=f"Using project: {project['name']}"
                )
            else:
                # Explicit ID not found - return not_found
                logger.warning(f"[PROJECT-RESOLVER] Explicit project ID not found: {explicit_project_id}")
                return ResolutionResult(
                    status="not_found",
                    message=f"Project '{explicit_project_id}' not found"
                )
        
        # 2. Use active project if available
        if active_project:
            logger.info(f"[PROJECT-RESOLVER] Using active project: {active_project['domain']}")
            return ResolutionResult(
                status="resolved",
                project=active_project,
                message=f"Using active project: {active_project['name']}"
            )
        
        # 3. Fuzzy match against user_text
        if not projects:
            logger.info("[PROJECT-RESOLVER] No projects available for matching")
            return ResolutionResult(
                status="not_found",
                message="No projects found. Create a project first."
            )
        
        # Build searchable strings (domain, name)
        project_map = {}
        search_strings = []
        
        for project in projects:
            domain = project.get("domain", "")
            name = project.get("name", "")
            
            if domain:
                project_map[domain.lower()] = project
                search_strings.append(domain.lower())
            
            if name:
                project_map[name.lower()] = project
                search_strings.append(name.lower())
        
        # Get close matches
        matches = get_close_matches(
            user_text.lower(),
            search_strings,
            n=3,  # Max 3 candidates
            cutoff=0.6  # Similarity threshold
        )
        
        if len(matches) == 1:
            # Single match - resolved
            matched_project = project_map[matches[0]]
            logger.info(f"[PROJECT-RESOLVER] Fuzzy matched to: {matched_project['domain']}")
            return ResolutionResult(
                status="resolved",
                project=matched_project,
                message=f"Matched to project: {matched_project['name']}"
            )
        
        elif len(matches) > 1:
            # Multiple matches - selection needed
            # Deduplicate by project ID
            unique_projects = []
            seen_ids = set()
            
            for match in matches:
                project = project_map[match]
                if project["id"] not in seen_ids:
                    unique_projects.append(project)
                    seen_ids.add(project["id"])
            
            logger.info(f"[PROJECT-RESOLVER] Multiple matches ({len(unique_projects)}), selection needed")
            return ResolutionResult(
                status="selection",
                candidates=unique_projects,
                message="Multiple projects match. Please select one."
            )
        
        else:
            # No matches - show all projects for selection
            logger.info("[PROJECT-RESOLVER] No matches, showing all projects for selection")
            return ResolutionResult(
                status="selection",
                candidates=projects[:10],  # Limit to 10
                message="Which project would you like to use?"
            )
    
    def _find_by_id(self, project_id: str, projects: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Find project by domain or database ID.
        
        Args:
            project_id: Domain name or numeric ID
            projects: List of projects
            
        Returns:
            Project dict or None
        """
        project_id_lower = project_id.lower()
        
        for project in projects:
            # Match by domain (case-insensitive)
            if project.get("domain", "").lower() == project_id_lower:
                return project
            
            # Match by name (case-insensitive)
            if project.get("name", "").lower() == project_id_lower:
                return project
            
            # Match by numeric ID
            if str(project.get("id")) == project_id:
                return project
        
        return None


# Singleton instance
_resolver: Optional[ProjectResolver] = None


def get_project_resolver() -> ProjectResolver:
    """Get or create project resolver singleton."""
    global _resolver
    if _resolver is None:
        _resolver = ProjectResolver()
    return _resolver
