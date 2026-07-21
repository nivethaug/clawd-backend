"""
Telegram Bot Worker
Main orchestration pipeline for telegram bot deployment.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import logging
from utils.logger import logger  # noqa: F811 — reassign below
logger = logging.getLogger("services.telegram.worker")

# Import telegram services
from services.telegram.validator import validate_telegram_token
from services.telegram.template import copy_telegram_template
from services.telegram.editor import TelegramBotEditor
from services.telegram.env_injector import inject_bot_token
from services.telegram.installer import install_bot_dependencies
from services.telegram.pm2_manager import start_bot_pm2, get_bot_status_pm2
from project_initial_env import write_initial_environment_variables

from domain_config import BASE_DOMAIN, SERVER_IP, frontend_domain as _frontend_domain, webhook_url as _webhook_url


def _save_project_metadata(
    project_path: str,
    project_id: int,
    project_name: str,
    bot_username: str,
    domain: str,
    port: int,
    pm2_process: str,
    telegram_path: str
) -> bool:
    """
    Save project metadata to project.json for Telegram bot projects.
    
    This enables proper cleanup during deletion and better project tracking.
    
    Args:
        project_path: Base project path (e.g., /root/dreampilot/projects/123/)
        project_id: Project ID
        project_name: Bot name
        bot_username: Telegram bot username (without @)
        domain: Webhook domain (without .{BASE_DOMAIN})
        port: Webhook server port
        pm2_process: PM2 process name
        telegram_path: Path to telegram bot files
    
    Returns:
        True if saved successfully, False otherwise
    """
    import json
    from datetime import datetime
    
    try:
        metadata = {
            "project_id": project_id,
            "project_name": project_name,
            "type_id": 2,  # Telegram bot type
            "bot_username": bot_username,
            # Note: bot_token is NOT included for security
            "domain": domain,
            "full_domain": f"{domain}-api.{BASE_DOMAIN}",
            "port": port,
            "pm2_process": pm2_process,
            "telegram_path": telegram_path,
            "webhook_url": _webhook_url(domain),
            "status": "ready",
            "created_at": datetime.utcnow().isoformat()
        }
        
        metadata_path = Path(project_path) / "project.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))
        
        logger.info(f"✅ Project metadata saved: {metadata_path}")
        return True
    
    except Exception as e:
        logger.error(f"Failed to save project metadata: {e}")
        return False


def _verify_dns_resolves(domain: str, timeout: int = 5) -> bool:
    """
    Check if a domain resolves (DNS lookup).
    
    Args:
        domain: Domain to check (e.g., mybot.{BASE_DOMAIN})
        timeout: DNS lookup timeout in seconds
    
    Returns:
        True if domain resolves, False otherwise
    """
    try:
        import socket
        # Simple DNS resolution check
        socket.gethostbyname(domain)
        logger.info(f"✅ DNS verification: {domain} resolves successfully")
        return True
    except socket.gaierror:
        logger.warning(f"⚠️ DNS verification failed: {domain} does not resolve")
        return False
    except Exception as e:
        logger.warning(f"⚠️ DNS verification error for {domain}: {e}")
        return False


def run_telegram_bot_pipeline(
    project_id: int,
    project_name: str,
    description: str,
    bot_token: str,
    project_path: str,
    domain: str,
    port: int,
    database_url: str = None,
    initial_environment_variables: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, Dict]:
    """
    Run complete telegram bot deployment pipeline.
    
    Args:
        project_id: Project ID
        project_name: Project name
        description: Bot description (for AI enhancement)
        bot_token: Telegram bot token
        project_path: Base project path (e.g., /root/dreampilot/projects/123/)
        domain: Webhook domain (e.g., mybot.{BASE_DOMAIN})
        port: Port for webhook server
        database_url: Database connection URL (optional)
    
    Returns:
        Tuple of (success, result_info)
    
    Pipeline Steps:
        1. Validate token
        2. Copy template
        3. Inject .env (BOT_TOKEN + webhook config)
        4. Install dependencies
        5. Start PM2 (base template works)
        6. Configure nginx (webhook routing)
        7. Provision DNS (optional - uses wildcard DNS fallback)
        8. HTTP verify (base works)
        9. Register Telegram webhook (with base template - DNS/nginx ready)
        10. AI enhance logic (Claude edits)
        11. Call buildpublish.py (restarts PM2 with enhanced code)
        12. HTTP verify (enhanced works)
    """
    logger.info(f"🚀 Starting Telegram bot pipeline for project {project_id}")
    logger.info(f"Bot name: {project_name}")
    logger.info(f"🔧 Received parameters:")
    logger.info(f"   - domain: '{domain}' (type: {type(domain).__name__})")
    logger.info(f"   - port: {port} (type: {type(port).__name__})")
    logger.info(f"   - project_id: {project_id} (type: {type(project_id).__name__})")
    logger.info(f"   - domain is truthy: {bool(domain)}")
    
    result_info = {
        "project_id": project_id,
        "bot_name": project_name,
        "domain": domain,
        "port": port,
        "steps_completed": [],
        "errors": []
    }
    
    try:
        # Step 1: Validate token
        logger.info("📋 Step 1/12: Validating bot token...")
        is_valid, token_info = validate_telegram_token(bot_token)
        
        if not is_valid:
            error_msg = f"Token validation failed: {token_info.get('error')}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        logger.info(f"✅ Token valid for bot: @{token_info.get('username')}")
        result_info["bot_username"] = token_info.get("username")
        result_info["steps_completed"].append("token_validation")
        
        # Step 2: Copy template
        logger.info("📋 Step 2/12: Copying telegram template...")
        success, template_result = copy_telegram_template(project_path)
        
        if not success:
            error_msg = f"Template copy failed: {template_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        telegram_path = template_result
        logger.info(f"✅ Template copied to {telegram_path}")
        result_info["telegram_path"] = telegram_path
        result_info["steps_completed"].append("template_copy")
        
        # Step 3: Inject environment (BOT_TOKEN + webhook config in one call)
        logger.info("📋 Step 3/12: Injecting environment variables...")
        success, env_result = inject_bot_token(
            project_path=telegram_path,
            bot_token=bot_token,
            domain=domain,
            port=port,
            project_id=project_id,
            database_url=database_url
        )
        
        if not success:
            error_msg = f"Environment injection failed: {env_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        logger.info(f"✅ Environment configured")
        result_info["steps_completed"].append("env_injection")

        initial_env_vars = initial_environment_variables or []
        if initial_env_vars:
            write_initial_environment_variables(str(Path(telegram_path) / ".env"), initial_env_vars)
            logger.info(
                "Initial environment variables applied for telegram project %s: %s",
                project_id,
                [item.get("key") for item in initial_env_vars],
            )
            result_info["steps_completed"].append("initial_env_injection")
        
        # Step 4: Install dependencies
        logger.info("📋 Step 4/12: Installing dependencies...")
        success, install_result = install_bot_dependencies(telegram_path)
        
        if not success:
            error_msg = f"Dependency installation failed: {install_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        logger.info(f"✅ Dependencies installed")
        result_info["steps_completed"].append("dependency_installation")
        
        # Step 5: Start PM2 (base template works!)
        logger.info("📋 Step 5/12: Starting bot via PM2 (base template)...")
        success, pm2_result = start_bot_pm2(
            project_id, 
            telegram_path, 
            port, 
            domain,
            bot_token=bot_token,
            webhook_url=_webhook_url(domain),
            database_url=database_url
        )
        
        if not success:
            error_msg = f"PM2 start failed: {pm2_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        # Track PM2 process name (domain-based or fallback to project_id)
        pm2_process_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
        logger.info(f"✅ Bot started: {pm2_result} (PM2 name: {pm2_process_name})")
        result_info["pm2_process"] = pm2_process_name
        result_info["steps_completed"].append("pm2_start")
        
        # Wait for bot to initialize (prevent 502 errors)
        logger.info("⏳ Waiting 5s for bot to initialize...")
        import time
        time.sleep(5)
        
        # Step 6: Configure nginx
        # Verify bot is running
        is_running, status_info = get_bot_status_pm2(project_id)
        result_info["bot_status"] = "running" if is_running else "error"
        result_info["pm2_status"] = status_info
        
        # Step 6: Configure nginx (webhook routing)
        logger.info("📋 Step 6/12: Configuring nginx for webhook...")
        try:
            from infrastructure_manager import NginxConfigurator

            nginx = NginxConfigurator()
            # Telegram bots use the -api subdomain for webhook (NOT frontend domain).
            # The webhook URL is https://{domain}-api.dreamagent.cloud/webhook
            api_domain = f"{domain}-api"

            # Generate telegram bot nginx config (uses -api domain)
            config_domain, config = nginx.generate_telegram_bot_config(api_domain, port)

            # Install config (named after the -api domain)
            if nginx.install_config(api_domain, config):
                logger.info(f"✅ Nginx config installed for {api_domain}.{BASE_DOMAIN}")
                result_info["steps_completed"].append("nginx_config")

                # Reload nginx
                if nginx.reload_nginx():
                    logger.info(f"✅ Nginx reloaded successfully")
                else:
                    logger.warning(f"⚠️ Nginx reload failed, but config installed")
            else:
                logger.warning(f"⚠️ Failed to install nginx config, continuing...")
                result_info["errors"].append("nginx_config_install_failed")
        
        except Exception as e:
            logger.warning(f"⚠️ Nginx configuration error: {e} - continuing without nginx")
            result_info["errors"].append(f"nginx_error: {e}")
        
        # Step 8: Provision DNS (optional - uses wildcard DNS)
        logger.info("📋 Step 7/12: Provisioning DNS (optional)...")
        try:
            from infrastructure_manager import DNSProvisioner

            dns = DNSProvisioner()

            # Check if DNS skill is available
            if dns.dns_skill_available:
                # Telegram bots only have a backend/API domain (no frontend).
                # The webhook URL is https://{domain}-api.dreamagent.cloud/webhook
                # so we only need ONE DNS record for the -api subdomain.
                api_domain = f"{domain}-api"
                api_dns_result = dns.create_a_record(api_domain, BASE_DOMAIN, SERVER_IP)
                if api_dns_result:
                    logger.info(f"✅ DNS A record created for webhook: {api_domain}.{BASE_DOMAIN}")
                    result_info["steps_completed"].append("dns_provisioning")
                else:
                    logger.warning(f"⚠️ DNS provisioning failed for {api_domain} — webhook may not work")
            else:
                logger.info(f"ℹ️ DNS provisioning skipped (using wildcard DNS)")
                logger.info(f"  Webhook will be available at: https://{domain}-api.{BASE_DOMAIN}/webhook")
                result_info["dns_skipped"] = True
        
        except Exception as e:
            logger.warning(f"⚠️ DNS provisioning error: {e} - continuing (wildcard DNS should work)")
            result_info["errors"].append(f"dns_error: {e}")
        
        # Step 8: HTTP verify (base template works)
        logger.info("📋 Step 8/12: HTTP verification (base template)...")
        try:
            import requests

            # Health check uses the -api domain (same as webhook + nginx config)
            api_full_domain = f"{domain}-api.{BASE_DOMAIN}"
            health_url = f"https://{api_full_domain}/health"
            
            # Fast HTTP check (< 1 second)
            response = requests.get(health_url, timeout=10, verify=True)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    logger.info(f"✅ Base template verified - bot is running!")
                    result_info["base_verification"] = "success"
                    result_info["steps_completed"].append("base_verification")
                else:
                    logger.warning(f"⚠️ Health check returned unexpected data: {data}")
                    result_info["base_verification"] = f"warning: {data}"
            else:
                logger.warning(f"⚠️ Health check failed with status {response.status_code}")
                result_info["base_verification"] = f"failed: status {response.status_code}"
        
        except requests.exceptions.SSLError:
            logger.error(f"❌ SSL certificate error - critical failure")
            result_info["errors"].append("ssl_error")
            result_info["base_verification"] = "ssl_error"
        except Exception as e:
            logger.warning(f"⚠️ HTTP verification error: {e} - continuing")
            result_info["base_verification"] = f"error: {e}"
        
        # ========================================================================
        # STEP 9: Register Telegram Webhook (Async with Retries)
        # ========================================================================
        # Register webhook asynchronously with DNS propagation retries.
        # This doesn't block deployment - webhook will be registered in background.
        # Telegram's servers may take 5-60 minutes to see DNS, so we retry with
        # exponential backoff (10s, 20s, 40s, 80s, 160s, 320s).
        # ========================================================================
        
        try:
            from services.telegram.webhook import register_webhook_async
            
            logger.info("🔗 Starting async Telegram webhook registration...")
            logger.info("📋 Step 9/12: Telegram webhook registration (async)")
            
            # Verify DNS resolves locally first (use -api domain)
            api_full_domain = f"{domain}-api.{BASE_DOMAIN}"
            dns_resolves = _verify_dns_resolves(api_full_domain)
            if not dns_resolves:
                logger.warning(f"⚠️ DNS not resolving locally for {api_full_domain}")
                logger.info("ℹ️ Starting async registration anyway (Telegram's DNS may differ)")
                result_info["dns_verification"] = "local_failed"
            else:
                logger.info(f"✅ Local DNS verification passed for {api_full_domain}")
                result_info["dns_verification"] = "success"

            # Start async webhook registration with retries
            register_webhook_async(
                bot_token=bot_token,
                domain=domain,
                project_id=project_id,
                max_retries=9,
                initial_delay=10
            )
            
            result_info["webhook_registration"] = "async_started"
            result_info["steps_completed"].append("webhook_registration")
            logger.info(f"✅ Webhook registration started in background (will retry up to 9 times)")
            logger.info(f"ℹ️ Bot deployment continuing - webhook will activate when DNS propagates")
        
        except Exception as e:
            # Non-blocking - don't fail deployment
            logger.warning(f"⚠️ Webhook registration error: {e}")
            result_info["webhook_registration"] = f"error: {e}"
            result_info["errors"].append(f"webhook_registration_error: {e}")
            logger.info("ℹ️ Bot will still work - webhook can be registered manually")
        
        # Step 10: AI enhance logic (now that base is deployed and working)
        logger.info("📋 Step 10/12: AI enhancement of bot logic...")
        try:
            editor = TelegramBotEditor(telegram_path, project_id=project_id)
            success, edit_result = editor.enhance_bot_logic(description, project_name)
            
            if success:
                logger.info(f"✅ AI enhancement: {edit_result}")
                result_info["ai_enhancement"] = edit_result
                result_info["steps_completed"].append("ai_enhancement")

                # Record token usage
                try:
                    from services.token_tracker import record_from_token_usage_json
                    from database_adapter import get_db
                    usage = getattr(editor, '_last_token_usage', None)
                    if usage:
                        with get_db() as conn:
                            row = conn.execute(
                                "SELECT user_id FROM projects WHERE id = %s", (project_id,)
                            ).fetchone()
                        _uid = row["user_id"] if row else None
                        if _uid:
                            record_from_token_usage_json(
                                user_id=_uid,
                                token_usage_json=usage,
                                usage_type="project_create",
                                project_id=project_id,
                                description=f"Telegram bot create: {project_name}",
                            )
                            logger.info(f"✅ Token usage recorded for telegram create")
                except Exception as track_err:
                    logger.warning(f"Token tracking failed: {track_err}")
            else:
                logger.warning(f"⚠️ AI enhancement failed: {edit_result}")
                result_info["ai_enhancement"] = f"failed: {edit_result}"
                # Continue anyway - base template still works
        
        except Exception as e:
            logger.warning(f"⚠️ AI enhancement error: {e} - continuing with base template")
            result_info["ai_enhancement"] = f"error: {e}"
        
        # Step 12: Call buildpublish.py (restarts PM2 with enhanced code)
        if result_info.get("ai_enhancement") and "failed" not in result_info.get("ai_enhancement", ""):
            logger.info("📋 Step 11/12: Running buildpublish.py (restart PM2)...")

            # First try: run buildpublish.py from the project directory.
            # On the host this has direct PM2 access.
            buildpublish_ok = False
            try:
                import subprocess

                buildpublish_path = Path(telegram_path) / "buildpublish.py"

                if buildpublish_path.exists():
                    result = subprocess.run(
                        ["python3", str(buildpublish_path)],
                        cwd=telegram_path,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    if result.returncode == 0:
                        logger.info(f"✅ buildpublish.py completed successfully")
                        buildpublish_ok = True
                        result_info["steps_completed"].append("buildpublish")
                    else:
                        logger.warning(f"⚠️ buildpublish.py failed: {result.stderr[:300]}")
                else:
                    logger.warning(f"⚠️ buildpublish.py not found at {buildpublish_path}")
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️ buildpublish.py timeout - continuing")
                result_info["errors"].append("buildpublish_timeout")
            except Exception as e:
                logger.warning(f"⚠️ buildpublish.py error: {e} - continuing")
                result_info["errors"].append(f"buildpublish_error: {e}")

            # Fallback: if buildpublish failed or wasn't found, restart PM2 directly.
            # The worker runs on the host with full PM2 access — no need for the
            # worker-api detour.
            if not buildpublish_ok:
                pm2_name = f"{domain}-bot" if domain else f"tg-bot-{project_id}"
                logger.info(f"🔄 Direct PM2 restart fallback: {pm2_name}")
                try:
                    restart_result = subprocess.run(
                        ["pm2", "restart", pm2_name, "--update-env"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if restart_result.returncode == 0:
                        logger.info(f"✅ PM2 restarted directly: {pm2_name}")
                        buildpublish_ok = True
                        result_info["steps_completed"].append("pm2_restart_fallback")
                    else:
                        # Try old naming convention
                        fallback_name = f"tg-bot-{project_id}"
                        logger.info(f"🔄 Trying fallback PM2 name: {fallback_name}")
                        restart2 = subprocess.run(
                            ["pm2", "restart", fallback_name, "--update-env"],
                            capture_output=True, text=True, timeout=30,
                        )
                        if restart2.returncode == 0:
                            logger.info(f"✅ PM2 restarted: {fallback_name}")
                            buildpublish_ok = True
                        else:
                            logger.error(f"❌ PM2 restart failed: {restart_result.stderr[:300]}")
                            result_info["errors"].append("pm2_restart_failed")
                except Exception as pm2_err:
                    logger.error(f"❌ PM2 restart error: {pm2_err}")
                    result_info["errors"].append(f"pm2_restart_error: {pm2_err}")

            # Wait for bot to restart either way
            if buildpublish_ok:
                logger.info(f"⏳ Waiting 3s for bot to restart...")
                time.sleep(3)

        # Step 13: HTTP verify (enhanced version works)
        logger.info("📋 Step 12/12: Final HTTP verification (enhanced bot)...")
        try:
            import requests
            import time
            
            # Wait for PM2 restart to complete
            time.sleep(3)

            # Health check uses -api domain (same as nginx config + webhook)
            api_full_domain = f"{domain}-api.{BASE_DOMAIN}"
            health_url = f"https://{api_full_domain}/health"
            
            # Fast HTTP check
            response = requests.get(health_url, timeout=10, verify=True)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    logger.info(f"✅ Enhanced bot verified - deployment complete!")
                    result_info["final_verification"] = "success"
                    result_info["steps_completed"].append("final_verification")
                else:
                    logger.warning(f"⚠️ Enhanced bot returned unexpected data: {data}")
                    result_info["final_verification"] = f"warning: {data}"
            else:
                logger.warning(f"⚠️ Final verification failed with status {response.status_code}")
                result_info["final_verification"] = f"failed: status {response.status_code}"
                
                # Check PM2 logs to diagnose crash
                logger.error(f"❌ Bot may have crashed after AI enhancement")
                logger.info(f"🔍 Checking PM2 logs for errors...")
                try:
                    pm2_logs = subprocess.run(
                        ["pm2", "logs", pm2_process_name, "--lines", "30", "--nostream"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if pm2_logs.stdout:
                        # Check for error patterns
                        error_patterns = ["Error", "Exception", "Traceback", "ModuleNotFoundError", "SyntaxError"]
                        has_errors = any(pattern in pm2_logs.stdout for pattern in error_patterns)
                        
                        if has_errors:
                            logger.error(f"🔴 PM2 error logs:\n{pm2_logs.stdout[:2000]}")
                            result_info["pm2_error_logs"] = pm2_logs.stdout[:1000]
                        else:
                            logger.info(f"ℹ️ PM2 logs (no errors detected):\n{pm2_logs.stdout[:500]}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not fetch PM2 logs: {e}")
                
                # SKIP: Claude agent verification for now (too complex, often fails)
                # TODO: Re-enable after improving verifier reliability
                logger.info("⏭️ Skipping Claude agent verification (disabled for now)")
                result_info["claude_fix"] = "skipped"
        
        except requests.exceptions.SSLError:
            logger.error(f"❌ SSL certificate error in final verification")
            result_info["errors"].append("ssl_error_final")
            result_info["final_verification"] = "ssl_error"
        except Exception as e:
            logger.warning(f"⚠️ Final verification error: {e}")
            result_info["final_verification"] = f"error: {e}"
        
        # ========================================================================
        # STEP: Save Project Metadata (for cleanup support)
        # ========================================================================
        
        logger.info("💾 Saving project metadata...")
        _save_project_metadata(
            project_path=project_path,
            project_id=project_id,
            project_name=project_name,
            bot_username=result_info.get("bot_username", ""),
            domain=domain,
            port=port,
            pm2_process=pm2_process_name,
            telegram_path=telegram_path
        )
        
        # ========================================================================
        # Final success
        # ========================================================================
        
        logger.info(f"🎉 Telegram bot pipeline completed!")
        logger.info(f"Bot running at: https://{domain}-api.{BASE_DOMAIN}")
        logger.info(f"Webhook URL: {_webhook_url(domain)}")

        result_info["webhook_url"] = _webhook_url(domain)
        result_info["bot_url"] = f"https://{domain}-api.{BASE_DOMAIN}"
        
        return True, result_info
    
    except Exception as e:
        error_msg = f"Pipeline error: {e}"
        logger.error(f"❌ {error_msg}")
        result_info["errors"].append(error_msg)
        return False, result_info


def run_telegram_bot_worker_background(
    project_id: int,
    project_name: str,
    description: str,
    bot_token: str,
    project_path: str,
    domain: str,
    port: int
):
    """
    Background worker entry point for telegram bot deployment.
    Updates project status in database as pipeline progresses.
    
    Args:
        Same as run_telegram_bot_pipeline
    """
    from database_adapter import update_project_status
    
    logger.info(f"🔄 Background worker started for telegram bot {project_id}")
    
    # Update status to "creating"
    update_project_status(project_id, "creating")
    
    try:
        # Run pipeline
        success, result_info = run_telegram_bot_pipeline(
            project_id=project_id,
            project_name=project_name,
            description=description,
            bot_token=bot_token,
            project_path=project_path,
            domain=domain,
            port=port
        )
        
        if success:
            # Update status to "ready"
            update_project_status(project_id, "ready")
            logger.info(f"✅ Project {project_id} status updated to 'ready'")
        else:
            # Update status to "failed"
            update_project_status(project_id, "failed")
            logger.error(f"❌ Project {project_id} status updated to 'failed'")
            logger.error(f"Errors: {result_info.get('errors')}")
    
    except Exception as e:
        logger.error(f"❌ Background worker error: {e}")
        update_project_status(project_id, "failed")


# For running directly (testing)
if __name__ == "__main__":
    # Test pipeline
    test_config = {
        "project_id": 999,
        "project_name": "TestBot",
        "description": "crypto price tracker",
        "bot_token": "test_token",
        "project_path": "/tmp/test-telegram",
        "domain": f"test.{BASE_DOMAIN}",
        "port": 8999
    }
    
    success, result = run_telegram_bot_pipeline(**test_config)
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    print(f"Info: {result}")
