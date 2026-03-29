#!/usr/bin/env python3
"""
Telegram Bot Build & Publish Script
Run from bot directory: python buildpublish.py [--skip-deps] [--no-restart]

IMPORTANT: Call this script AFTER making ANY changes to the bot code!
- If you modified any files in the bot directory, run: python3 buildpublish.py
- This will install deps and restart PM2 automatically
- Only skip restart with --no-restart if you're just testing locally

Steps:
1. Install Python dependencies
2. Verify main.py exists
3. Restart PM2 process (bot will reload with new code)
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path


# Shared virtual environment path (same as backend)
SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"


def run(cmd: str, cwd: str = None, env: dict = None) -> bool:
    """Run shell command, return True if success"""
    print(f"\n▶ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"✗ Failed: {cmd}")
        return False
    print(f"✓ Success: {cmd}")
    return True


def install_dependencies(venv_path: str = None):
    """Install Python dependencies using shared venv with caching"""
    print("\n" + "="*50)
    print("PIP INSTALL")
    print("="*50)
    
    # Check for requirements.txt
    if not Path("requirements.txt").exists():
        print("⚠ No requirements.txt found, skipping")
        return True
    
    # Determine venv path
    venv = venv_path or SHARED_VENV_PATH
    pip_path = Path(venv) / "bin" / "pip"
    
    # Check if venv exists
    if pip_path.exists():
        print(f"📦 Using shared venv: {venv}")
        pip_cmd = str(pip_path)
    else:
        print("⚠ Shared venv not found, using system pip")
        pip_cmd = "pip"
    
    # Install with caching options
    return run(f"{pip_cmd} install --prefer-binary -r requirements.txt")


def verify_main():
    """Verify main.py exists"""
    main_path = Path("main.py")
    if not main_path.exists():
        print("✗ main.py not found")
        return False
    print(f"✓ main.py verified: {main_path.stat().st_size} bytes")
    return True


def restart_pm2():
    """Restart PM2 process for this bot
    
    PM2 app name is read from .env file (BOT_NAME variable)
    Format: tg-bot-{project_id} (set by pm2_manager.py)
    """
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)
    
    # Read bot name from .env
    env_path = Path(".env")
    if not env_path.exists():
        print("✗ .env file not found")
        return False
    
    project_id = None
    bot_token = None
    domain = None
    
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith("PROJECT_ID="):
                project_id = line.split("=", 1)[1].strip()
            elif line.startswith("BOT_TOKEN="):
                bot_token = line.split("=", 1)[1].strip()
            elif line.startswith("WEBHOOK_DOMAIN="):
                domain = line.split("=", 1)[1].strip()
    
    if not project_id:
        print("✗ PROJECT_ID not found in .env")
        return False
    
    # PM2 process name format: tg-bot-{project_id}
    pm2_process_name = f"tg-bot-{project_id}"
    
    print(f"📦 Restarting PM2 app: {pm2_process_name}")
    if not run(f"pm2 restart {pm2_process_name}"):
        return False
    
    # Re-register webhook if token and domain available
    if bot_token and domain:
        print("\n" + "="*50)
        print("WEBHOOK RE-REGISTRATION")
        print("="*50)
        re_register_webhook(bot_token, domain, project_id)
    
    return True


def re_register_webhook(bot_token: str, domain: str, project_id: str):
    """
    Re-register Telegram webhook after restart.
    Called automatically when bot restarts to ensure webhook is up-to-date.
    
    Args:
        bot_token: Telegram bot token
        domain: Webhook domain
        project_id: Project ID
    
    Safety:
        - Non-blocking (won't fail restart if webhook registration fails)
        - Timeout: 10 seconds
        - Logs success/failure
    """
    import requests
    
    try:
        # Build webhook URL
        webhook_url = f"https://{domain}/bot/{project_id}/webhook"
        
        print(f"🔗 Re-registering webhook: {webhook_url}")
        
        # Delete old webhook first (cleanup)
        delete_url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
        try:
            requests.get(delete_url, timeout=5)
            print("✓ Old webhook removed")
        except:
            pass  # Ignore errors
        
        # Register new webhook
        telegram_api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
        
        payload = {
            "url": webhook_url,
            "allowed_updates": ["message", "edited_message", "callback_query"]
        }
        
        response = requests.post(telegram_api_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("ok"):
                print(f"✅ Webhook re-registered successfully")
                print(f"📍 URL: {webhook_url}")
            else:
                error_msg = result.get("description", "Unknown error")
                print(f"⚠️ Webhook registration failed: {error_msg}")
        else:
            print(f"⚠️ Webhook registration failed with status {response.status_code}")
    
    except requests.exceptions.Timeout:
        print("⚠️ Webhook registration timeout (non-critical)")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Webhook registration error: {e} (non-critical)")
    except Exception as e:
        print(f"⚠️ Unexpected webhook error: {e} (non-critical)")



def main():
    parser = argparse.ArgumentParser(description="Telegram Bot Build & Publish")
    parser.add_argument("--skip-deps", action="store_true", help="Skip pip install")
    parser.add_argument("--no-restart", action="store_true", help="Skip PM2 restart (restart is default)")
    parser.add_argument("--venv", type=str, help="Virtual environment path (default: /root/dreampilot/dreampilotvenv)")
    args = parser.parse_args()
    
    # Ensure we're in bot directory
    if not Path("main.py").exists():
        print("✗ Error: Run this script from the bot directory")
        sys.exit(1)
    
    success = True
    
    # Step 1: Install dependencies
    if not args.skip_deps:
        if not install_dependencies(args.venv):
            success = False
    
    # Step 2: Verify main.py
    if success:
        if not verify_main():
            success = False
    
    # Step 3: Restart PM2 (MANDATORY by default)
    if not args.no_restart and success:
        if not restart_pm2():
            print("⚠ PM2 restart failed, but continuing")
    
    print("\n" + "="*50)
    if success:
        print("✓ BUILD & PUBLISH COMPLETE")
    else:
        print("✗ BUILD FAILED")
    print("="*50)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
