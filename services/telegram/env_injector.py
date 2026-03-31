"""
Telegram Bot Environment Injector
Injects BOT_TOKEN into .env file securely.
"""
import os
import stat
from pathlib import Path
from typing import Tuple
from utils.logger import logger


def inject_bot_token(
    project_path: str, 
    bot_token: str,
    domain: str = None,
    port: int = None,
    project_id: int = None
) -> Tuple[bool, str]:
    """
    Inject BOT_TOKEN and webhook config into .env file with secure permissions.
    
    Args:
        project_path: Path to telegram/ directory
        bot_token: Telegram bot token (NEVER logged)
        domain: Webhook domain (e.g., "crypto-price-tracker-bot-yi62nm")
        port: Port number for the bot
        project_id: Project ID
    
    Returns:
        Tuple of (success, message)
    
    Security:
        - Creates .env with chmod 600 (owner read/write only)
        - NEVER logs the token
        - NEVER stores in database
    """
    try:
        # Validate inputs
        if not bot_token or not bot_token.strip():
            return False, "Bot token is empty or invalid"
        
        telegram_dir = Path(project_path)
        if not telegram_dir.exists():
            return False, f"Telegram directory not found: {telegram_dir}"
        
        env_file = telegram_dir / ".env"
        
        # Read existing .env.example or create from scratch
        env_example = telegram_dir / ".env.example"
        
        if env_example.exists():
            # Copy .env.example as base
            with open(env_example, 'r') as f:
                env_content = f.read()
            logger.info("Using .env.example as base")
        else:
            # Create minimal .env
            env_content = """# Telegram Bot Configuration
BOT_TOKEN=your_telegram_bot_token_here
BOT_NAME=AI Assistant Bot

# API Configuration
API_TIMEOUT=10
DEFAULT_CURRENCY=usd

# Database Configuration
DATABASE_URL=postgresql://user:password@localhost:5432/db_name

# Webhook Configuration
PORT=8010
WEBHOOK_DOMAIN=your-subdomain.dreambigwithai.com
WEBHOOK_PATH=/webhook
"""
        
        # Replace placeholders with actual values
        lines = env_content.split('\n')
        updated_lines = []
        
        for line in lines:
            if line.startswith('BOT_TOKEN='):
                # Replace token line (NEVER log this)
                updated_lines.append(f'BOT_TOKEN={bot_token}')
            elif line.startswith('WEBHOOK_DOMAIN=') and domain:
                updated_lines.append(f'WEBHOOK_DOMAIN={domain}')
            elif line.startswith('WEBHOOK_URL=') and domain:
                updated_lines.append(f'WEBHOOK_URL=https://{domain}/webhook')
            elif line.startswith('PORT=') and port:
                updated_lines.append(f'PORT={port}')
            elif line.startswith('PROJECT_ID=') and project_id:
                updated_lines.append(f'PROJECT_ID={project_id}')
            else:
                updated_lines.append(line)
        
        # Add missing webhook config if not in template
        if domain and not any(l.startswith('WEBHOOK_DOMAIN=') for l in lines):
            updated_lines.append(f'WEBHOOK_DOMAIN={domain}')
        if domain and not any(l.startswith('WEBHOOK_URL=') for l in lines):
            updated_lines.append(f'WEBHOOK_URL=https://{domain}/webhook')
        if port and not any(l.startswith('PORT=') for l in lines):
            updated_lines.append(f'PORT={port}')
        if project_id and not any(l.startswith('PROJECT_ID=') for l in lines):
            updated_lines.append(f'PROJECT_ID={project_id}')
        
        # Write .env file
        env_content_updated = '\n'.join(updated_lines)
        
        with open(env_file, 'w') as f:
            f.write(env_content_updated)
        
        # Set secure permissions (chmod 600)
        os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)
        
        # Verify file created
        if not env_file.exists():
            return False, "Failed to create .env file"
        
        # Verify permissions
        file_stat = os.stat(env_file)
        permissions = oct(file_stat.st_mode)[-3:]
        
        if permissions != '600':
            logger.warning(f"Failed to set secure permissions (got {permissions})")
        
        logger.info(f"✅ .env file created with secure permissions at {env_file}")
        logger.info("✅ BOT_TOKEN injected (token not logged for security)")
        if domain:
            logger.info(f"✅ Webhook config injected: domain={domain}, port={port}")
        
        return True, f"Environment configured at {env_file}"
    
    except PermissionError as e:
        error_msg = f"Permission denied creating .env: {e}"
        logger.error(error_msg)
        return False, error_msg
    
    except Exception as e:
        # Never log the token in error messages
        error_msg = f"Failed to inject environment: {type(e).__name__}"
        logger.error(error_msg)
        return False, error_msg


def update_env_variable(project_path: str, key: str, value: str) -> Tuple[bool, str]:
    """
    Update a specific environment variable in .env file.
    
    Args:
        project_path: Path to telegram/ directory
        key: Environment variable name
        value: New value
    
    Returns:
        Tuple of (success, message)
    """
    try:
        env_file = Path(project_path) / ".env"
        
        if not env_file.exists():
            return False, ".env file not found"
        
        # Read existing content
        with open(env_file, 'r') as f:
            lines = f.readlines()
        
        # Update or add variable
        updated = False
        new_lines = []
        
        for line in lines:
            if line.startswith(f'{key}='):
                new_lines.append(f'{key}={value}\n')
                updated = True
            else:
                new_lines.append(line)
        
        # Add if not found
        if not updated:
            new_lines.append(f'{key}={value}\n')
        
        # Write back
        with open(env_file, 'w') as f:
            f.writelines(new_lines)
        
        logger.info(f"✅ Updated {key} in .env")
        return True, f"{key} updated"
    
    except Exception as e:
        error_msg = f"Failed to update {key}: {e}"
        logger.error(error_msg)
        return False, error_msg


def inject_webhook_config(project_path: str, domain: str, port: int, project_id: int) -> Tuple[bool, str]:
    """
    Inject webhook configuration into .env file.
    
    Args:
        project_path: Path to telegram/ directory
        domain: Domain name (e.g., "crypto-price-tracker-bot-yi62nm")
        port: Port number for the bot
        project_id: Project ID
    
    Returns:
        Tuple of (success, message)
    """
    try:
        env_file = Path(project_path) / ".env"
        
        # Create .env if it doesn't exist
        if not env_file.exists():
            env_file.touch()
            os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)
        
        # Build webhook URL
        webhook_url = f"https://{domain}/webhook"
        
        # Read existing content
        with open(env_file, 'r') as f:
            lines = f.readlines()
        
        # Variables to set
        config_vars = {
            'WEBHOOK_DOMAIN': domain,
            'WEBHOOK_URL': webhook_url,
            'WEBHOOK_PATH': '/webhook',
            'PORT': str(port),
            'PROJECT_ID': str(project_id)
        }
        
        # Update or add each variable
        for key, value in config_vars.items():
            updated = False
            for i, line in enumerate(lines):
                if line.startswith(f'{key}='):
                    lines[i] = f'{key}={value}\n'
                    updated = True
                    break
            
            if not updated:
                # Add to end if not found
                if lines and not lines[-1].endswith('\n'):
                    lines.append('\n')
                lines.append(f'{key}={value}\n')
        
        # Write back
        with open(env_file, 'w') as f:
            f.writelines(lines)
        
        logger.info(f"✅ Webhook config injected: domain={domain}, port={port}")
        return True, f"Webhook config set for {domain}"
    
    except Exception as e:
        error_msg = f"Failed to inject webhook config: {e}"
        logger.error(error_msg)
        return False, error_msg
