"""
Groq LLM Service

Handles all Groq API interactions for multi-turn chat completion.
Uses official Groq Python SDK.
"""

import os
import logging
import asyncio
from typing import Optional, List

from groq import Groq

logger = logging.getLogger(__name__)

# Track if we've already logged the missing API key error
_GROQ_API_KEY_LOGGED = False


class GroqService:
    """Service for interacting with Groq API."""

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    DEFAULT_TEMPERATURE = 0.4
    DEFAULT_MAX_TOKENS = 2000
    TIMEOUT_SECONDS = 30

    def __init__(self):
        """Initialize Groq service with environment configuration."""
        global _GROQ_API_KEY_LOGGED
        
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", self.DEFAULT_MODEL)

        # Validate API key exists - log only once
        if not self.api_key or self.api_key == "your_key_here":
            if not _GROQ_API_KEY_LOGGED:
                logger.error("GROQ_API_KEY not configured or not set")
                _GROQ_API_KEY_LOGGED = True
            raise ValueError("GROQ_API_KEY is not configured")

        # Initialize Groq client
        self.client = Groq(api_key=self.api_key, timeout=self.TIMEOUT_SECONDS)

    async def generate_chat_completion(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate a chat completion using Groq API via SDK (async).

        Args:
            messages: Array of message dicts with 'role' and 'content'
            temperature: Sampling temperature (optional, defaults to 0.4)
            max_tokens: Maximum tokens to generate (optional, defaults to 2000)

        Returns:
            Generated text response from the assistant

        Raises:
            RuntimeError: If Groq API call fails
        """
        try:
            # Use Groq SDK to create completion (run in executor for async compatibility)
            loop = asyncio.get_event_loop()
            completion = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature or self.DEFAULT_TEMPERATURE,
                    max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
                )
            )

            # Return the assistant's message content
            return completion.choices[0].message.content

        except Exception as e:
            # Handle Groq API errors
            error_str = str(e).lower()

            if "invalid api key" in error_str or "unauthorized" in error_str:
                logger.error(f"Groq API invalid key: {type(e).__name__}")
                raise RuntimeError("Invalid Groq API key")

            elif "timeout" in error_str or "timed out" in error_str:
                logger.error(f"Groq API timeout: {e}")
                raise RuntimeError("Groq API request timed out")

            elif "rate limit" in error_str or "quota" in error_str:
                logger.error(f"Groq API rate limit: {e}")
                raise RuntimeError("Groq API rate limit exceeded")

            else:
                logger.error(f"Groq API unexpected error: {type(e).__name__}: {e}")
                raise RuntimeError(f"Groq API request failed: {type(e).__name__}")

    def is_configured(self) -> bool:
        """
        Check if Groq service is properly configured.

        Returns:
            True if API key is set and not the placeholder
        """
        return bool(self.api_key and self.api_key != "your_key_here")

    def infer_pages(self, description: str) -> List[str]:
        """
        Use LLM to infer page names from a product description.

        Args:
            description: Product/project description

        Returns:
            List of page names (e.g., ["Dashboard", "Documents", "Settings"])
        """
        import json

        prompt = f"""Extract the EXACT page names mentioned in this SaaS app description.

Description: {description}

CRITICAL RULES:
1. Look for phrases like "with X pages:", "pages:", "main pages:", etc.
2. Extract ONLY the page names explicitly mentioned in the description
3. Convert to PascalCase: "Knowledge Base" → "KnowledgeBase", "My Learning" → "MyLearning"
4. If pages are listed after "pages:", use those EXACT pages
5. Do NOT add generic pages if specific pages are mentioned
6. Return 4-8 pages maximum

Examples:
- "with pages: Dashboard, Tickets, Knowledge Base" → ["Dashboard", "Tickets", "KnowledgeBase"]
- "four main pages: Dashboard, Courses, My Learning, Certificates" → ["Dashboard", "Courses", "MyLearning", "Certificates"]
- "Support desk with Tickets, Knowledge Base, Customers" → ["Dashboard", "Tickets", "KnowledgeBase", "Customers"]

Response format (JSON ONLY):
{{"pages": ["Dashboard", "Tickets", "KnowledgeBase", "Customers"]}}"""

        messages = [{"role": "user", "content": prompt}]

        try:
            response = self.generate_chat_completion(messages, max_tokens=200)
            print(f"🔴 GROQ-RAW-RESPONSE: {response[:500]}")

            # Parse JSON response
            # Try to extract JSON from response (handle markdown code blocks)
            response = response.strip()
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()

            data = json.loads(response)
            pages = data.get("pages", [])

            # Validate and clean page names
            cleaned = []
            for page in pages:
                # Remove special characters, ensure PascalCase
                clean = "".join(c for c in str(page) if c.isalnum() or c.isspace())
                clean = "".join(word.capitalize() for word in clean.split())
                if clean and len(clean) < 30:  # Skip absurdly long names
                    cleaned.append(clean)

            logger.info(f"[Groq] Inferred pages: {cleaned}")
            print(f"🔴 GROQ-CLEANED-PAGES: {cleaned}")
            return cleaned

        except json.JSONDecodeError as e:
            logger.error(f"[Groq] JSON parse failed: {e}. Raw response: {response[:500]}")
            return ["Dashboard", "Analytics", "Settings"]
        except Exception as e:
            logger.error(f"[Groq] Page inference failed: {type(e).__name__}: {e}")
            print(f"🔴 GROQ-ERROR: {e}")
            # Return sensible defaults
            return ["Dashboard", "Analytics", "Settings"]
