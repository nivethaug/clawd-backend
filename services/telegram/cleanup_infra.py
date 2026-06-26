"""
Telegram Bot Infrastructure Cleanup Module

Handles cleanup of PM2 processes, nginx configs, SSL certificates, 
DNS records, and databases for telegram bot projects.
"""

import os
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

from domain_config import BASE_DOMAIN, frontend_domain as _frontend_domain


def cleanup_telegram_bot_infrastructure(
    project_path: str,
    project_id: Optional[int] = None,
    project_metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Full infrastructure cleanup for a telegram bot project.
    
    Args:
        project_path: Full path to project directory
        project_id: Project ID (extracted from path if not provided)
        project_metadata: Project metadata from project.json
    
    Returns:
        Dict with complete cleanup status
    """
    logger.info(f"🤖 Starting telegram bot infrastructure cleanup for: {project_path}")
    
    project_metadata = project_metadata or {}
    
    # Extract project_id from path if not provided
    if not project_id:
        path_basename = os.path.basename(project_path)
        project_id_match = re.match(r'^(\d+)_', path_basename)
        project_id = int(project_id_match.group(1)) if project_id_match else None
    
    # Extract project name from metadata or path
    project_name = project_metadata.get("project_name")
    if not project_name:
        path_basename = os.path.basename(project_path)
        match = re.match(r'^\d+_(.+?)_\d{8}_\d{6}$', path_basename)
        if match:
            project_name = match.group(1)
        else:
            parts = path_basename.split('_', 1)
            project_name = parts[1] if len(parts) > 1 else path_basename
        logger.info(f"Extracted project name from path: {project_name}")
    
    # Get domain from project.json - telegram bots store domain directly
    domain = project_metadata.get("domain", "")
    
    if not domain:
        # Fallback: try frontend_domain
        domain = project_metadata.get("frontend_domain", "").replace(f".{BASE_DOMAIN}", "")
    
    if not domain:
        # Last resort: use project_name (but log warning)
        domain = project_name
        logger.warning(f"⚠️ No domain found in project.json, using project_name: {project_name}")
    else:
        logger.info(f"📦 Using domain from project.json: {domain}")
    
    # Get database info
    db_name = project_metadata.get("database", {}).get("name", "")
    db_user = project_metadata.get("database", {}).get("user", "")
    
    if not db_name:
        db_name = project_metadata.get("database", "")
        if db_name:
            db_user = db_name.replace("_db", "_user")
    
    cleanup_results = {
        "project_name": project_name,
        "project_path": project_path,
        "project_id": project_id,
        "domain": domain,
        "project_type": "telegram_bot",
        "steps": {}
    }
    
    # STEP 1: Delete PM2 process
    if project_id:
        try:
            from services.telegram.pm2_manager import delete_bot_pm2
            logger.info(f"🗑 Deleting Telegram bot PM2 process for project {project_id}")
            success, message = delete_bot_pm2(project_id, domain=domain)
            cleanup_results["steps"]["pm2"] = {
                "success": success,
                "message": message,
                "process_name": f"{domain}-bot" if domain else f"tg-bot-{project_id}"
            }
            if success:
                logger.info(f"✅ PM2 process deleted successfully")
            else:
                logger.warning(f"⚠️ PM2 delete result: {message}")
        except Exception as e:
            logger.error(f"Error deleting telegram bot PM2: {e}")
            cleanup_results["steps"]["pm2"] = {"error": str(e)}
    else:
        logger.warning("No project_id found, skipping PM2 cleanup")
        cleanup_results["steps"]["pm2"] = {"skipped": True, "reason": "No project_id"}
    
# STEP 2: Remove Nginx configuration
    try:
        from infrastructure_manager import NginxConfigurator
        nginx_name = domain or project_name
        if nginx_name:
            nginx = NginxConfigurator()
            removed = nginx.remove_config(nginx_name)
            cleanup_results["steps"]["nginx"] = {"success": removed, "message": f"Removed nginx config for {nginx_name}"}
            logger.info(f"🗑 Nginx config cleanup for {nginx_name}: {'✅ removed' if removed else '⚠️ failed'}")
        else:
            cleanup_results["steps"]["nginx"] = {"skipped": True, "reason": "No domain"}
    except Exception as e:
        logger.error(f"Error in Nginx cleanup: {e}")
        cleanup_results["steps"]["nginx"] = {"error": str(e)}

    # STEP 3: SSL cleanup
    # All bots use the wildcard *.{BASE_DOMAIN} certificate, so there's
    # no per-domain SSL cert to remove. Nothing to do here.
    cleanup_results["steps"]["ssl"] = {"skipped": True, "reason": f"Uses wildcard cert (*.{BASE_DOMAIN})"}

    # STEP 4: Remove DNS records
    try:
        from infrastructure_manager import DNSProvisioner
        if domain:
            dns = DNSProvisioner()
            deleted = dns.delete_a_record(domain)
            cleanup_results["steps"]["dns"] = {"success": deleted, "message": f"DNS A record deletion for {domain}"
                + (" — skipped (DNS API not configured)" if not dns.dns_skill_available else "")}
            logger.info(f"🗑 DNS cleanup for {domain}: {'✅ deleted' if deleted else '⚠️ skipped/failed'}")
        else:
            cleanup_results["steps"]["dns"] = {"skipped": True, "reason": "No domain"}
    except Exception as e:
        logger.error(f"Error in DNS cleanup: {e}")
        cleanup_results["steps"]["dns"] = {"error": str(e)}

    # STEP 5: Drop PostgreSQL database (if any)
    try:
        from infrastructure_manager import DatabaseProvisioner
        db_service_name = domain or project_name
        if db_service_name:
            db_prov = DatabaseProvisioner()
            db_prov.drop_database_and_user(db_service_name)
            cleanup_results["steps"]["database"] = {"success": True, "message": f"Dropped database for {db_service_name}"}
            logger.info(f"🗑 Database dropped for {db_service_name}")
        else:
            logger.info("Skipping database cleanup: no service name found")
            cleanup_results["steps"]["database"] = {"skipped": True}
    except Exception as e:
        logger.error(f"Error in database cleanup: {e}")
        cleanup_results["steps"]["database"] = {"error": str(e)}
    
    # STEP 6: Remove project directory
    try:
        cleanup_results["steps"]["directory"] = cleanup_project_directory(project_path)
    except Exception as e:
        logger.error(f"Error in directory cleanup: {e}")
        cleanup_results["steps"]["directory"] = {"error": str(e)}
    
    logger.info(f"✅ Telegram bot infrastructure cleanup completed for {project_name}")
    
    return cleanup_results


def cleanup_project_directory(project_path: str) -> Dict[str, Any]:
    """
    Remove project directory.
    
    Args:
        project_path: Full path to project directory
    
    Returns:
        Dict with cleanup status
    """
    import shutil
    
    if not os.path.exists(project_path):
        return {"success": True, "message": "Directory does not exist"}
    
    try:
        shutil.rmtree(project_path)
        logger.info(f"✅ Removed project directory: {project_path}")
        return {"success": True, "message": f"Removed {project_path}"}
    except Exception as e:
        logger.error(f"Failed to remove project directory: {e}")
        return {"success": False, "error": str(e)}
