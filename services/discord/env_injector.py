"""
Discord Bot Environment Injector
Injects DISCORD_TOKEN into .env file securely.
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
    project_id: int = None,
    database_url: str = None
) -> Tuple[bool, str]:
    """
    Inject DISCORD_TOKEN and config into .env file with secure permissions.

    Args:
        project_path: Path to discord/ directory
        bot_token: Discord bot token (NEVER logged)
        domain: Domain (e.g., "mybot-abc123")
        port: Port number for the health server
        project_id: Project ID
        database_url: Database connection URL

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

        discord_dir = Path(project_path)
        if not discord_dir.exists():
            return False, f"Discord directory not found: {discord_dir}"

        env_file = discord_dir / ".env"

        # Read existing .env.example or create from scratch
        env_example = discord_dir / ".env.example"

        if env_example.exists():
            with open(env_example, 'r') as f:
                env_content = f.read()
            logger.info("Using .env.example as base")
        else:
            env_content = """# Discord Bot Configuration
DISCORD_TOKEN=your_discord_bot_token_here
COMMAND_PREFIX=!

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=dreampilot
DB_USER=admin
DB_PASSWORD=StrongAdminPass123

# Server Configuration
PORT=8010
PROJECT_ID=1
"""

        # Log incoming parameters
        logger.info(f"inject_bot_token called with:")
        logger.info(f"   - project_path: {project_path}")
        logger.info(f"   - domain: {domain}")
        logger.info(f"   - port: {port}")
        logger.info(f"   - project_id: {project_id}")

        # Replace placeholders with actual values
        lines = env_content.split('\n')
        updated_lines = []
        set_keys = set()

        for line in lines:
            if line.startswith('DISCORD_TOKEN='):
                updated_lines.append(f'DISCORD_TOKEN={bot_token}')
                set_keys.add('DISCORD_TOKEN')
                logger.info(f"   Set DISCORD_TOKEN")
            elif line.startswith('PORT='):
                if port:
                    updated_lines.append(f'PORT={port}')
                    logger.info(f"   Set PORT={port}")
                else:
                    updated_lines.append(line)
                set_keys.add('PORT')
            elif line.startswith('PROJECT_ID='):
                if project_id:
                    updated_lines.append(f'PROJECT_ID={project_id}')
                    logger.info(f"   Set PROJECT_ID={project_id}")
                else:
                    updated_lines.append(line)
                set_keys.add('PROJECT_ID')
            elif line.startswith('DATABASE_URL='):
                if database_url:
                    updated_lines.append(f'DATABASE_URL={database_url}')
                    logger.info(f"   Set DATABASE_URL=***")
                else:
                    updated_lines.append(line)
                set_keys.add('DATABASE_URL')
            elif line.startswith('WEBHOOK_DOMAIN='):
                if domain:
                    updated_lines.append(f'WEBHOOK_DOMAIN={domain}')
                    logger.info(f"   Set WEBHOOK_DOMAIN={domain}")
                else:
                    updated_lines.append(line)
                set_keys.add('WEBHOOK_DOMAIN')
            elif line.startswith('WEBHOOK_URL='):
                if domain:
                    updated_lines.append(f'WEBHOOK_URL=https://{domain}.dreambigwithai.com/health')
                    logger.info(f"   Set WEBHOOK_URL=https://{domain}.dreambigwithai.com/health")
                else:
                    updated_lines.append(line)
                set_keys.add('WEBHOOK_URL')
            elif line.startswith('DB_HOST=') and database_url:
                # Skip individual DB fields if DATABASE_URL is provided
                updated_lines.append(line)
            elif line.startswith('DB_PORT=') and database_url:
                updated_lines.append(line)
            elif line.startswith('DB_NAME=') and database_url:
                updated_lines.append(line)
            elif line.startswith('DB_USER=') and database_url:
                updated_lines.append(line)
            elif line.startswith('DB_PASSWORD=') and database_url:
                updated_lines.append(line)
            else:
                updated_lines.append(line)

        # Add missing required variables
        if port and 'PORT' not in set_keys:
            updated_lines.append(f'PORT={port}')
            logger.info(f"   Added PORT={port}")
        if project_id and 'PROJECT_ID' not in set_keys:
            updated_lines.append(f'PROJECT_ID={project_id}')
            logger.info(f"   Added PROJECT_ID={project_id}")
        if database_url and 'DATABASE_URL' not in set_keys:
            updated_lines.append(f'DATABASE_URL={database_url}')
            logger.info(f"   Added DATABASE_URL=***")
        if domain and 'WEBHOOK_DOMAIN' not in set_keys:
            updated_lines.append(f'WEBHOOK_DOMAIN={domain}')
            logger.info(f"   Added WEBHOOK_DOMAIN={domain}")
        if domain and 'WEBHOOK_URL' not in set_keys:
            updated_lines.append(f'WEBHOOK_URL=https://{domain}.dreambigwithai.com/health')
            logger.info(f"   Added WEBHOOK_URL")

        # Write .env file
        env_content_updated = '\n'.join(updated_lines)

        with open(env_file, 'w') as f:
            f.write(env_content_updated)

        # Set secure permissions (chmod 600)
        os.chmod(env_file, stat.S_IRUSR | stat.S_IWUSR)

        logger.info(f".env file created with secure permissions at {env_file}")
        logger.info("DISCORD_TOKEN injected (token not logged for security)")
        if domain:
            logger.info(f"Config injected: domain={domain}, port={port}")

        return True, f"Environment configured at {env_file}"

    except PermissionError as e:
        error_msg = f"Permission denied creating .env: {e}"
        logger.error(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = f"Failed to inject environment: {type(e).__name__}"
        logger.error(error_msg)
        return False, error_msg


def update_env_variable(project_path: str, key: str, value: str) -> Tuple[bool, str]:
    """
    Update a specific environment variable in .env file.

    Args:
        project_path: Path to discord/ directory
        key: Environment variable name
        value: New value

    Returns:
        Tuple of (success, message)
    """
    try:
        env_file = Path(project_path) / ".env"

        if not env_file.exists():
            return False, ".env file not found"

        with open(env_file, 'r') as f:
            lines = f.readlines()

        updated = False
        new_lines = []

        for line in lines:
            if line.startswith(f'{key}='):
                new_lines.append(f'{key}={value}\n')
                updated = True
            else:
                new_lines.append(line)

        if not updated:
            new_lines.append(f'{key}={value}\n')

        with open(env_file, 'w') as f:
            f.writelines(new_lines)

        logger.info(f"Updated {key} in .env")
        return True, f"{key} updated"

    except Exception as e:
        error_msg = f"Failed to update {key}: {e}"
        logger.error(error_msg)
        return False, error_msg
