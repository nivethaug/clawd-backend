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

    async def infer_pages(self, description: str) -> List[str]:
        """
        Use LLM to infer page names from a product description.

        Args:
            description: Product/project description

        Returns:
            List of page names (e.g., ["Dashboard", "Documents", "Settings"])
        """
        import json

        prompt = f"""You are extracting page names from a SaaS application description.

Product description:
{description}

CRITICAL: You MUST respond with ONLY a JSON object. NO explanations. NO text before or after.

Output format (STRICT - nothing else):
{{"pages": ["PageOne","PageTwo","PageThree","PageFour"]}}

Step 1 — Extract Explicit Pages
Look for phrases like: "main pages:", "pages:", "sections:", "modules:"
If found, extract them EXACTLY as written.

Step 2 — Contextual Inference (if no explicit pages)
Identify the product type and generate 4-8 realistic pages:
- Analytics platform → ActivityMonitor, DataExplorer, Metrics, Reports, Alerts, Integrations
- CRM → Contacts, Leads, Deals, Accounts, Reports, Settings
- E-commerce → Products, Orders, Customers, Inventory, Analytics, StoreSettings
- Document system → Documents, Folders, Search, Sharing, Settings
- Project management → Projects, Tasks, Team, Timeline, Reports, Settings

RULES:
1. Return ONLY JSON - no markdown, no explanation, no text
2. 4-8 pages, PascalCase, 1-3 words each
3. Never empty array
4. Match product type contextually"""

        messages = [{"role": "user", "content": prompt}]

        try:
            logger.info("🔍 GROQ_INVOKE: Starting page inference...")
            logger.info(f"🔍 GROQ_INVOKE: Description: {description[:200]}...")
            print("\n" + "="*60)
            print("🔍 GROQ PAGE INFERENCE START")
            print("="*60)
            
            # Call async method with await
            response = await self.generate_chat_completion(messages, max_tokens=200)
            
            print(f"🔍 GROQ_RAW_RESPONSE: {response[:500]}")
            logger.info(f"🔍 GROQ_RAW_RESPONSE: {response[:500]}")

            # Parse JSON response - handle multiple formats
            response = response.strip()
            
            # Method 1: Extract from markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].split("```")[0].strip()
            else:
                # Method 2: Find JSON object using regex (handles embedded JSON in text)
                import re
                # Match {"pages": [...]} pattern
                json_match = re.search(r'\{[^{}]*"pages"\s*:\s*\[[^\]]*\][^{}]*\}', response, re.DOTALL)
                if json_match:
                    response = json_match.group(0)
                    logger.info(f"[Groq] Extracted JSON from response: {response[:200]}")

            data = json.loads(response)
            pages = data.get("pages", [])
            print(f"✅ GROQ_PARSED_PAGES: {pages}")
            logger.info(f"✅ GROQ_PARSED_PAGES: {pages}")

            # Validate and clean page names
            cleaned = []
            for page in pages:
                # Remove special characters, ensure PascalCase
                clean = "".join(c for c in str(page) if c.isalnum() or c.isspace())
                clean = "".join(word.capitalize() for word in clean.split())
                if clean and len(clean) < 30:  # Skip absurdly long names
                    cleaned.append(clean)

            print(f"✅ GROQ_CLEANED_PAGES: {cleaned}")
            print(f"📊 GROQ_PAGE_COUNT: {len(cleaned)} pages")
            print("="*60)
            print("🔍 GROQ PAGE INFERENCE COMPLETE")
            print("="*60 + "\n")
            logger.info(f"[Groq] Inferred pages: {cleaned}")
            return cleaned

        except json.JSONDecodeError as e:
            logger.error(f"[Groq] JSON parse failed: {e}. Raw response: {response[:500]}")
            print(f"❌ GROQ_JSON_ERROR: {e}")
            print(f"❌ GROQ_RAW_FAILED: {response[:500]}")
            print(f"⚠️  GROQ_FALLBACK: Using generic defaults")
            print("="*60 + "\n")
            return ["Dashboard", "Analytics", "Settings"]
        except Exception as e:
            logger.error(f"[Groq] Page inference failed: {type(e).__name__}: {e}")
            print(f"❌ GROQ_ERROR: {type(e).__name__}: {e}")
            print(f"⚠️  GROQ_FALLBACK: Using generic defaults")
            print("="*60 + "\n")
            # Return sensible defaults
            return ["Dashboard", "Analytics", "Settings"]
