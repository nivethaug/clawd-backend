"""
Telegram Bot Environment Injector
Injects BOT_TOKEN into .env file securely.
"""
import os
import stat
from pathlib import Path
from typing import Tuple
from utils.logger import logger


def inject_bot_token(project_path: str, bot_token: str) -> Tuple[bool, str]:
    """
    Inject BOT_TOKEN into .env file with secure permissions.
    
    Args:
        project_path: Path to telegram/ directory
        bot_token: Telegram bot token (NEVER logged)
    
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
        
        # Replace BOT_TOKEN placeholder
        lines = env_content.split('\n')
        updated_lines = []
        
        for line in lines:
            if line.startswith('BOT_TOKEN='):
                # Replace token line (NEVER log this)
                updated_lines.append(f'BOT_TOKEN={bot_token}')
            elif line.startswith('WEBHOOK_DOMAIN='):
                # Will be updated later with actual domain
                updated_lines.append(line)
            else:
                updated_lines.append(line)
        
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
