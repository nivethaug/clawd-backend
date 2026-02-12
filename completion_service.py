"""
Multi-turn Chat Completion Service

Handles stateless multi-turn chat conversations using Groq LLM.
Accepts full conversation history and returns next AI response.
"""

import logging
from typing import Optional, List, Dict, Any

from groq_service import GroqService

logger = logging.getLogger(__name__)


class CompletionService:
    """Service for multi-turn chat completions."""

    # Maximum number of messages to prevent abuse
    MAX_MESSAGES = 50

    # Internal system prompt (never sent from client)
    SYSTEM_PROMPT = """You are a senior AI software architect and product strategist. The user is building AI-powered automation projects inside a structured platform.

Project Types:
website: - Full-stack web apps - SaaS dashboards - APIs + frontend - Auth + DB aware
telegrambot: - Telegram Bot API - Commands + webhook/polling - Event-driven
discordbot: - Slash commands - Moderation + automation - Event-driven
tradingbot: - Exchange API integrations - Strategy execution - Risk management mandatory - API rate limits awareness
scheduler: - Cron-job based systems - Recurring automation - Web scraping - Web search integrations - Time-triggered execution
custom: - Hybrid systems - Multi-service orchestration - Advanced automation

Mode Rules:
If mode = create: Structure final output as:
1. Project Objective
2. Core Features
3. Architecture Overview
4. Required Integrations
5. Data & Storage Considerations
6. Execution Constraints

If mode = modify: Structure final output as:
1. Change Summary
2. Impacted Components
3. Implementation Strategy
4. Risk & Side Effects

General Behavior Rules:
- Use entire conversation context.
- Maintain conversation continuity.
- Ask clarifying questions if needed.
- Do NOT generate code.
- Do NOT execute.
- Keep structured output.
- Tailor response to projectType.
- tradingbot → emphasize risk controls.
- scheduler → emphasize cron reliability.
- bots → emphasize event-driven design.
- website → emphasize frontend/backend separation.
- custom → infer intelligently."""

    def __init__(self):
        """Initialize completion service."""
        self.groq_service: Optional[GroqService] = None
        self._initialize_groq()

    def _initialize_groq(self) -> None:
        """Initialize Groq service if configured."""
        try:
            self.groq_service = GroqService()
            if self.groq_service.is_configured():
                logger.info("Groq completion service initialized successfully")
            else:
                logger.warning("Groq completion service not properly configured")
                self.groq_service = None
        except ValueError:
            logger.warning("GROQ_API_KEY not configured, completion service unavailable")
            self.groq_service = None
        except Exception as e:
            logger.error(f"Failed to initialize Groq completion service: {e}")
            self.groq_service = None

    def is_available(self) -> bool:
        """
        Check if completion service is available.

        Returns:
            True if Groq service is configured and ready
        """
        return self.groq_service is not None

    def sanitize_message(self, msg: Dict[str, str]) -> Optional[Dict[str, str]]:
        """
        Sanitize a single message - reject system role, validate structure.

        Args:
            msg: Message dict with 'role' and 'content'

        Returns:
            Sanitized message dict or None if invalid
        """
        role = msg.get("role", "").lower()
        content = msg.get("content", "").strip()

        # Reject system role from client
        if role == "system":
            logger.warning("Client attempted to send system role")
            return None

        # Only allow user and assistant roles
        if role not in ["user", "assistant"]:
            return None

        # Content must be non-empty
        if not content:
            return None

        return {"role": role, "content": content}

    def validate_request(
        self,
        project_type: str,
        mode: str,
        messages: List[Dict[str, str]],
    ) -> tuple[bool, Optional[str]]:
        """
        Validate completion request parameters.

        Args:
            project_type: Project type from user
            mode: Operation mode (create/modify)
            messages: List of chat messages

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate project_type
        valid_project_types = [
            "website",
            "telegrambot",
            "discordbot",
            "tradingbot",
            "scheduler",
            "custom",
        ]
        if project_type not in valid_project_types:
            return (
                False,
                f"Invalid projectType '{project_type}'. Must be one of: "
                f"{', '.join(valid_project_types)}",
            )

        # Validate mode
        if mode not in ["create", "modify"]:
            return False, f"Invalid mode '{mode}'. Must be either 'create' or 'modify'"

        # Validate messages array
        if not messages or len(messages) == 0:
            return False, "messages array is required and cannot be empty"

        # Check message count limit
        if len(messages) > self.MAX_MESSAGES:
            return False, f"messages array too large (max {self.MAX_MESSAGES})"

        # Sanitize all messages
        sanitized = []
        for msg in messages:
            clean = self.sanitize_message(msg)
            if clean:
                sanitized.append(clean)

        # Must have at least one user message after sanitization
        has_user = any(m["role"] == "user" for m in sanitized)
        if not has_user:
            return False, "messages array must contain at least one user message"

        return True, None

    async def complete(
        self,
        project_type: str,
        mode: str,
        messages: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Generate a multi-turn chat completion.

        Args:
            project_type: Type of project
            mode: Operation mode (create or modify)
            messages: Array of chat messages (full history)

        Returns:
            Dict with success status and message or error

        Raises:
            RuntimeError: If Groq service is not available
        """
        if not self.is_available():
            raise RuntimeError("Completion service not available - GROQ_API_KEY not configured")

        # Validate request
        is_valid, error_msg = self.validate_request(project_type, mode, messages)
        if not is_valid:
            return {"success": False, "error": error_msg}

        # Sanitize messages (reject system role, validate structure)
        sanitized_messages = []
        for msg in messages:
            clean = self.sanitize_message(msg)
            if clean:
                sanitized_messages.append(clean)

        # Build messages array for Groq
        # First: system prompt
        # Then: sanitized client messages
        groq_messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
        ]

        # Add project context to the first user message
        # This helps Groq understand the context from the start
        context_prefix = f"""[Project Context]
Type: {project_type}
Mode: {mode}

Conversation:"""

        # Inject context into first user message or add as first message
        if sanitized_messages and sanitized_messages[0]["role"] == "user":
            first_user_msg = sanitized_messages[0]
            first_user_msg["content"] = f"{context_prefix}\n\n{first_user_msg['content']}"
            groq_messages.extend(sanitized_messages)
        else:
            # Add context as separate message if first is assistant
            groq_messages.append({"role": "user", "content": context_prefix})
            groq_messages.extend(sanitized_messages)

        try:
            # Call Groq API with full message history
            assistant_content = await self.groq_service.generate_chat_completion(
                messages=groq_messages,
            )

            return {
                "success": True,
                "message": {
                    "role": "assistant",
                    "content": assistant_content,
                },
            }

        except Exception as e:
            logger.error(f"Failed to generate completion: {e}")
            return {
                "success": False,
                "error": f"Failed to generate completion: {type(e).__name__}",
            }
