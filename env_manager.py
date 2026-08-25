"""
Environment Variables Manager

Provides read/write/reveal/restart capabilities for project .env files.
Works for all project types (website, telegram bot, discord bot, scheduler)
by resolving the correct .env path based on project type_id.

No new database tables. .env files are the single source of truth.
"""

import os
import re
import stat
import subprocess
import logging
from typing import Dict, List, Tuple, Optional

from database_adapter import get_db

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

# Variables managed by DreamAgent infrastructure. These are HIDDEN from users
# entirely — never returned by GET, never editable. Users only see the
# variables they explicitly added (integrations + bot credentials).
SYSTEM_KEYS = frozenset({
    "PORT",
    "HOST",
    "DEBUG",
    "PROJECT_ID",
    "PROJECT_NAME",
    "SECRET_KEY",
    "DATABASE_URL",
    # Common infrastructure-managed variants
    "API_HOST",
    "API_PORT",
    "APP_ENV",
    "NODE_ENV",
    "PYTHON_ENV",
    "VITE_API_URL",
    "CORS_ORIGINS",
    "RELOAD",
    "LOG_LEVEL",
    "PM2_ID",
    "WEBHOOK_URL",      # set by the deployment pipeline
    "WEBHOOK_SECRET",
    "WEBHOOK_DOMAIN",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "COMMAND_PREFIX",
    # Scheduler infrastructure (injected by env_injector.py at create time).
    # These are platform-managed — the user never sets them. The channel
    # keys (EMAIL_TO, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    # DISCORD_WEBHOOK_URL, API_ENDPOINT) are NOT here: those are user-managed
    # sender channels shown in the env dialog / SenderChannels UI.
    "PROJECT_PATH",   # auto-resolved at create time
    "BACKEND_URL",    # platform API URL (resolved from SCHEDULER_BACKEND_URL)
    "SMTP_HOST",      # shared SMTP relay (Hostinger) — injected, not user-set
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "SMTP_FROM",
})

# Patterns that mark a visible variable as sensitive (masked by default)
SENSITIVE_PATTERNS = [
    "TOKEN",
    "SECRET",
    "KEY",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
]

# Valid env var key format: uppercase letters, digits, underscores only,
# must start with a letter. Rejects lowercase, hyphens, dots.
KEY_REGEX = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Map project type_id -> subdirectory containing the .env file.
# An empty string ("") means the .env lives at the project root.
#
# These MUST match where copy_*_template() puts the template + where the
# *_env_injector writes .env at create time, and where the runtime's
# config.py loads .env from. Verified 2026-07-26:
#   - website (1): copy -> backend/, inject -> backend/.env     ✅ "backend"
#   - telegram (2): copy -> telegram/, inject -> telegram/.env  ✅ "telegram"
#   - discord (3): copy -> discord/, inject -> discord/.env     ✅ "discord"
#   - scheduler (5): copy -> ROOT, inject -> ROOT/.env         → "" (root)
#     (scheduler is the outlier: its copy_scheduler_template writes
#      directly to project_path, not a subdir; config.py loads
#      _project_dir/.env, i.e. root. The old "scheduler" value pointed
#      at a phantom subdir and hid create-time channels from GET /env.)
ENV_SUBDIR_MAP = {
    1: "backend",      # website — .env at {project_path}/backend/.env
    2: "telegram",     # telegram bot — .env at {project_path}/telegram/.env
    3: "discord",      # discord bot — .env at {project_path}/discord/.env
    5: "",             # scheduler — .env at {project_path}/.env (root)
    7: "",             # agent — .env at {project_path}/.env (root; fast path,
                       # slug fallback below covers non-7 ids)
}

# Value returned for masked sensitive variables (never the real value)
MASKED_VALUE = "********"


# ============================================================================
# HELPERS
# ============================================================================

def _is_sensitive(key: str) -> bool:
    """Return True if the key should be masked (contains a sensitive pattern)."""
    key_upper = key.upper()
    return any(p in key_upper for p in SENSITIVE_PATTERNS)


def _is_system(key: str) -> bool:
    """Return True if the key is infrastructure-managed and should be hidden."""
    return key in SYSTEM_KEYS


# ============================================================================
# PATH RESOLUTION
# ============================================================================

def _parse_env_file_keys(path: str) -> "list[tuple[str, str]]":
    """Return [(key, value), ...] for non-comment KEY=VALUE lines in an env file."""
    pairs: "list[tuple[str, str]]" = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                pairs.append((k.strip(), v.strip()))
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning(f"[ENV] Failed to parse {path}: {e}")
    return pairs


def _migrate_legacy_scheduler_env(project_path: str) -> None:
    """
    Merge a legacy {project_path}/scheduler/.env into {project_path}/.env.

    Idempotent: if scheduler/.env has already been renamed to
    scheduler/.env.migrated (or doesn't exist), this is a no-op. Only keys
    missing from root .env are appended (root wins on conflict). Safe to call
    on every scheduler env access.
    """
    root_env = os.path.join(project_path, ".env")
    legacy_dir = os.path.join(project_path, "scheduler")
    legacy_env = os.path.join(legacy_dir, ".env")
    migrated_env = os.path.join(legacy_dir, ".env.migrated")

    # Already migrated, or never had a legacy file -> nothing to do.
    if not os.path.exists(legacy_env) or os.path.exists(migrated_env):
        return

    legacy_pairs = _parse_env_file_keys(legacy_env)
    if not legacy_pairs:
        # Empty legacy file — just mark migrated.
        try:
            os.rename(legacy_env, migrated_env)
        except OSError:
            pass
        return

    root_keys = {k for k, _ in _parse_env_file_keys(root_env)} if os.path.exists(root_env) else set()

    # Append only keys missing from root.
    new_lines: "list[str]" = []
    for k, v in legacy_pairs:
        if k not in root_keys:
            new_lines.append(f"{k}={v}")

    if new_lines:
        try:
            # Preserve a blank line separator if root .env exists and is non-empty.
            needs_separator = False
            if os.path.exists(root_env):
                with open(root_env, "r", encoding="utf-8") as f:
                    content = f.read()
                if content and not content.endswith("\n"):
                    new_lines.insert(0, "")
                elif content and not content.endswith("\n\n"):
                    needs_separator = True
            with open(root_env, "a", encoding="utf-8") as f:
                if needs_separator:
                    f.write("\n")
                f.write("\n".join(new_lines) + "\n")
            migrated_keys = [ln.split("=", 1)[0] for ln in new_lines if "=" in ln]
            logger.info(
                f"[ENV] Migrated {len(new_lines)} key(s) from scheduler/.env -> root .env "
                f"for {os.path.basename(project_path)}: {migrated_keys}"
            )
        except Exception as e:
            logger.warning(f"[ENV] Migration append failed for {project_path}: {e}")
            return  # don't rename if append failed

    # Mark as migrated so we never run again.
    try:
        os.rename(legacy_env, migrated_env)
        logger.info(f"[ENV] Renamed scheduler/.env -> scheduler/.env.migrated for {project_path}")
    except OSError as e:
        logger.warning(f"[ENV] Could not rename legacy scheduler/.env: {e}")


def get_project_env_info(project_id: int) -> Tuple[str, int, Optional[str], str]:
    """
    Resolve the .env file path for a project.

    Args:
        project_id: Project ID

    Returns:
        Tuple of (env_path, type_id, domain, project_name)

    Raises:
        ValueError: If project not found or type unsupported
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT project_path, type_id, domain, name FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()

    if not row:
        raise ValueError(f"Project {project_id} not found")

    if isinstance(row, dict):
        project_path = row["project_path"]
        type_id = row["type_id"]
        domain = row.get("domain")
        project_name = row["name"]
    else:
        project_path = row[0]
        type_id = row[1]
        domain = row[2]
        project_name = row[3]

    if not project_path:
        raise ValueError(f"Project {project_id} has no project_path")

    # type_id not in the map at all -> genuinely unsupported.
    # type_id in map with subdir="" -> supported, .env at project root.
    if type_id not in ENV_SUBDIR_MAP:
        # Slug fallback: 'agent' (scheduler-family, root .env) may carry any
        # SERIAL id on environments where the seed order differed.
        try:
            with get_db() as _conn:
                _trow = _conn.execute(
                    "SELECT type FROM project_types WHERE id = ?",
                    (type_id,),
                ).fetchone()
            _slug = ""
            if _trow:
                _d = dict(_trow) if not isinstance(_trow, dict) else _trow
                _slug = _d.get("type") or ""
        except Exception:
            _slug = ""
        if _slug in ("agent", "scheduler"):
            env_path = os.path.join(project_path, ".env")
            return env_path, type_id, domain, project_name
        raise ValueError(
            f"Environment variable editing is not supported for type_id={type_id}. "
            f"Supported types: {list(ENV_SUBDIR_MAP.keys())}"
        )
    subdir = ENV_SUBDIR_MAP[type_id]

    env_path = os.path.join(project_path, subdir, ".env") if subdir else os.path.join(project_path, ".env")

    # One-time migration for scheduler projects (type_id=5):
    # Before this fix, GET/PUT read from {project_path}/scheduler/.env while
    # the create-flow + runtime used {project_path}/.env (root). Users who
    # manually added keys via the env dialog wrote them to scheduler/.env,
    # which the runtime ignored. Now that we read root, merge any keys from
    # the legacy scheduler/.env into root .env so nothing is lost. The merge
    # only adds keys missing from root (root wins on conflict) and then
    # renames scheduler/.env to .env.migrated so it never runs again.
    if type_id == 5 and subdir == "":
        _migrate_legacy_scheduler_env(project_path)

    return env_path, type_id, domain, project_name


# ============================================================================
# READ
# ============================================================================

def read_env_file(path: str) -> List[Dict]:
    """
    Parse a .env file into a list of variable dicts.

    Only returns USER-MANAGED variables. Infrastructure/system variables
    (PORT, HOST, DATABASE_URL, SECRET_KEY, etc.) are hidden entirely.

    Returns:
        List of {key, value, masked} dicts.
        - masked=True for sensitive keys (value replaced with '********')
        - Comment lines and blank lines are skipped.
    """
    variables: List[Dict] = []

    if not os.path.exists(path):
        return variables

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()

                # Skip blank lines and comments
                if not stripped or stripped.startswith("#"):
                    continue

                if "=" not in stripped:
                    continue

                key, _, value = stripped.partition("=")
                key = key.strip()
                value = value.strip()

                # Remove surrounding quotes if present
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]

                if not key:
                    continue

                # Hide infrastructure-managed variables completely
                if _is_system(key):
                    continue

                sensitive = _is_sensitive(key)

                variables.append({
                    "key": key,
                    "value": MASKED_VALUE if sensitive else value,
                    "masked": sensitive,
                })
    except Exception as e:
        logger.error(f"Failed to read .env at {path}: {e}")
        raise

    return variables


# ============================================================================
# VALIDATION
# ============================================================================

class EnvValidationError(Exception):
    """Raised when env var keys fail validation."""
    pass


def validate_keys(updates: Dict[str, str]) -> None:
    """
    Validate env var keys before writing.

    Rules:
        - Must match ^[A-Z][A-Z0-9_]*$  (rejects lowercase, hyphens, dots)
        - Must not be a system/infrastructure key (hidden from users)

    Raises:
        EnvValidationError: With a descriptive message listing all problems.
    """
    errors: List[str] = []

    for key in updates:
        if not KEY_REGEX.match(key):
            errors.append(
                f"Invalid key '{key}': must be uppercase letters, digits, and "
                f"underscores only, starting with a letter."
            )
        elif _is_system(key):
            errors.append(
                f"'{key}' is a system variable managed by the platform and cannot be modified."
            )

    if errors:
        raise EnvValidationError("; ".join(errors))


# ============================================================================
# WRITE (atomic, comment-preserving)
# ============================================================================

def write_env_file(path: str, updates: Dict[str, str]) -> None:
    """
    Merge key=value updates into an existing .env file.

    - Preserves comments and unrelated lines.
    - Updates existing keys in place.
    - Appends new keys at the end.
    - Writes atomically via temp file + os.replace.
    - Sets permissions to 600 (owner read/write only).

    Args:
        path: Path to the .env file
        updates: Dict of {KEY: value} to write
    """
    # Read existing lines
    existing_lines: List[str] = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    updated_keys = set()
    new_lines: List[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}\n")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append keys not already present
    appended_any = False
    for key, val in updates.items():
        if key not in updated_keys:
            if not appended_any and new_lines and new_lines[-1].strip():
                new_lines.append("\n")
            new_lines.append(f"{key}={val}\n")
            appended_any = True

    # Atomic write: temp file -> rename
    dir_name = os.path.dirname(path)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        # Set permissions before rename so the final file is correct
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 600

        os.replace(tmp_path, path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise

    logger.info(f"[ENV] Updated {len(updates)} variable(s) in {os.path.basename(os.path.dirname(path))}/.env")


# ============================================================================
# REVEAL
# ============================================================================

def reveal_env_value(path: str, key: str) -> Optional[str]:
    """
    Read a single env var value unmasked.

    System/infrastructure keys are never revealable — returns None for them
    so platform secrets (SMTP_PASS, BACKEND_URL, DATABASE_URL, etc.) can't
    be exfiltrated via the reveal endpoint even by the project owner.

    Args:
        path: Path to .env file
        key: Variable key to reveal

    Returns:
        The unmasked value, or None if not found / not allowed.
    """
    # Defense in depth: system keys are hidden from GET, blocked from PUT,
    # and must also be blocked from reveal. Without this, a project owner
    # could POST /env/reveal {"key":"SMTP_PASS"} and read shared infra creds.
    if _is_system(key):
        logger.warning(f"[ENV] Reveal blocked for system key '{key}'")
        return None

    if not os.path.exists(path):
        return None

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if "=" not in stripped or stripped.startswith("#"):
                continue
            k, _, v = stripped.partition("=")
            k = k.strip()
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                v = v[1:-1]
            if k == key:
                return v

    return None


# ============================================================================
# DELETE
# ============================================================================

def delete_env_keys(path: str, keys: List[str]) -> int:
    """
    Remove specified keys from a .env file.

    - Preserves comments, blank lines, and all other variables.
    - Refuses to delete system/infrastructure keys (safety check).
    - Writes atomically via temp file + os.replace.
    - Sets permissions to 600.

    Args:
        path: Path to .env file
        keys: List of keys to remove

    Returns:
        Number of keys actually removed.
    """
    # Safety: never allow deleting system keys
    keys_to_delete = {k for k in keys if not _is_system(k)}
    if not keys_to_delete:
        return 0

    if not os.path.exists(path):
        return 0

    with open(path, "r", encoding="utf-8") as f:
        existing_lines = f.readlines()

    removed = 0
    new_lines: List[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in keys_to_delete:
                removed += 1
                continue
        new_lines.append(line)

    # Only write if we actually removed something
    if removed > 0:
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    logger.info(f"[ENV] Deleted {removed} variable(s) from {os.path.basename(os.path.dirname(path))}/.env")
    return removed


# ============================================================================
# RESTART
# ============================================================================

def restart_project_if_required(
    project_id: int, type_id: int, domain: Optional[str]
) -> Dict[str, any]:
    """
    Restart the appropriate PM2 process after env changes.

    Dispatches by project type:
        - type_id=1 (website): restart {domain}-backend
        - type_id=2 (telegram): restart via telegram pm2_manager
        - type_id=3 (discord): restart via discord pm2_manager
        - type_id=5 (scheduler): restart shared clawd-scheduler

    Returns:
        Dict with {success: bool, message: str, process: str}
        Non-fatal: if restart fails, returns success=False but does NOT raise.
    """
    result: Dict[str, any] = {
        "success": False,
        "message": "",
        "process": "",
    }

    try:
        if type_id == 1:
            # Website backend
            if not domain:
                # Fallback to project name based process name
                result["message"] = "No domain available, cannot restart website backend"
                return result

            process_name = f"{domain.split('.')[0]}-backend"
            result["process"] = process_name
            r = subprocess.run(
                ["pm2", "restart", process_name],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                result["success"] = True
                result["message"] = f"Restarted {process_name}"
            else:
                result["message"] = f"PM2 restart failed: {r.stderr[:200] if r.stderr else 'unknown'}"
            return result

        elif type_id == 2:
            # Telegram bot
            from services.telegram.pm2_manager import restart_bot_pm2
            success, msg = restart_bot_pm2(project_id, domain)
            result["success"] = success
            result["message"] = msg
            result["process"] = f"tg-bot-{project_id}"
            return result

        elif type_id == 3:
            # Discord bot
            from services.discord.pm2_manager import restart_bot_pm2
            success, msg = restart_bot_pm2(project_id)
            result["success"] = success
            result["message"] = msg
            result["process"] = f"dc-bot-{project_id}"
            return result

        elif type_id == 5:
            # Scheduler (shared centralized process)
            result["process"] = "clawd-scheduler"
            r = subprocess.run(
                ["pm2", "restart", "clawd-scheduler"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if r.returncode == 0:
                result["success"] = True
                result["message"] = "Restarted clawd-scheduler"
            else:
                result["message"] = f"PM2 restart failed: {r.stderr[:200] if r.stderr else 'unknown'}"
            return result

        else:
            result["message"] = f"No restart logic for type_id={type_id}"
            return result

    except subprocess.TimeoutExpired:
        result["message"] = "PM2 restart timed out"
        return result
    except Exception as e:
        logger.error(f"[ENV] Restart failed for project {project_id}: {e}")
        result["message"] = f"Restart error: {str(e)}"
        return result
