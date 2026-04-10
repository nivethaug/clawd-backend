"""
Discord Bot Worker
Main orchestration pipeline for discord bot deployment.
"""
import os
import time
from pathlib import Path
from typing import Tuple, Dict
from utils.logger import logger

# Import discord services
from services.discord.validator import validate_discord_token
from services.discord.template import copy_discord_template
from services.discord.editor import DiscordBotEditor
from services.discord.env_injector import inject_bot_token
from services.discord.installer import install_bot_dependencies
from services.discord.pm2_manager import start_bot_pm2, get_bot_status_pm2


def _save_project_metadata(
    project_path: str,
    project_id: int,
    project_name: str,
    bot_username: str,
    domain: str,
    port: int,
    pm2_process: str,
    discord_path: str
) -> bool:
    """
    Save project metadata to project.json for Discord bot projects.

    Args:
        project_path: Base project path
        project_id: Project ID
        project_name: Bot name
        bot_username: Discord bot username
        domain: Domain
        port: Health server port
        pm2_process: PM2 process name
        discord_path: Path to discord bot files

    Returns:
        True if saved successfully, False otherwise
    """
    import json
    from datetime import datetime

    try:
        metadata = {
            "project_id": project_id,
            "project_name": project_name,
            "type_id": 3,  # Discord bot type
            "bot_username": bot_username,
            "domain": domain,
            "full_domain": f"{domain}.dreambigwithai.com" if domain and '.' not in domain else domain,
            "port": port,
            "pm2_process": pm2_process,
            "discord_path": discord_path,
            "status": "ready",
            "created_at": datetime.utcnow().isoformat()
        }

        metadata_path = Path(project_path) / "project.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        logger.info(f"Project metadata saved: {metadata_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save project metadata: {e}")
        return False


def _verify_dns_resolves(domain: str, timeout: int = 5) -> bool:
    """Check if a domain resolves."""
    try:
        import socket
        socket.gethostbyname(domain)
        logger.info(f"DNS verification: {domain} resolves successfully")
        return True
    except socket.gaierror:
        logger.warning(f"DNS verification failed: {domain} does not resolve")
        return False
    except Exception as e:
        logger.warning(f"DNS verification error for {domain}: {e}")
        return False


def run_discord_bot_pipeline(
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
    Run complete discord bot deployment pipeline.

    Args:
        project_id: Project ID
        project_name: Project name
        description: Bot description (for AI enhancement)
        bot_token: Discord bot token
        project_path: Base project path
        domain: Domain
        port: Port for health server
        database_url: Database connection URL (optional)

    Returns:
        Tuple of (success, result_info)
    """
    logger.info(f"Starting Discord bot pipeline for project {project_id}")
    logger.info(f"Bot name: {project_name}")

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
        logger.info("Step 1/12: Validating bot token...")
        is_valid, token_info = validate_discord_token(bot_token)

        if not is_valid:
            error_msg = f"Token validation failed: {token_info.get('error')}"
            logger.error(error_msg)
            result_info["errors"].append(error_msg)
            return False, result_info

        logger.info(f"Token valid for bot: {token_info.get('username')}")
        result_info["bot_username"] = token_info.get("username")
        result_info["steps_completed"].append("token_validation")

        # Step 2: Copy template
        logger.info("Step 2/12: Copying discord template...")
        success, template_result = copy_discord_template(project_path)

        if not success:
            error_msg = f"Template copy failed: {template_result}"
            logger.error(error_msg)
            result_info["errors"].append(error_msg)
            return False, result_info

        discord_path = template_result
        logger.info(f"Template copied to {discord_path}")
        result_info["discord_path"] = discord_path
        result_info["steps_completed"].append("template_copy")

        # Step 3: Inject environment
        logger.info("Step 3/12: Injecting environment variables...")
        success, env_result = inject_bot_token(
            project_path=discord_path,
            bot_token=bot_token,
            domain=domain,
            port=port,
            project_id=project_id,
            database_url=database_url
        )

        if not success:
            error_msg = f"Environment injection failed: {env_result}"
            logger.error(error_msg)
            result_info["errors"].append(error_msg)
            return False, result_info

        logger.info("Environment configured")
        result_info["steps_completed"].append("env_injection")

        # Step 4: Install dependencies
        logger.info("Step 4/12: Installing dependencies...")
        success, install_result = install_bot_dependencies(discord_path)

        if not success:
            error_msg = f"Dependency installation failed: {install_result}"
            logger.error(error_msg)
            result_info["errors"].append(error_msg)
            return False, result_info

        logger.info("Dependencies installed")
        result_info["steps_completed"].append("dependency_installation")

        # Step 5: Start PM2
        logger.info("Step 5/12: Starting bot via PM2...")
        success, pm2_result = start_bot_pm2(
            project_id,
            discord_path,
            port,
            domain=domain,
            bot_token=bot_token,
            database_url=database_url
        )

        if not success:
            error_msg = f"PM2 start failed: {pm2_result}"
            logger.error(error_msg)
            result_info["errors"].append(error_msg)
            return False, result_info

        pm2_process_name = f"dc-bot-{project_id}"
        logger.info(f"Bot started: {pm2_result} (PM2 name: {pm2_process_name})")
        result_info["pm2_process"] = pm2_process_name
        result_info["steps_completed"].append("pm2_start")

        # Wait for bot to initialize
        logger.info("Waiting 5s for bot to initialize...")
        time.sleep(5)

        # Step 6: Configure nginx
        logger.info("Step 6/12: Configuring nginx...")
        try:
            from infrastructure_manager import NginxConfigurator

            nginx = NginxConfigurator()
            full_domain = f"{domain}.dreambigwithai.com" if domain and '.' not in domain else domain

            # Use telegram bot config as template (same proxy pattern)
            config_domain, config = nginx.generate_telegram_bot_config(domain, port)

            if nginx.install_config(domain, config):
                logger.info(f"Nginx config installed for {full_domain}")
                result_info["steps_completed"].append("nginx_config")

                if nginx.reload_nginx():
                    logger.info("Nginx reloaded successfully")
                else:
                    logger.warning("Nginx reload failed, but config installed")
            else:
                logger.warning("Failed to install nginx config, continuing...")
                result_info["errors"].append("nginx_config_install_failed")

        except Exception as e:
            logger.warning(f"Nginx configuration error: {e} - continuing without nginx")
            result_info["errors"].append(f"nginx_error: {e}")

        # Step 7: Provision DNS
        logger.info("Step 7/12: Provisioning DNS (optional)...")
        try:
            from infrastructure_manager import DNSProvisioner

            dns = DNSProvisioner()

            if dns.dns_skill_available:
                dns_result = dns.create_a_record(domain, "dreambigwithai.com", "195.200.14.37")

                if dns_result:
                    logger.info(f"DNS A record created for {full_domain}")
                    result_info["steps_completed"].append("dns_provisioning")
                else:
                    logger.warning("DNS provisioning failed, but wildcard DNS may work")
            else:
                logger.info("DNS provisioning skipped (using wildcard DNS)")
                result_info["dns_skipped"] = True

        except Exception as e:
            logger.warning(f"DNS provisioning error: {e} - continuing")
            result_info["errors"].append(f"dns_error: {e}")

        # Step 8: HTTP verify (base template)
        logger.info("Step 8/12: HTTP verification (base template)...")
        try:
            import requests

            full_domain = f"{domain}.dreambigwithai.com" if domain and '.' not in domain else domain
            health_url = f"https://{full_domain}/health"

            response = requests.get(health_url, timeout=10, verify=True)

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    logger.info("Base template verified - bot is running!")
                    result_info["base_verification"] = "success"
                    result_info["steps_completed"].append("base_verification")
                else:
                    logger.warning(f"Health check returned unexpected data: {data}")
                    result_info["base_verification"] = f"warning: {data}"
            else:
                logger.warning(f"Health check failed with status {response.status_code}")
                result_info["base_verification"] = f"failed: status {response.status_code}"

        except requests.exceptions.SSLError:
            logger.error("SSL certificate error")
            result_info["errors"].append("ssl_error")
            result_info["base_verification"] = "ssl_error"
        except Exception as e:
            logger.warning(f"HTTP verification error: {e} - continuing")
            result_info["base_verification"] = f"error: {e}"

        # Step 9: Register webhook (no-op for Discord)
        logger.info("Step 9/12: Webhook registration (skipped - Discord uses gateway)...")
        from services.discord.webhook import register_discord_interactions_endpoint
        register_discord_interactions_endpoint(bot_token, full_domain if 'full_domain' in dir() else domain, project_id)
        result_info["webhook_registration"] = "skipped_gateway_mode"
        result_info["steps_completed"].append("webhook_registration")

        # Step 10: AI enhance logic
        logger.info("Step 10/12: AI enhancement of bot logic...")
        try:
            editor = DiscordBotEditor(discord_path)
            success, edit_result = editor.enhance_bot_logic(description, project_name)

            if success:
                logger.info(f"AI enhancement: {edit_result}")
                result_info["ai_enhancement"] = edit_result
                result_info["steps_completed"].append("ai_enhancement")
            else:
                logger.warning(f"AI enhancement failed: {edit_result}")
                result_info["ai_enhancement"] = f"failed: {edit_result}"

        except Exception as e:
            logger.warning(f"AI enhancement error: {e} - continuing with base template")
            result_info["ai_enhancement"] = f"error: {e}"

        # Step 11: Run buildpublish.py
        if result_info.get("ai_enhancement") and "failed" not in result_info.get("ai_enhancement", ""):
            logger.info("Step 11/12: Running buildpublish.py (restart PM2)...")
            try:
                import subprocess

                buildpublish_path = Path(discord_path) / "buildpublish.py"

                if buildpublish_path.exists():
                    result = subprocess.run(
                        ["python3", str(buildpublish_path), str(discord_path), str(project_id)],
                        cwd=discord_path,
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    if result.returncode == 0:
                        logger.info("buildpublish.py completed successfully")
                        result_info["steps_completed"].append("buildpublish")

                        logger.info("Waiting 3s for bot to restart...")
                        time.sleep(3)
                    else:
                        logger.warning(f"buildpublish.py failed: {result.stderr}")
                        result_info["errors"].append(f"buildpublish_failed: {result.stderr}")
                else:
                    logger.warning(f"buildpublish.py not found at {buildpublish_path}")

            except subprocess.TimeoutExpired:
                logger.warning("buildpublish.py timeout - continuing")
                result_info["errors"].append("buildpublish_timeout")
            except Exception as e:
                logger.warning(f"buildpublish.py error: {e} - continuing")
                result_info["errors"].append(f"buildpublish_error: {e}")

        # Step 12: Final HTTP verify
        logger.info("Step 12/12: Final HTTP verification...")
        try:
            import requests

            time.sleep(3)

            full_domain = f"{domain}.dreambigwithai.com" if domain and '.' not in domain else domain
            health_url = f"https://{full_domain}/health"

            response = requests.get(health_url, timeout=10, verify=True)

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "healthy":
                    logger.info("Enhanced bot verified - deployment complete!")
                    result_info["final_verification"] = "success"
                    result_info["steps_completed"].append("final_verification")
                else:
                    logger.warning(f"Enhanced bot returned unexpected data: {data}")
                    result_info["final_verification"] = f"warning: {data}"
            else:
                logger.warning(f"Final verification failed with status {response.status_code}")
                result_info["final_verification"] = f"failed: status {response.status_code}"

        except requests.exceptions.SSLError:
            logger.error("SSL certificate error in final verification")
            result_info["errors"].append("ssl_error_final")
            result_info["final_verification"] = "ssl_error"
        except Exception as e:
            logger.warning(f"Final verification error: {e}")
            result_info["final_verification"] = f"error: {e}"

        # Save project metadata
        logger.info("Saving project metadata...")
        _save_project_metadata(
            project_path=project_path,
            project_id=project_id,
            project_name=project_name,
            bot_username=result_info.get("bot_username", ""),
            domain=domain,
            port=port,
            pm2_process=pm2_process_name,
            discord_path=discord_path
        )

        # Final success
        logger.info(f"Discord bot pipeline completed!")

        result_info["bot_url"] = f"https://{full_domain}" if 'full_domain' in dir() else ""

        return True, result_info

    except Exception as e:
        error_msg = f"Pipeline error: {e}"
        logger.error(error_msg)
        result_info["errors"].append(error_msg)
        return False, result_info


def run_discord_bot_worker_background(
    project_id: int,
    project_name: str,
    description: str,
    bot_token: str,
    project_path: str,
    domain: str,
    port: int,
    database_url: str = None
):
    """
    Background worker entry point for discord bot deployment.

    Args:
        Same as run_discord_bot_pipeline
    """
    from database_adapter import update_project_status

    logger.info(f"Background worker started for discord bot {project_id}")

    update_project_status(project_id, "creating")

    try:
        success, result_info = run_discord_bot_pipeline(
            project_id=project_id,
            project_name=project_name,
            description=description,
            bot_token=bot_token,
            project_path=project_path,
            domain=domain,
            port=port,
            database_url=database_url
        )

        if success:
            update_project_status(project_id, "ready")
            logger.info(f"Project {project_id} status updated to 'ready'")
        else:
            update_project_status(project_id, "failed")
            logger.error(f"Project {project_id} status updated to 'failed'")
            logger.error(f"Errors: {result_info.get('errors')}")

    except Exception as e:
        logger.error(f"Background worker error: {e}")
        update_project_status(project_id, "failed")
