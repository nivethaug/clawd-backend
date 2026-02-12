"""
Groq LLM Service

Handles all Groq API interactions for multi-turn chat completion.
Stateless, secure, with proper error handling.
"""

import os
import logging
from typing import Optional, List
from httpx import AsyncClient, TimeoutException, HTTPStatusError

logger = logging.getLogger(__name__)


class GroqService:
    """Service for interacting with Groq API."""

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    DEFAULT_MODEL = "llama3-70b-8192"
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

    async def generate_chat_completion(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Generate a chat completion using Groq API.

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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.DEFAULT_TEMPERATURE,
            "max_tokens": max_tokens or self.DEFAULT_MAX_TOKENS,
        }

        try:
            async with AsyncClient(timeout=self.TIMEOUT_SECONDS) as client:
                response = await client.post(
                    self.GROQ_API_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()

                data = response.json()
                return data["choices"][0]["message"]["content"]

        except TimeoutException:
            logger.error("Groq API timeout")
            raise RuntimeError("Groq API request timed out")

        except HTTPStatusError as e:
            logger.error(f"Groq API HTTP error: {e.response.status_code}")
            raise RuntimeError(f"Groq API error: {e.response.status_code}")

        except Exception as e:
            logger.error(f"Groq API unexpected error: {type(e).__name__}")
            # Never log the API key
            raise RuntimeError(f"Groq API request failed: {type(e).__name__}")

    def is_configured(self) -> bool:
        """
        Check if Groq service is properly configured.

        Returns:
            True if API key is set and not the placeholder
        """
        return bool(self.api_key and self.api_key != "your_key_here")
