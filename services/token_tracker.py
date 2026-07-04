"""
Token Usage Tracker — Record and query AI token consumption.

Table: token_usage
  - user_id     : who used the tokens
  - project_id  : which project (nullable for non-project usage)
  - session_id  : which chat session (nullable)
  - usage_type  : 'ai_chat', 'project_create', 'ai_completion'
  - description : human-readable note
  - input_tokens / output_tokens / total_tokens
  - model       : which AI model was used
  - created_at  : when

Usage:
    from services.token_tracker import record_usage, get_user_usage

    # Record AI chat tokens
    record_usage(user_id=1, usage_type="ai_chat", total_tokens=500,
                 project_id=5, session_id=12, model="claude-sonnet")

    # Record project creation tokens
    record_usage(user_id=1, usage_type="project_create", total_tokens=1200,
                 project_id=5, description="Website: my-site")

    # Query user's total usage this month
    get_user_usage(user_id=1, period="month")
"""

import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Valid usage types
VALID_USAGE_TYPES = {"ai_chat", "project_create", "ai_completion"}


def record_usage(
    user_id: int,
    usage_type: str,
    total_tokens: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    project_id: Optional[int] = None,
    session_id: Optional[int] = None,
    description: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    cost_usd: float = 0.0,
    duration_ms: int = 0,
    operation: Optional[str] = None,
    credits_charged: int = 0,
) -> bool:
    """
    Record a token usage event.

    Args:
        user_id: The user who consumed the tokens
        usage_type: One of 'ai_chat', 'project_create', 'ai_completion'
        total_tokens: Total tokens consumed
        input_tokens: Input/prompt tokens
        output_tokens: Output/completion tokens
        project_id: Associated project (nullable)
        session_id: Associated chat session (nullable)
        description: Human-readable description
        model: AI model used
        provider: AI provider (e.g. 'glm', 'openai')
        cost_usd: Estimated cost in USD
        duration_ms: Request duration in milliseconds
        operation: Billing operation code (e.g. 'ADD_FEATURE', 'WEBSITE')
        credits_charged: Credits deducted for this request

    Returns:
        True if recorded successfully, False otherwise
    """
    if usage_type not in VALID_USAGE_TYPES:
        logger.warning(f"Invalid usage_type '{usage_type}', skipping token tracking")
        return False

    # Guard: token_usage.user_id has a FK to users(id).
    # Unauthenticated flows (e.g. Prompt Assistant) may pass user_id=0 or
    # None. Skip gracefully rather than triggering a FK violation.
    if not user_id or user_id <= 0:
        logger.debug(
            f"[TOKEN] Skipping record_usage ({usage_type}, {total_tokens} tokens) — "
            f"no valid user_id ({user_id})"
        )
        return False

    # If total_tokens not provided but input+output are, calculate
    if total_tokens == 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens

    # If individual tokens not provided but total is, estimate 60/40 split
    if total_tokens > 0 and input_tokens == 0 and output_tokens == 0:
        input_tokens = int(total_tokens * 0.6)
        output_tokens = total_tokens - input_tokens

    try:
        from database_adapter import get_db

        with get_db() as conn:
            conn.execute(
                """INSERT INTO token_usage
                   (user_id, project_id, session_id, usage_type, description,
                    input_tokens, output_tokens, total_tokens, model,
                    provider, cost_usd, operation, credits_charged, duration_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    user_id,
                    project_id,
                    session_id,
                    usage_type,
                    description,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    model,
                    provider,
                    cost_usd,
                    operation,
                    credits_charged,
                    duration_ms,
                ),
            )
            conn.commit()

        logger.info(
            f"[TOKEN] Recorded {usage_type}: {total_tokens} tokens for user {user_id}"
            + (f" project={project_id}" if project_id else "")
            + (f" model={model}" if model else "")
        )
        return True

    except Exception as e:
        logger.error(f"[TOKEN] Failed to record usage: {e}")
        return False


def record_from_token_usage_json(
    user_id: int,
    token_usage_json: Any,
    usage_type: str = "ai_chat",
    project_id: Optional[int] = None,
    session_id: Optional[int] = None,
    description: Optional[str] = None,
) -> bool:
    """
    Record usage from the token_usage JSON dict that handlers return.
    Expected format: {"input_tokens": N, "output_tokens": N, "total_tokens": N, "model": "..."}
    Also accepts: {"inputTokens": N, "outputTokens": N, "totalTokens": N}
    """
    if not token_usage_json:
        return False

    try:
        if isinstance(token_usage_json, str):
            import json
            token_usage_json = json.loads(token_usage_json)

        input_t = (
            token_usage_json.get("input_tokens")
            or token_usage_json.get("inputTokens")
            or 0
        )
        output_t = (
            token_usage_json.get("output_tokens")
            or token_usage_json.get("outputTokens")
            or 0
        )
        total_t = (
            token_usage_json.get("total_tokens")
            or token_usage_json.get("totalTokens")
            or (input_t + output_t)
        )
        model_name = token_usage_json.get("model")
        provider = token_usage_json.get("provider")
        cost_usd = float(token_usage_json.get("cost_usd", 0) or 0)
        duration_ms = int(token_usage_json.get("duration_ms", 0) or 0)
        operation = token_usage_json.get("operation")
        credits_charged = int(token_usage_json.get("credits_charged", 0) or 0)

        return record_usage(
            user_id=user_id,
            usage_type=usage_type,
            total_tokens=int(total_t),
            input_tokens=int(input_t),
            output_tokens=int(output_t),
            project_id=project_id,
            session_id=session_id,
            description=description,
            model=model_name,
            provider=provider,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            operation=operation,
            credits_charged=credits_charged,
        )

    except Exception as e:
        logger.error(f"[TOKEN] Failed to parse token_usage JSON: {e}")
        return False


# ============================================================================
# Query Functions
# ============================================================================


def get_user_usage(
    user_id: int,
    period: str = "month",
    usage_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get aggregated token usage for a user.

    Args:
        user_id: User ID
        period: 'day', 'week', 'month', 'all'
        usage_type: Filter by type (optional)

    Returns:
        {
            "user_id": 1,
            "period": "month",
            "total_tokens": 50000,
            "input_tokens": 30000,
            "output_tokens": 20000,
            "by_type": {
                "ai_chat": {"total_tokens": 40000, "count": 120},
                "project_create": {"total_tokens": 10000, "count": 5},
            },
            "daily": [{"date": "2026-06-01", "total_tokens": 5000}, ...],
        }
    """
    where_date = _period_to_where(period)

    type_filter = ""
    params: list = [user_id]

    if usage_type:
        type_filter = "AND usage_type = %s"
        params.append(usage_type)

    from database_adapter import get_db

    try:
        with get_db() as conn:
            # Overall totals
            row = conn.execute(
                f"""SELECT
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(input_tokens), 0) as input_tokens,
                    COALESCE(SUM(output_tokens), 0) as output_tokens,
                    COUNT(*) as count
                FROM token_usage
                WHERE user_id = %s {where_date} {type_filter}""",
                tuple(params),
            ).fetchone()

            totals = {
                "total_tokens": row["total_tokens"] if isinstance(row, dict) else row[0],
                "input_tokens": row["input_tokens"] if isinstance(row, dict) else row[1],
                "output_tokens": row["output_tokens"] if isinstance(row, dict) else row[2],
                "count": row["count"] if isinstance(row, dict) else row[3],
            }

            # Breakdown by usage_type
            by_type_rows = conn.execute(
                f"""SELECT
                    usage_type,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(input_tokens), 0) as input_tokens,
                    COALESCE(SUM(output_tokens), 0) as output_tokens,
                    COUNT(*) as count
                FROM token_usage
                WHERE user_id = %s {where_date}
                GROUP BY usage_type
                ORDER BY total_tokens DESC""",
                tuple([user_id]),
            ).fetchall()

            by_type = {}
            for r in by_type_rows:
                key = r["usage_type"] if isinstance(r, dict) else r[0]
                by_type[key] = {
                    "total_tokens": r["total_tokens"] if isinstance(r, dict) else r[1],
                    "input_tokens": r["input_tokens"] if isinstance(r, dict) else r[2],
                    "output_tokens": r["output_tokens"] if isinstance(r, dict) else r[3],
                    "count": r["count"] if isinstance(r, dict) else r[4],
                }

            # Daily breakdown (last 30 days max)
            daily_rows = conn.execute(
                f"""SELECT
                    DATE(created_at) as date,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as count
                FROM token_usage
                WHERE user_id = %s {where_date} {type_filter}
                GROUP BY DATE(created_at)
                ORDER BY date DESC
                LIMIT 30""",
                tuple(params),
            ).fetchall()

            daily = [
                {
                    "date": str(r["date"] if isinstance(r, dict) else r[0]),
                    "total_tokens": r["total_tokens"] if isinstance(r, dict) else r[1],
                    "count": r["count"] if isinstance(r, dict) else r[2],
                }
                for r in daily_rows
            ]

        return {
            "user_id": user_id,
            "period": period,
            **totals,
            "by_type": by_type,
            "daily": daily,
        }

    except Exception as e:
        logger.error(f"[TOKEN] Failed to query usage: {e}")
        return {"user_id": user_id, "period": period, "error": str(e)}


def get_project_usage(
    project_id: int,
    period: str = "all",
) -> Dict[str, Any]:
    """Get aggregated token usage for a project."""
    where_date = _period_to_where(period)

    from database_adapter import get_db

    try:
        with get_db() as conn:
            row = conn.execute(
                f"""SELECT
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(input_tokens), 0) as input_tokens,
                    COALESCE(SUM(output_tokens), 0) as output_tokens,
                    COUNT(*) as count
                FROM token_usage
                WHERE project_id = %s {where_date}""",
                (project_id,),
            ).fetchone()

        totals = {
            "total_tokens": row["total_tokens"] if isinstance(row, dict) else row[0],
            "input_tokens": row["input_tokens"] if isinstance(row, dict) else row[1],
            "output_tokens": row["output_tokens"] if isinstance(row, dict) else row[2],
            "count": row["count"] if isinstance(row, dict) else row[3],
        }

        return {"project_id": project_id, "period": period, **totals}

    except Exception as e:
        logger.error(f"[TOKEN] Failed to query project usage: {e}")
        return {"project_id": project_id, "error": str(e)}


def get_platform_usage(period: str = "month") -> Dict[str, Any]:
    """Get platform-wide aggregated usage (admin only)."""
    where_date = _period_to_where(period)
    where_date_tu = _period_to_where(period, table="tu")

    from database_adapter import get_db

    try:
        with get_db() as conn:
            row = conn.execute(
                f"""SELECT
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COALESCE(SUM(input_tokens), 0) as input_tokens,
                    COALESCE(SUM(output_tokens), 0) as output_tokens,
                    COUNT(*) as count,
                    COUNT(DISTINCT user_id) as unique_users,
                    COALESCE(SUM(cost_usd), 0) as total_cost
                FROM token_usage
                WHERE 1=1 {where_date}""",
                (),
            ).fetchone()

            by_type_rows = conn.execute(
                f"""SELECT
                    usage_type,
                    COALESCE(SUM(total_tokens), 0) as total_tokens,
                    COUNT(*) as count,
                    COALESCE(SUM(cost_usd), 0) as total_cost
                FROM token_usage
                WHERE 1=1 {where_date}
                GROUP BY usage_type
                ORDER BY total_tokens DESC""",
                (),
            ).fetchall()

            by_user_rows = conn.execute(
                f"""SELECT
                    tu.user_id,
                    u.email,
                    u.name,
                    COALESCE(SUM(tu.total_tokens), 0) as total_tokens,
                    COUNT(*) as count,
                    COALESCE(SUM(tu.cost_usd), 0) as total_cost
                FROM token_usage tu
                JOIN users u ON u.id = tu.user_id
                WHERE 1=1 {where_date_tu}
                GROUP BY tu.user_id, u.email, u.name
                ORDER BY total_tokens DESC
                LIMIT 20""",
                (),
            ).fetchall()

        def v(r, k, i):
            return r[k] if isinstance(r, dict) else r[i]

        return {
            "period": period,
            "total_tokens": v(row, "total_tokens", 0),
            "input_tokens": v(row, "input_tokens", 1),
            "output_tokens": v(row, "output_tokens", 2),
            "count": v(row, "count", 3),
            "unique_users": v(row, "unique_users", 4),
            "total_cost_usd": v(row, "total_cost", 5),
            "by_type": {
                v(r, "usage_type", 0): {
                    "total_tokens": v(r, "total_tokens", 1),
                    "count": v(r, "count", 2),
                    "total_cost_usd": v(r, "total_cost", 3),
                }
                for r in by_type_rows
            },
            "top_users": [
                {
                    "user_id": v(r, "user_id", 0),
                    "email": v(r, "email", 1),
                    "name": v(r, "name", 2),
                    "total_tokens": v(r, "total_tokens", 3),
                    "count": v(r, "count", 4),
                    "total_cost_usd": v(r, "total_cost", 5),
                }
                for r in by_user_rows
            ],
        }

    except Exception as e:
        logger.error(f"[TOKEN] Failed to query platform usage: {e}")
        return {"period": period, "error": str(e)}


def get_usage_logs(
    user_id: Optional[int] = None,
    project_id: Optional[int] = None,
    usage_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get raw usage log entries with filters.
    """
    conditions = []
    params: list = []

    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)
    if project_id:
        conditions.append("project_id = %s")
        params.append(project_id)
    if usage_type:
        conditions.append("usage_type = %s")
        params.append(usage_type)

    where = " AND ".join(conditions) if conditions else "1=1"

    from database_adapter import get_db

    try:
        with get_db() as conn:
            rows = conn.execute(
                f"""SELECT
                    id, user_id, project_id, session_id,
                    usage_type, description,
                    input_tokens, output_tokens, total_tokens,
                    model, cost_usd, created_at
                FROM token_usage
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
                tuple(params + [limit, offset]),
            ).fetchall()

            total_row = conn.execute(
                f"SELECT COUNT(*) as cnt FROM token_usage WHERE {where}",
                tuple(params),
            ).fetchone()
            total = total_row["cnt"] if isinstance(total_row, dict) else total_row[0]

        def row_to_dict(r):
            if isinstance(r, dict):
                return {**r, "created_at": str(r["created_at"])}
            return {
                "id": r[0], "user_id": r[1], "project_id": r[2],
                "session_id": r[3], "usage_type": r[4], "description": r[5],
                "input_tokens": r[6], "output_tokens": r[7], "total_tokens": r[8],
                "model": r[9], "cost_usd": float(r[10]) if r[10] is not None else 0.0,
                "created_at": str(r[11]),
            }

        return {
            "logs": [row_to_dict(r) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error(f"[TOKEN] Failed to query usage logs: {e}")
        return {"logs": [], "total": 0, "error": str(e)}


# ============================================================================
# Helpers
# ============================================================================


def _period_to_where(period: str, table: str = "") -> str:
    """Convert a period string to a SQL WHERE clause for created_at.
    
    Args:
        period: 'day', 'week', 'month', 'all'
        table: Optional table alias prefix (e.g. 'tu') to avoid ambiguous column
               references in JOINs.
    """
    prefix = f"{table}." if table else ""
    if period == "day":
        return f"AND {prefix}created_at >= CURRENT_DATE"
    elif period == "week":
        return f"AND {prefix}created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif period == "month":
        return f"AND {prefix}created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif period == "all":
        return ""
    else:
        return ""
