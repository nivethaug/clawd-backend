"""
Groq LLM Service

Handles all Groq API interactions for multi-turn chat completion.
Uses official Groq Python SDK.
"""

import os
import logging
from typing import Optional, List

from groq import Groq

logger = logging.getLogger(__name__)


class GroqService:
    """Service for interacting with Groq API."""

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    DEFAULT_TEMPERATURE = 0.4
    DEFAULT_MAX_TOKENS = 2000
    TIMEOUT_SECONDS = 30

    def __init__(self):
        """Initialize Groq service with environment configuration."""
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", self.DEFAULT_MODEL)

        # Validate API key exists
        if not self.api_key or self.api_key == "your_key_here":
            logger.error("GROQ_API_KEY not configured or not set")
            raise ValueError("GROQ_API_KEY is not configured")

        # Initialize Groq client
        self.client = Groq(api_key=self.api_key)

    async def generate_chat_completion(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate a chat completion using Groq API via SDK.

        Args:
            messages: Array of message dicts with 'role' and 'content'
            temperature: Sampling temperature (optional, defaults to 0.4)
            max_tokens: Maximum tokens to generate (optional, defaults to 2000)

        Returns:
            Generated text response from the assistant

        Raises:
            ValueError: If API key is not configured
            RuntimeError: If Groq API call fails
        """
        if not self.api_key or self.api_key == "your_key_here":
            raise ValueError("GROQ_API_KEY is not configured")

        try:
            # Use Groq SDK to create completion
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature or self.DEFAULT_TEMPERATURE,
                max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
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
