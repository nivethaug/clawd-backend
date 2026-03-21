#!/usr/bin/env python3
"""
ACP Preprocessor - Fast LLM preprocessing before ACPX calls.

Uses GLM-4-Flash (via Z.ai or Groq) to:
1. Classify user intent (simple question vs code changes needed)
2. Enhance vague requests into clear instructions
3. Skip ACPX for simple conversational messages
"""

import os
import logging
import json
import httpx
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# Configuration
PREPROCESSOR_TIMEOUT = 10  # Fast timeout for preprocessing
Z_AI_API_KEY = os.getenv("Z_AI_API_KEY", "")  # REQUIRED - Set in environment
Z_AI_API_BASE = os.getenv("Z_AI_API_BASE", "https://api.z.ai/api/coding/paas/v4")
Z_AI_MODEL = os.getenv("Z_AI_MODEL", "glm-4-flash")  # Fast model for preprocessing
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")  # Fallback option


class IntentType(Enum):
    """Classification of user intent."""
    SIMPLE_QUESTION = "simple_question"      # Just needs a text response
    CODE_CHANGE = "code_change"              # Needs to modify files
    CLARIFICATION = "clarification"          # User is asking for clarification
    GREETING = "greeting"                    # Hello, hi, etc.
    UNKNOWN = "unknown"                      # Can't determine


@dataclass
class PreprocessResult:
    """Result of preprocessing a user message."""
    intent: IntentType
    should_call_acpx: bool
    enhanced_prompt: Optional[str]
    direct_response: Optional[str]
    confidence: float


class ACPPreprocessor:
    """
    Fast LLM preprocessor for ACP chat.
    
    Uses GLM-4-Flash (Z.ai) or Llama-3.1-8B (Groq) for fast classification.
    """
    
    def __init__(self, use_glm: bool = True):
        """
        Initialize preprocessor.
        
        Args:
            use_glm: If True, prefer GLM-4-Flash. If False, use Groq Llama.
        """
        self.use_glm = use_glm and bool(Z_AI_API_KEY)
        self.use_groq = bool(GROQ_API_KEY)
        
        if not self.use_glm and not self.use_groq:
            logger.warning("[ACP-PRE] No fast LLM API configured, preprocessing disabled")
            self.enabled = False
        else:
            self.enabled = True
            logger.info(f"[ACP-PRE] Initialized with {'GLM-4-Flash (Z.ai)' if self.use_glm else 'Groq Llama'}")
    
    async def classify_intent(self, user_message: str, project_name: str) -> PreprocessResult:
        """
        Classify user intent and decide if ACPX is needed.
        
        Args:
            user_message: User's chat message
            project_name: Name of the project
            
        Returns:
            PreprocessResult with classification and enhanced prompt
        """
        if not self.enabled:
            # No preprocessing - always call ACPX
            return PreprocessResult(
                intent=IntentType.UNKNOWN,
                should_call_acpx=True,
                enhanced_prompt=None,
                direct_response=None,
                confidence=0.0
            )
        
        system_prompt = f"""You are an intent classifier for a web app builder assistant.

The user is working on a project called "{project_name}".

Classify the user's message into ONE of these categories:
1. GREETING - Simple hello/hi/good morning
2. SIMPLE_QUESTION - Asking about what you can do, general questions, no code changes needed
3. CODE_CHANGE - Wants to add/modify/remove features, pages, components, or fix bugs
4. CLARIFICATION - Asking about previous response or for more details

IMPORTANT: Respond with ONLY a JSON object, no other text:
{{"intent": "CATEGORY", "needs_acpx": true/false, "enhanced_prompt": "clearer version if needs_acpx is true", "direct_response": "simple response if needs_acpx is false", "confidence": 0.0-1.0}}

Examples:
- "hello" -> {{"intent": "GREETING", "needs_acpx": false, "direct_response": "Hello! How can I help you with your {project_name} app today?", "confidence": 0.95}}
- "what can you do" -> {{"intent": "SIMPLE_QUESTION", "needs_acpx": false, "direct_response": "I can help you build your app! Add pages, create forms, fix issues, and more. What would you like to do?", "confidence": 0.9}}
- "add a contact form" -> {{"intent": "CODE_CHANGE", "needs_acpx": true, "enhanced_prompt": "Add a contact form to the website with name, email, and message fields", "confidence": 0.95}}
- "my app health" -> {{"intent": "SIMPLE_QUESTION", "needs_acpx": true, "enhanced_prompt": "Check the health and status of the application - look for issues with dependencies, configuration, and file structure", "confidence": 0.85}}
- "fix the login bug" -> {{"intent": "CODE_CHANGE", "needs_acpx": true, "enhanced_prompt": "Find and fix the bug in the login functionality", "confidence": 0.9}}"""

        user_prompt = f'User message: "{user_message}"\n\nClassify and respond with JSON only:'

        try:
            if self.use_glm:
                response = await self._call_glm(system_prompt, user_prompt)
            else:
                response = await self._call_groq_fast(system_prompt, user_prompt)
            
            # Parse JSON response
            result = self._parse_response(response, user_message)
            logger.info(f"[ACP-PRE] Classified as {result.intent.value}, needs_acpx={result.should_call_acpx}")
            return result
            
        except Exception as e:
            logger.error(f"[ACP-PRE] Classification failed: {e}")
            # Fallback: call ACPX to be safe
            return PreprocessResult(
                intent=IntentType.UNKNOWN,
                should_call_acpx=True,
                enhanced_prompt=None,
                direct_response=None,
                confidence=0.0
            )
    
    async def _call_glm(self, system_prompt: str, user_prompt: str) -> str:
        """Call GLM-4-Flash via Z.ai API (OpenAI-compatible)."""
        async with httpx.AsyncClient(timeout=PREPROCESSOR_TIMEOUT) as client:
            response = await client.post(
                f"{Z_AI_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {Z_AI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": Z_AI_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def _call_groq_fast(self, system_prompt: str, user_prompt: str) -> str:
        """Call Llama-3.1-8B via Groq API (fast model)."""
        async with httpx.AsyncClient(timeout=PREPROCESSOR_TIMEOUT) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    def _parse_response(self, response: str, original_message: str) -> PreprocessResult:
        """Parse LLM response into PreprocessResult."""
        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                # Remove code block markers
                lines = response.split("\n")
                response = "\n".join(lines[1:-1])
            
            data = json.loads(response)
            
            intent_map = {
                "GREETING": IntentType.GREETING,
                "SIMPLE_QUESTION": IntentType.SIMPLE_QUESTION,
                "CODE_CHANGE": IntentType.CODE_CHANGE,
                "CLARIFICATION": IntentType.CLARIFICATION,
            }
            
            intent_str = data.get("intent", "UNKNOWN").upper()
            intent = intent_map.get(intent_str, IntentType.UNKNOWN)
            
            return PreprocessResult(
                intent=intent,
                should_call_acpx=data.get("needs_acpx", True),
                enhanced_prompt=data.get("enhanced_prompt"),
                direct_response=data.get("direct_response"),
                confidence=float(data.get("confidence", 0.5))
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[ACP-PRE] Failed to parse response: {e}")
            # Default to calling ACPX
            return PreprocessResult(
                intent=IntentType.UNKNOWN,
                should_call_acpx=True,
                enhanced_prompt=original_message,
                direct_response=None,
                confidence=0.0
            )


# Singleton instance
_preprocessor: Optional[ACPPreprocessor] = None


def get_preprocessor() -> ACPPreprocessor:
    """Get or create the preprocessor singleton."""
    global _preprocessor
    if _preprocessor is None:
        _preprocessor = ACPPreprocessor()
    return _preprocessor


# Convenience function
async def preprocess_message(user_message: str, project_name: str) -> PreprocessResult:
    """
    Preprocess a user message before ACPX.
    
    Args:
        user_message: User's chat message
        project_name: Name of the project
        
    Returns:
        PreprocessResult with classification and recommendations
    """
    return await get_preprocessor().classify_intent(user_message, project_name)
