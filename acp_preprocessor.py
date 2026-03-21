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
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum

# Import read tool for GLM
from readtool import TOOL_DEFINITION, execute_read_tool

logger = logging.getLogger(__name__)

# Configuration
PREPROCESSOR_TIMEOUT = 10  # Fast timeout for preprocessing
Z_AI_API_KEY = os.getenv("Z_AI_API_KEY", "")  # Set in environment or .env
Z_AI_API_BASE = os.getenv("Z_AI_API_BASE", "https://api.z.ai/api/coding/paas/v4")
Z_AI_MODEL = os.getenv("Z_AI_MODEL", "GLM-4.5-Air")  # Free tier model (fast + good quality)
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
        # GLM is always enabled (API key check removed)
        self.use_glm = use_glm  # Always use GLM when requested
        self.use_groq = bool(GROQ_API_KEY)  # Groq as fallback
        
        # Check if API keys are configured
        self.glm_key_configured = bool(Z_AI_API_KEY)
        
        if not self.glm_key_configured:
            logger.warning("[ACP-PRE] Z_AI_API_KEY not configured - GLM calls will fail")
            if self.use_groq:
                logger.info("[ACP-PRE] Falling back to Groq for classification")
        
        # Always enable preprocessor (GLM doesn't require API key check)
        self.enabled = True
        logger.info(f"[ACP-PRE] Initialized with GLM-4-Flash (Z.ai) - always enabled")
    
    async def classify_intent(self, user_message: str, project_name: str, project_path: str = None) -> PreprocessResult:
        """
        Classify user intent and decide if ACPX is needed.
        
        Args:
            user_message: User's chat message
            project_name: Name of the project
            project_path: Optional path to project root for reading context
            
        Returns:
            PreprocessResult with classification and enhanced prompt
        """
        logger.info(f"[ACP-PRE] Classifying intent for message (length={len(user_message)}) in project '{project_name}'")
        
        if not self.enabled:
            # No preprocessing - always call ACPX
            logger.warning("[ACP-PRE] Preprocessor disabled, defaulting to ACPX")
            logger.info("[ACP-PRE] DECISION: Use ACPX (Claude) - preprocessor disabled")
            return PreprocessResult(
                intent=IntentType.UNKNOWN,
                should_call_acpx=True,
                enhanced_prompt=None,
                direct_response=None,
                confidence=0.0
            )
        
        # Detect if this is a code reading/checking request (not a change)
        is_read_only = self._is_read_only_request(user_message)
        logger.debug(f"[ACP-PRE] Read-only detection: {is_read_only}")
        logger.info(f"[ACP-PRE] Read-only check: {is_read_only}, project_path={bool(project_path)}, use_glm={self.use_glm}")
        
        if is_read_only and project_path and self.use_glm:
            # Use GLM with read tool to answer directly (no ACPX needed)
            logger.info("[ACP-PRE] DECISION: Use Read Tool (GLM) - read-only request with project context")
            logger.info("[ACP-PRE] Handling as read-only request with GLM tools")
            return await self._handle_read_only_with_tools(user_message, project_name, project_path)
        
        # For other cases, use simple classification
        # Log why we're NOT using read tool
        if is_read_only:
            if not project_path:
                logger.info("[ACP-PRE] Cannot use Read Tool: project_path not provided")
            elif not self.use_glm:
                logger.info("[ACP-PRE] Cannot use Read Tool: GLM not configured (using Groq)")
        
        project_context = ""
        if project_path:
            project_context = self._read_project_context(project_path)
        
        system_prompt = f"""You are an intent classifier for a web app builder assistant.

The user is working on a project called "{project_name}".
{project_context}

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
            # Check if GLM API key is available, fallback to Groq if not
            use_glm_for_call = self.use_glm and self.glm_key_configured
            
            if self.use_glm and not self.glm_key_configured:
                logger.warning("[ACP-PRE] GLM API key not configured, falling back to Groq")
            
            logger.debug(f"[ACP-PRE] Calling {'GLM' if use_glm_for_call else 'Groq'} for classification")
            
            if use_glm_for_call:
                response = await self._call_glm(system_prompt, user_prompt)
            else:
                response = await self._call_groq_fast(system_prompt, user_prompt)
            
            logger.debug(f"[ACP-PRE] Classification response received (length={len(response)})")
            
            # Parse JSON response
            result = self._parse_response(response, user_message)
            
            # Log final decision
            if result.should_call_acpx:
                logger.info(f"[ACP-PRE] DECISION: Use ACPX (Claude) - intent={result.intent.value}, confidence={result.confidence}")
            else:
                logger.info(f"[ACP-PRE] DECISION: Direct Response - intent={result.intent.value}, confidence={result.confidence}")
            
            logger.info(f"[ACP-PRE] Classified as {result.intent.value}, needs_acpx={result.should_call_acpx}, confidence={result.confidence}")
            return result
            
        except Exception as e:
            logger.error(f"[ACP-PRE] Classification failed: {e}")
            logger.warning("[ACP-PRE] DECISION: Use ACPX (Claude) - classification failed, fallback for safety")
            # Fallback: call ACPX to be safe
            return PreprocessResult(
                intent=IntentType.UNKNOWN,
                should_call_acpx=True,
                enhanced_prompt=None,
                direct_response=None,
                confidence=0.0
            )
    
    async def _call_glm_with_tools(self, system_prompt: str, user_prompt: str, project_path: str = None) -> str:
        """
        Call GLM-4-Flash with read tool support.
        
        GLM can read files to answer questions without calling ACPX.
        Handles multi-turn tool call loops.
        """
        if not Z_AI_API_KEY:
            raise ValueError("Z_AI_API_KEY not configured")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # Add project path hint if available
        if project_path and os.path.exists(project_path):
            messages[0]["content"] += f"\n\nProject path: {project_path}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:  # Longer timeout for tool calls
            max_iterations = 5  # Prevent infinite loops
            
            for iteration in range(max_iterations):
                response = await client.post(
                    f"{Z_AI_API_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {Z_AI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": Z_AI_MODEL,
                        "messages": messages,
                        "tools": [TOOL_DEFINITION],
                        "tool_choice": "auto",
                        "temperature": 0.1,
                        "max_tokens": 1000
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                msg = data["choices"][0]["message"]
                
                # No tool calls - return final response
                if not msg.get("tool_calls"):
                    return msg.get("content", "")
                
                # Add assistant message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": msg.get("content", ""),
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"]
                            }
                        }
                        for tc in msg["tool_calls"]
                    ]
                })
                
                # Execute each tool call
                for tc in msg["tool_calls"]:
                    try:
                        args = json.loads(tc["function"]["arguments"])
                        result = execute_read_tool(
                            path=args.get("path", ""),
                            max_lines=args.get("max_lines", 200),
                            offset=args.get("offset", 1)
                        )
                        tool_result = result["content"] if result["success"] else f"Error: {result['content']}"
                    except Exception as e:
                        tool_result = f"Tool error: {e}"
                    
                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": tool_result
                    })
                
                logger.info(f"[ACP-PRE] GLM made {len(msg['tool_calls'])} tool call(s), continuing...")
            
            # Max iterations reached - return last content
            return messages[-1].get("content", "Unable to complete analysis")

    async def _call_glm(self, system_prompt: str, user_prompt: str) -> str:
        """Call GLM-4-Flash via Z.ai API (simple, no tools)."""
        if not Z_AI_API_KEY:
            raise ValueError("Z_AI_API_KEY not configured")
        
        logger.debug(f"[ACP-PRE] Calling GLM-4-Flash API at {Z_AI_API_BASE}")
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
            content = data["choices"][0]["message"]["content"]
            logger.debug(f"[ACP-PRE] GLM response received (tokens: {data.get('usage', {})})")
            return content
    
    async def _call_groq_fast(self, system_prompt: str, user_prompt: str) -> str:
        """Call Llama-3.1-8B via Groq API (fast model)."""
        logger.debug("[ACP-PRE] Calling Groq Llama-3.1-8B API")
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
            content = data["choices"][0]["message"]["content"]
            logger.debug(f"[ACP-PRE] Groq response received (tokens: {data.get('usage', {})})")
            return content
    
    def _read_project_context(self, project_path: str) -> str:
        """
        Read key project files to build context for the LLM.
        
        This allows the preprocessor to answer questions about code
        WITHOUT calling ACPX (e.g., "check my app health", "what pages do I have").
        
        Args:
            project_path: Path to project root
            
        Returns:
            Context string with project information
        """
        if not project_path or not os.path.exists(project_path):
            return ""
        
        context_parts = []
        
        try:
            # 1. Read package.json for dependencies
            pkg_json_path = os.path.join(project_path, "package.json")
            if os.path.exists(pkg_json_path):
                with open(pkg_json_path, "r", encoding="utf-8") as f:
                    pkg = json.load(f)
                    deps = pkg.get("dependencies", {})
                    context_parts.append(f"Dependencies: {', '.join(deps.keys())}")
            
            # 2. List src directory structure
            src_path = os.path.join(project_path, "src")
            if os.path.exists(src_path):
                files = []
                for root, dirs, filenames in os.walk(src_path):
                    # Skip node_modules and hidden dirs
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
                    for fname in filenames:
                        if fname.endswith((".tsx", ".ts", ".jsx", ".js", ".css")):
                            rel_path = os.path.relpath(os.path.join(root, fname), src_path)
                            files.append(rel_path)
                
                if files:
                    context_parts.append(f"Source files ({len(files)}): {', '.join(files[:20])}")
                    if len(files) > 20:
                        context_parts.append(f"  ... and {len(files) - 20} more files")
            
            # 3. Check for pages directory (common in Next.js/Remix)
            pages_path = os.path.join(project_path, "src", "pages")
            if os.path.exists(pages_path):
                pages = [f for f in os.listdir(pages_path) if f.endswith((".tsx", ".ts", ".jsx", ".js"))]
                if pages:
                    context_parts.append(f"Pages: {', '.join(pages)}")
            
            # 4. Check for components
            components_path = os.path.join(project_path, "src", "components")
            if os.path.exists(components_path):
                components = []
                for root, dirs, filenames in os.walk(components_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for fname in filenames:
                        if fname.endswith((".tsx", ".ts", ".jsx", ".js")):
                            components.append(fname)
                if components:
                    context_parts.append(f"Components ({len(components)}): {', '.join(components[:15])}")
            
        except Exception as e:
            logger.warning(f"[ACP-PRE] Failed to read project context: {e}")
            return ""
        
        if context_parts:
            return "\nProject context:\n" + "\n".join(f"- {part}" for part in context_parts)
        return ""
    
    def _is_read_only_request(self, user_message: str) -> bool:
        """
        Detect if the user wants to READ/CHECK code without changing it.
        
        These can be handled by GLM with read tool (no ACPX needed).
        """
        read_patterns = [
            "check", "show", "list", "what", "explain", "describe",
            "review", "analyze", "tell me", "how does", "what is",
            "what are", "is there", "are there", "read", "view",
            "health", "status", "structure", "architecture"
        ]
        
        change_patterns = [
            "add", "create", "make", "build", "fix", "update", "change",
            "modify", "remove", "delete", "implement", "write", "edit",
            "deploy", "publish", "refactor", "optimize", "improve"
        ]
        
        msg_lower = user_message.lower()
        
        # If it has change words, it's not read-only
        for pattern in change_patterns:
            if pattern in msg_lower:
                return False
        
        # If it has read words, it's read-only
        for pattern in read_patterns:
            if pattern in msg_lower:
                return True
        
        return False
    
    async def _handle_read_only_with_tools(self, user_message: str, project_name: str, project_path: str) -> PreprocessResult:
        """
        Handle read-only requests using GLM with read tool.
        
        GLM will read files and answer directly without ACPX.
        """
        logger.info(f"[ACP-PRE] === READ TOOL MODE ACTIVATED ===")
        logger.info(f"[ACP-PRE] Starting read-only tool call for project '{project_name}' at {project_path}")
        logger.info(f"[ACP-PRE] User message: {user_message[:100]}...")
        system_prompt = f"""You are a helpful assistant for a web app builder called "{project_name}".

The user is asking about their project. You have access to a "read" tool to examine files.

IMPORTANT: 
1. First use the read tool to examine relevant files (package.json, src/, pages/, components/)
2. Then provide a helpful, friendly response based on what you found
3. Be concise but informative
4. If you find any issues, mention them gently

The project is located at: {project_path}

Use the read tool to answer the user's question. Start by reading the project structure."""

        user_prompt = f'User asks: "{user_message}"'
        
        try:
            response = await self._call_glm_with_tools(system_prompt, user_prompt, project_path)
            logger.info(f"[ACP-PRE] Read-only tool call completed successfully (response length={len(response)})")
            logger.info(f"[ACP-PRE] DECISION: Direct Response (Read Tool) - successfully answered without ACPX")
            
            return PreprocessResult(
                intent=IntentType.SIMPLE_QUESTION,
                should_call_acpx=False,  # Don't call ACPX - we answered directly
                enhanced_prompt=None,
                direct_response=response,
                confidence=0.9
            )
            
        except Exception as e:
            logger.warning(f"[ACP-PRE] Read-only tool call failed: {e}, falling back to ACPX")
            logger.warning("[ACP-PRE] DECISION: Use ACPX (Claude) - Read Tool failed, fallback for safety")
            return PreprocessResult(
                intent=IntentType.SIMPLE_QUESTION,
                should_call_acpx=True,  # Fallback to ACPX
                enhanced_prompt=user_message,
                direct_response=None,
                confidence=0.5
            )
    
    def _parse_response(self, response: str, original_message: str) -> PreprocessResult:
        """Parse LLM response into PreprocessResult."""
        logger.debug("[ACP-PRE] Parsing classification response")
        try:
            # Try to extract JSON from response
            response = response.strip()
            if response.startswith("```"):
                # Remove code block markers
                logger.debug("[ACP-PRE] Removing code block markers from response")
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
            logger.debug(f"[ACP-PRE] Parsed intent: {intent_str} -> {intent.value}")
            
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
        logger.info("[ACP-PRE] Creating new preprocessor singleton")
        _preprocessor = ACPPreprocessor()
    return _preprocessor


# Convenience function
async def preprocess_message(user_message: str, project_name: str, project_path: str = None) -> PreprocessResult:
    """
    Preprocess a user message before ACPX.
    
    Args:
        user_message: User's chat message
        project_name: Name of the project
        project_path: Optional path to project root for reading context
        
    Returns:
        PreprocessResult with classification and recommendations
    """
    return await get_preprocessor().classify_intent(user_message, project_name, project_path)
