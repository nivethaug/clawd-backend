"""
Telegram Bot Worker
Main orchestration pipeline for telegram bot deployment.
"""
import os
from pathlib import Path
from typing import Tuple, Dict
from utils.logger import logger

# Import telegram services
from services.telegram.validator import validate_telegram_token
from services.telegram.template import copy_telegram_template
from services.telegram.editor import TelegramBotEditor
from services.telegram.env_injector import inject_bot_token, inject_webhook_config
from services.telegram.installer import install_bot_dependencies
from services.telegram.pm2_manager import start_bot_pm2, get_bot_status_pm2


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
        domain: Webhook domain (without .dreambigwithai.com)
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
            "full_domain": f"{domain}.dreambigwithai.com",
            "port": port,
            "pm2_process": pm2_process,
            "telegram_path": telegram_path,
            "webhook_url": f"https://{domain}.dreambigwithai.com/webhook",
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


def run_telegram_bot_pipeline(
    project_id: int,
    project_name: str,
    description: str,
    bot_token: str,
    project_path: str,
    domain: str,
    port: int,
    database_url: str = None
) -> Tuple[bool, Dict]:
    """
    Run complete telegram bot deployment pipeline.
    
    Args:
        project_id: Project ID
        project_name: Project name
        description: Bot description (for AI enhancement)
        bot_token: Telegram bot token
        project_path: Base project path (e.g., /root/dreampilot/projects/123/)
        domain: Webhook domain (e.g., mybot.dreambigwithai.com)
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
        9. AI enhance logic (Claude edits)
        10. Call buildpublish.py (restarts PM2)
        11. HTTP verify (enhanced works)
    """
    logger.info(f"🚀 Starting Telegram bot pipeline for project {project_id}")
    logger.info(f"Bot name: {project_name}")
    logger.info(f"Domain: {domain}:{port}")
    
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
        logger.info("📋 Step 1/6: Validating bot token...")
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
        logger.info("📋 Step 2/6: Copying telegram template...")
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
        
        # Step 3: Inject environment
        logger.info("📋 Step 3/6: Injecting environment variables...")
        success, env_result = inject_bot_token(telegram_path, bot_token)
        
        if not success:
            error_msg = f"Environment injection failed: {env_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        # Update webhook config (sets WEBHOOK_DOMAIN, WEBHOOK_URL, PORT, PROJECT_ID)
        success, webhook_result = inject_webhook_config(telegram_path, domain, port, project_id)
        if not success:
            logger.warning(f"⚠️ Webhook config injection failed: {webhook_result}")
        
        logger.info(f"✅ Environment configured")
        result_info["steps_completed"].append("env_injection")
        
        # Step 4: Install dependencies
        logger.info("📋 Step 4/11: Installing dependencies...")
        success, install_result = install_bot_dependencies(telegram_path)
        
        if not success:
            error_msg = f"Dependency installation failed: {install_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info
        
        logger.info(f"✅ Dependencies installed")
        result_info["steps_completed"].append("dependency_installation")
        
        # Step 5: Start PM2 (base template works!)
        logger.info("📋 Step 5/11: Starting bot via PM2 (base template)...")
        success, pm2_result = start_bot_pm2(
            project_id, 
            telegram_path, 
            port, 
            domain,
            bot_token=bot_token,
            webhook_url=f"https://{domain}/webhook",
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
        logger.info("📋 Step 6/11: Configuring nginx webhook routing...")
        
        # Verify bot is running
        is_running, status_info = get_bot_status_pm2(project_id)
        result_info["bot_status"] = "running" if is_running else "error"
        result_info["pm2_status"] = status_info
        
        # Step 7: Configure nginx (webhook routing)
        logger.info("📋 Step 7/8: Configuring nginx for webhook...")
        try:
            from infrastructure_manager import NginxConfigurator
            
            nginx = NginxConfigurator()
            full_domain = f"{domain}.dreambigwithai.com"
            
            # Generate telegram bot nginx config
            config_domain, config = nginx.generate_telegram_bot_config(domain, port)
            
            # Install config
            if nginx.install_config(domain, config):
                logger.info(f"✅ Nginx config installed for {full_domain}")
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
        logger.info("📋 Step 8/8: Provisioning DNS (optional)...")
        try:
            from infrastructure_manager import DNSProvisioner
            
            dns = DNSProvisioner()
            
            # Check if DNS skill is available
            if dns.dns_skill_available:
                # Create A record for webhook domain
                dns_result = dns.create_a_record(domain, "dreambigwithai.com", "195.200.14.37")
                
                if dns_result:
                    logger.info(f"✅ DNS A record created for {full_domain}")
                    result_info["steps_completed"].append("dns_provisioning")
                else:
                    logger.warning(f"⚠️ DNS provisioning failed, but wildcard DNS may work")
            else:
                logger.info(f"ℹ️ DNS provisioning skipped (using wildcard DNS)")
                logger.info(f"  Webhook will be available at: https://{full_domain}/webhook")
                result_info["dns_skipped"] = True
        
        except Exception as e:
            logger.warning(f"⚠️ DNS provisioning error: {e} - continuing (wildcard DNS should work)")
            result_info["errors"].append(f"dns_error: {e}")
        
        # Step 8: HTTP verify (base template works)
        logger.info("📋 Step 8/11: HTTP verification (base template)...")
        try:
            import requests
            
            full_domain = f"{domain}.dreambigwithai.com"
            health_url = f"https://{full_domain}/health"
            
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
        
        # Step 9: AI enhance logic (now that base is deployed and working)
        logger.info("📋 Step 9/11: AI enhancement of bot logic...")
        try:
            editor = TelegramBotEditor(telegram_path)
            success, edit_result = editor.enhance_bot_logic(description, project_name)
            
            if success:
                logger.info(f"✅ AI enhancement: {edit_result}")
                result_info["ai_enhancement"] = edit_result
                result_info["steps_completed"].append("ai_enhancement")
            else:
                logger.warning(f"⚠️ AI enhancement failed: {edit_result}")
                result_info["ai_enhancement"] = f"failed: {edit_result}"
                # Continue anyway - base template still works
        
        except Exception as e:
            logger.warning(f"⚠️ AI enhancement error: {e} - continuing with base template")
            result_info["ai_enhancement"] = f"error: {e}"
        
        # Step 10: Call buildpublish.py (restarts PM2 with enhanced code)
        if result_info.get("ai_enhancement") and "failed" not in result_info.get("ai_enhancement", ""):
            logger.info("📋 Step 10/11: Running buildpublish.py (restart PM2)...")
            try:
                import subprocess
                
                # Run buildpublish.py from telegram directory
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
                        logger.debug(f"Output: {result.stdout}")
                        result_info["steps_completed"].append("buildpublish")
                        
                        # Wait for bot to restart
                        logger.info("⏳ Waiting 3s for bot to restart...")
                        time.sleep(3)
                    else:
                        logger.warning(f"⚠️ buildpublish.py failed: {result.stderr}")
                        result_info["errors"].append(f"buildpublish_failed: {result.stderr}")
                else:
                    logger.warning(f"⚠️ buildpublish.py not found at {buildpublish_path}")
            
            except subprocess.TimeoutExpired:
                logger.warning(f"⚠️ buildpublish.py timeout - continuing")
                result_info["errors"].append("buildpublish_timeout")
            except Exception as e:
                logger.warning(f"⚠️ buildpublish.py error: {e} - continuing")
                result_info["errors"].append(f"buildpublish_error: {e}")
        
        # Step 11: HTTP verify (enhanced version works)
        logger.info("📋 Step 11/11: Final HTTP verification (enhanced bot)...")
        try:
            import requests
            import time
            
            # Wait for PM2 restart to complete
            time.sleep(3)
            
            full_domain = f"{domain}.dreambigwithai.com"
            health_url = f"https://{full_domain}/health"
            
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
        # STEP: Register Telegram Webhook (NEW - Safe & Optional)
        # ========================================================================
        
        try:
            from services.telegram.webhook import register_telegram_webhook
            
            logger.info("🔗 Registering Telegram webhook...")
            
            # Register webhook with Telegram API
            webhook_success, webhook_msg = register_telegram_webhook(
                bot_token=bot_token,
                domain=full_domain,
                project_id=project_id
            )
            
            if webhook_success:
                result_info["webhook_registration"] = "success"
                result_info["steps_completed"].append("webhook_registration")
                logger.info(f"✅ Webhook registered: {webhook_msg}")
            else:
                # Non-blocking - don't fail deployment
                result_info["webhook_registration"] = f"failed: {webhook_msg}"
                logger.warning(f"⚠️ Webhook registration failed: {webhook_msg}")
                logger.info("ℹ️ Bot will still work - webhook can be registered manually")
        
        except Exception as e:
            # Non-blocking - don't fail deployment
            logger.warning(f"⚠️ Webhook registration error: {e}")
            result_info["webhook_registration"] = f"error: {e}"
            result_info["errors"].append(f"webhook_registration_error: {e}")
        
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
        logger.info(f"Bot running at: https://{full_domain}")
        logger.info(f"Webhook URL: https://{full_domain}/webhook")
        
        result_info["webhook_url"] = f"https://{full_domain}/webhook"
        result_info["bot_url"] = f"https://{full_domain}"
        
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
        "domain": "test.dreambigwithai.com",
        "port": 8999
    }
    
    success, result = run_telegram_bot_pipeline(**test_config)
    print(f"\nResult: {'SUCCESS' if success else 'FAILED'}")
    print(f"Info: {result}")
