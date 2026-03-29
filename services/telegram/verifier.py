"""
Telegram Bot Webhook Verification Module
Uses Claude Code Agent (with Chrome DevTools MCP) to verify deployed webhook endpoints.

Verification Steps:
1. Claude agent navigates to health endpoint
2. Takes snapshot (verify JSON response)
3. Checks console for errors
4. Checks network requests
5. Navigates to root endpoint
6. Verifies JSON response
7. Takes screenshot (WebP 75%)
8. Closes page

Token-efficient approach:
- Use snapshot (not screenshot) for verification
- Filter console messages (errors only)
- Filter network requests (API only, no static)
- Use WebP 75% for final proof screenshot
"""

import json
import logging
import asyncio
from typing import Tuple, Dict, Any, Optional
from pathlib import Path

# Import Claude Code Agent
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from claude_code_agent import ClaudeCodeAgent

logger = logging.getLogger(__name__)


class WebhookVerificationError(Exception):
    """Custom exception for webhook verification failures."""
    pass


async def verify_telegram_bot_webhook(domain: str, timeout: int = 120, max_retries: int = 2) -> Tuple[bool, Dict[str, Any]]:
    """
    Verify Telegram bot webhook endpoints using Claude Code Agent with Chrome DevTools MCP.
    
    If verification fails, Claude agent will attempt to diagnose and fix issues, then retest.
    
    Args:
        domain: Full domain (e.g., "mybot-api.dreambigwithai.com")
        timeout: Timeout in seconds for verification (default: 120)
        max_retries: Maximum number of retry attempts if verification fails (default: 2)
    
    Returns:
        Tuple of (success, verification_info)
        
    verification_info contains:
        - health_status: bool
        - root_status: bool
        - console_errors: List[str]
        - network_errors: List[str]
        - ssl_valid: bool
        - screenshot: Optional[str] (base64 WebP)
        - agent_response: str (full Claude agent response)
        - retry_count: int (number of retries attempted)
        - fixes_applied: List[str] (description of fixes Claude applied)
        - error: Optional[str]
    """
    verification_info = {
        "health_status": False,
        "root_status": False,
        "console_errors": [],
        "network_errors": [],
        "ssl_valid": False,
        "screenshot": None,
        "agent_response": None,
        "retry_count": 0,
        "fixes_applied": [],
        "error": None
    }
    
    retry_count = 0
    
    while retry_count <= max_retries:
        try:
            # Log attempt
            logger.info("="*60)
            if retry_count == 0:
                logger.info("🔍 TELEGRAM BOT VERIFICATION - CLAUDE AGENT")
                logger.info("="*60)
                logger.info(f"Domain: {domain}")
                logger.info(f"Timeout: {timeout}s")
                logger.info(f"Max retries: {max_retries}")
            else:
                logger.info(f"🔄 RETRY attempt {retry_count}/{max_retries}")
            logger.info("="*60)
            
            # Build verification prompt for Claude agent
            if retry_count == 0:
                # Initial verification prompt
                verification_prompt = f"""Verify the Telegram bot webhook endpoints for domain: {domain}

Use Chrome DevTools MCP to perform these verification steps:

1. **Open health endpoint**: Navigate to https://{domain}/health
2. **Verify health JSON**: Take a snapshot and confirm it returns:
   {{{{ "status": "healthy", "service": "telegram-bot" }}}}
3. **Check console errors**: List console messages (filter: errors only)
4. **Check network requests**: List network requests (filter: no static files)
5. **Navigate to root endpoint**: Go to https://{domain}/
6. **Verify root JSON**: Take a snapshot and confirm it returns:
   {{{{ "message": "Telegram Bot API", "docs": "/docs" }}}}
7. **Take screenshot**: Capture WebP screenshot at 75% quality
8. **Close browser page**: MANDATORY - always close when done

**Token-efficient approach**:
- Use `take_snapshot()` (not screenshot) for verification
- Filter console messages: `types: ["error"]`
- Filter network requests: `includeStatic: false`
- Use WebP 75% for final screenshot

**Return format**:
Return a JSON object with these fields:
{{{{
  "health_status": boolean,
  "root_status": boolean,
  "console_errors": [list of error messages],
  "network_errors": [list of failed requests with status >= 400],
  "ssl_valid": boolean,
  "screenshot": "base64 WebP string (or null)",
  "success": boolean,
  "summary": "Brief summary of verification results"
}}}}

**Important**:
- ALWAYS close the browser page when done (use close_page)
- If any step fails, continue with remaining steps
- SSL is valid if we can successfully load https://{domain}
- Report all console errors and failed network requests"""
            else:
                # Retry prompt: diagnose and fix issues
                previous_errors = []
                if not verification_info["health_status"]:
                    previous_errors.append("Health endpoint check failed")
                if not verification_info["root_status"]:
                    previous_errors.append("Root endpoint check failed")
                if verification_info["console_errors"]:
                    previous_errors.append(f"Console errors: {verification_info['console_errors']}")
                if verification_info["network_errors"]:
                    previous_errors.append(f"Network errors: {verification_info['network_errors']}")
                
                verification_prompt = f"""Previous verification failed for {domain}. Issues detected:
{chr(10).join(f'- {err}' for err in previous_errors)}

**Your task**: Diagnose and fix the issues, then retest.

**Steps**:
1. **Diagnose**: Check PM2 logs, nginx logs, or application code to identify root cause
   - Use terminal commands to check logs: `pm2 logs <app-name>`, `sudo tail -f /var/log/nginx/error.log`
   - Check if process is running: `pm2 list`
   - Verify nginx config: `sudo nginx -t`
   
2. **Fix**: Apply necessary fixes
   - If code error: Fix the Python/FastAPI code
   - If nginx error: Fix nginx configuration
   - If PM2 error: Restart the service
   
3. **Retest**: After fixing, perform full verification again:
   - Open https://{domain}/health and verify JSON response
   - Open https://{domain}/ and verify JSON response
   - Check console errors and network requests
   - Take screenshot (WebP 75%)
   - Close browser page

**Return format** (same as before):
{{{{
  "health_status": boolean,
  "root_status": boolean,
  "console_errors": [list],
  "network_errors": [list],
  "ssl_valid": boolean,
  "screenshot": "base64 WebP or null",
  "success": boolean,
  "fixes_applied": ["list of fixes you applied"],
  "summary": "Brief summary"
}}}}

**Important**: If you cannot fix the issue, explain why in the summary field."""

            # Get repository path (use backend directory as workspace)
            repo_path = str(Path(__file__).parent.parent.parent)
            logger.info(f"📁 Repository path: {repo_path}")
            
            # Run Claude Code Agent with verification prompt
            logger.info("\n" + "="*60)
            logger.info("🤖 INVOKING CLAUDE CODE AGENT")
            logger.info("="*60)
            
            agent_response_text = []
            
            def on_text_callback(text: str):
                """Capture agent response text."""
                agent_response_text.append(text)
                logger.debug(f"[Claude Agent]: {text[:100]}...")
            
            async with ClaudeCodeAgent(
                repo_path=repo_path,
                on_text=on_text_callback,
                progress_interval=30.0
            ) as agent:
                response = await agent.query(verification_prompt, timeout=timeout)
                
                if response:
                    verification_info["agent_response"] = response
                    logger.info(f"✅ Claude agent completed verification (attempt {retry_count + 1})")
                    logger.debug(f"Agent response: {response[:500]}...")
                    
                    # Try to parse JSON from response
                    logger.info("\n📋 Parsing verification results from agent response...")
                    try:
                        # Look for JSON in response (might be wrapped in markdown)
                        json_match = None
                        import re
                        
                        # Try to find JSON code block
                        json_block_pattern = r'```(?:json)?\s*(\{{.*?\}})\s*```'
                        json_match = re.search(json_block_pattern, response, re.DOTALL)
                        
                        if json_match:
                            json_str = json_match.group(1)
                        else:
                            # Try to find raw JSON object
                            json_pattern = r'\{{[^{}]*"health_status"[^{}]*\}}'
                            json_match = re.search(json_pattern, response, re.DOTALL)
                            if json_match:
                                json_str = json_match.group(0)
                            else:
                                # Use entire response as JSON
                                json_str = response.strip()
                        
                        # Parse JSON
                        result_data = json.loads(json_str)
                        
                        # Extract verification results
                        verification_info["health_status"] = result_data.get("health_status", False)
                        verification_info["root_status"] = result_data.get("root_status", False)
                        verification_info["console_errors"] = result_data.get("console_errors", [])
                        verification_info["network_errors"] = result_data.get("network_errors", [])
                        verification_info["ssl_valid"] = result_data.get("ssl_valid", False)
                        verification_info["screenshot"] = result_data.get("screenshot")
                        
                        # Track fixes applied (if any)
                        if "fixes_applied" in result_data:
                            verification_info["fixes_applied"].extend(result_data["fixes_applied"])
                        
                        logger.info(f"✅ Parsed verification results from agent response")
                        logger.info(f"   - Health: {verification_info['health_status']}")
                        logger.info(f"   - Root: {verification_info['root_status']}")
                        logger.info(f"   - SSL: {verification_info['ssl_valid']}")
                        logger.info(f"   - Console errors: {len(verification_info['console_errors'])}")
                        logger.info(f"   - Network errors: {len(verification_info['network_errors'])}")
                        if verification_info["fixes_applied"]:
                            logger.info(f"   - Fixes applied: {verification_info['fixes_applied']}")
                    
                    except (json.JSONDecodeError, AttributeError) as e:
                        logger.warning(f"⚠️ Could not parse JSON from agent response: {e}")
                        logger.warning(f"Response preview: {response[:500]}")
                        # Try to extract status from text if JSON parsing failed
                        response_lower = response.lower()
                        if "health_status" in response_lower and "true" in response_lower:
                            verification_info["health_status"] = True
                        if "root_status" in response_lower and "true" in response_lower:
                            verification_info["root_status"] = True
                        if "ssl" in response_lower and ("valid" in response_lower or "working" in response_lower):
                            verification_info["ssl_valid"] = True
                        
                        # Track if fixes were mentioned
                        if "fixed" in response_lower or "applied fix" in response_lower:
                            verification_info["fixes_applied"].append("Fix applied (detected from response text)")
                else:
                    error_msg = f"Claude agent returned no response (attempt {retry_count + 1})"
                    logger.error(f"❌ {error_msg}")
                    verification_info["error"] = error_msg
                    # Don't return yet - allow retry
            
            # Determine overall success
            success = (
                verification_info["health_status"] and
                verification_info["root_status"] and
                len(verification_info["console_errors"]) == 0 and
                len(verification_info["network_errors"]) == 0
            )
            
            if success:
                logger.info(f"✅ Webhook verification successful for {domain} (attempt {retry_count + 1})")
                if retry_count > 0:
                    logger.info(f"   Verification succeeded after {retry_count} retry attempt(s)")
                return (True, verification_info)
            else:
                # Verification failed - check if we should retry
                if retry_count < max_retries:
                    logger.warning(f"⚠️ Verification failed (attempt {retry_count + 1}), will retry...")
                    retry_count += 1
                    # Continue loop to retry
                else:
                    # No more retries
                    logger.error(f"❌ Verification failed after {retry_count + 1} attempts for {domain}")
                    verification_info["error"] = f"Verification failed after {retry_count + 1} attempts"
                    return (False, verification_info)
                    
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ Verification timeout (attempt {retry_count + 1})")
            if retry_count < max_retries:
                retry_count += 1
                # Continue loop to retry
            else:
                error_msg = f"Verification timeout after {timeout} seconds (all {max_retries + 1} attempts)"
                logger.error(f"❌ {error_msg}")
                verification_info["error"] = error_msg
                return (False, verification_info)
        
        except Exception as e:
            error_msg = f"Verification error on attempt {retry_count + 1}: {e}"
            logger.error(f"❌ {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            
            if retry_count < max_retries:
                logger.info(f"🔄 Will retry after error...")
                retry_count += 1
                # Continue loop to retry
            else:
                verification_info["error"] = error_msg
                return (False, verification_info)
    
    # Should not reach here, but just in case
    logger.error("❌ Unexpected exit from verification loop")
    return (False, verification_info)


async def _fallback_http_verification(domain: str, verification_info: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    Fallback HTTP verification when Chrome DevTools MCP is not available.
    
    Uses simple HTTP requests to verify endpoints.
    """
    try:
        import requests
        
        logger.info("🔄 Using HTTP fallback verification")
        
        # Check health endpoint
        health_url = f"https://{domain}/health"
        try:
            response = requests.get(health_url, timeout=10, verify=True)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    verification_info["health_status"] = True
                    verification_info["ssl_valid"] = True
                    logger.info(f"✅ Health endpoint verified (HTTP fallback)")
                else:
                    logger.warning(f"⚠️ Health endpoint returned unexpected data: {data}")
            else:
                logger.warning(f"⚠️ Health endpoint returned status {response.status_code}")
        except requests.exceptions.SSLError:
            logger.error(f"❌ SSL certificate error for {domain}")
            verification_info["error"] = "SSL certificate invalid"
        except Exception as e:
            logger.warning(f"⚠️ Health endpoint check failed: {e}")
        
        # Check root endpoint
        root_url = f"https://{domain}/"
        try:
            response = requests.get(root_url, timeout=10, verify=True)
            if response.status_code == 200:
                data = response.json()
                if "message" in data and "Telegram Bot API" in data.get("message", ""):
                    verification_info["root_status"] = True
                    logger.info(f"✅ Root endpoint verified (HTTP fallback)")
                else:
                    logger.warning(f"⚠️ Root endpoint returned unexpected data: {data}")
            else:
                logger.warning(f"⚠️ Root endpoint returned status {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Root endpoint check failed: {e}")
        
        # Determine overall success
        success = verification_info["health_status"] and verification_info["root_status"]
        
        if success:
            logger.info(f"✅ HTTP fallback verification successful for {domain}")
        else:
            logger.warning(f"⚠️ HTTP fallback verification completed with issues for {domain}")
        
        return (success, verification_info)
        
    except ImportError:
        error_msg = "Requests library not available for HTTP fallback"
        logger.error(f"❌ {error_msg}")
        verification_info["error"] = error_msg
        return (False, verification_info)
    except Exception as e:
        error_msg = f"HTTP fallback verification error: {e}"
        logger.error(f"❌ {error_msg}")
        verification_info["error"] = error_msg
        return (False, verification_info)


def verify_telegram_bot_webhook_sync(domain: str, timeout: int = 120, max_retries: int = 2) -> Tuple[bool, Dict[str, Any]]:
    """
    Synchronous wrapper for verify_telegram_bot_webhook.
    
    Args:
        domain: Full domain (e.g., "mybot-api.dreambigwithai.com")
        timeout: Timeout in seconds for verification (default: 120)
        max_retries: Maximum number of retry attempts (default: 2)
    
    Returns:
        Tuple of (success, verification_info)
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(verify_telegram_bot_webhook(domain, timeout, max_retries))


if __name__ == "__main__":
    # Test verification
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python verifier.py <domain>")
        print("Example: python verifier.py mybot-api.dreambigwithai.com")
        sys.exit(1)
    
    domain = sys.argv[1]
    success, info = verify_telegram_bot_webhook_sync(domain)
    
    print("\n" + "="*60)
    print("VERIFICATION RESULTS")
    print("="*60)
    print(f"Domain: {domain}")
    print(f"Success: {'✅ YES' if success else '❌ NO'}")
    print(f"Health Status: {'✅' if info['health_status'] else '❌'}")
    print(f"Root Status: {'✅' if info['root_status'] else '❌'}")
    print(f"SSL Valid: {'✅' if info['ssl_valid'] else '❌'}")
    
    if info['console_errors']:
        print(f"\nConsole Errors ({len(info['console_errors'])}):")
        for error in info['console_errors']:
            print(f"  - {error}")
    
    if info['network_errors']:
        print(f"\nNetwork Errors ({len(info['network_errors'])}):")
        for error in info['network_errors']:
            print(f"  - {error}")
    
    if info['error']:
        print(f"\nError: {info['error']}")
    
    if info['screenshot']:
        print(f"\nScreenshot: ✅ Captured (WebP 75%)")
    
    print("="*60)
    sys.exit(0 if success else 1)
