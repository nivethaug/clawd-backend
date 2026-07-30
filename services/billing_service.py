"""
Billing Service — Core credit accounting, cascade deduction, and billing
operations.

Architecture: pure-Python, DB-backed. No external dependencies.

Credit Types (generic — adding new types requires only INSERT, never DDL):
  - project_ai  : AI credits for agent chat / code generation
  - edit_token  : Early Access edit tokens (separate quota)
  - (future: image, video, voice, api, marketplace)

Billing Cascade (when EARLY_ACCESS_MODE is on):
  Edit ops:     edit_token(monthly) → project_ai(monthly) → project_ai(purchased)
  Creation ops: project_ai(monthly) → project_ai(purchased)
  Never blocks while any balance remains. Cascade depletes each tier before
  touching the next.

All mutations are wrapped in transactions. Each deduction writes a
credit_transaction row for full auditability.
"""

import os
import json
import logging
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Token-to-credit conversion ──────────────────────────────────────
# edit_token: 1:1 (1 token = 1 edit token — unchanged)
# project_ai: 1 credit = 1,000 tokens (covers token overflow after
#   edit_token exhausted). This lets project_ai credits absorb large
#   token usage without draining in one chat session.
TOKENS_PER_CREDIT = 1000


# ======================================================================
# Balance helpers
# ======================================================================

def get_or_create_balance(conn, user_id: int, credit_type: str = "project_ai") -> Dict[str, Any]:
    """Get a user's balance for a credit type, creating if missing (monthly_limit 0)."""
    row = conn.execute(
        "SELECT * FROM user_credit_balances WHERE user_id = %s AND credit_type = %s",
        (user_id, credit_type),
    ).fetchone()

    if row is None:
        # Determine monthly_limit from plan
        from services.plan_cache import get_plan, get_plan_grants
        plan = _get_user_plan(conn, user_id)
        grants = get_plan_grants(plan["id"]) if plan else {}
        monthly_limit = grants.get(credit_type, 0)

        conn.execute(
            """INSERT INTO user_credit_balances (user_id, credit_type, monthly_limit, used, purchased)
               VALUES (%s, %s, %s, 0, 0)""",
            (user_id, credit_type, monthly_limit),
        )
        conn.execute("SELECT 1")  # ensure no pending results

        row = conn.execute(
            "SELECT * FROM user_credit_balances WHERE user_id = %s AND credit_type = %s",
            (user_id, credit_type),
        ).fetchone()

    return dict(row) if row and not isinstance(row, dict) else row


def get_all_balances(conn, user_id: int) -> List[Dict[str, Any]]:
    """Get all credit balances for a user."""
    rows = conn.execute(
        "SELECT * FROM user_credit_balances WHERE user_id = %s ORDER BY credit_type",
        (user_id,),
    ).fetchall()
    return [dict(r) if not isinstance(r, dict) else r for r in rows]


def get_monthly_remaining(balance: Dict[str, Any]) -> float:
    """How many monthly credits remain (can be negative if over-spent)."""
    return float(balance["monthly_limit"]) - float(balance["used"])


def get_total_available(balance: Dict[str, Any]) -> float:
    """Total credits available = monthly remaining + purchased."""
    return get_monthly_remaining(balance) + float(balance.get("purchased", 0))


# ======================================================================
# Config / operation helpers
# ======================================================================

def _get_user_plan(conn, user_id: int) -> Optional[Dict[str, Any]]:
    """Look up the user's plan from users.plan_id (FK → plans)."""
    row = conn.execute(
        """SELECT p.* FROM users u JOIN billing_plans p ON u.plan_id = p.id
           WHERE u.id = %s""",
        (user_id,),
    ).fetchone()
    if row is None:
        # Fallback: try getting plan_id directly and cache lookup
        row2 = conn.execute("SELECT plan_id FROM users WHERE id = %s", (user_id,)).fetchone()
        if row2:
            pid = (dict(row2) if not isinstance(row2, dict) else row2).get("plan_id")
            if pid:
                from services.plan_cache import get_plan
                return get_plan(pid)
    return dict(row) if row and not isinstance(row, dict) else row


def is_early_access_enabled() -> bool:
    from services.plan_cache import is_early_access_enabled as _ea
    return _ea()


# ======================================================================
# Cascade: can_afford
# ======================================================================

def _cascade_order(op: Dict[str, Any]) -> List[str]:
    """Determine the credit cascade order for an operation.

    Returns a list of (credit_type, source) pairs to try in order.

    Edit operations (category='edit') ALWAYS try edit_token first (monthly
    then purchased), then fall back to project_ai monthly → purchased.
    This is unconditional (not gated by EARLY_ACCESS_MODE) so edits always
    consume edit tokens first.

    Creation operations use project_ai monthly → project_ai purchased.
    """
    credit_type = op.get("credit_type", "project_ai")
    op_category = op.get("category", "creation")

    # Edit operations: edit_token(monthly) → edit_token(purchased) → project_ai(monthly) → project_ai(purchased)
    if op_category == "edit":
        return [
            ("edit_token", "monthly"),
            ("edit_token", "purchased"),
            ("project_ai", "monthly"),
            ("project_ai", "purchased"),
        ]

    # Creation op
    return [("project_ai", "monthly"), ("project_ai", "purchased")]


def can_afford(conn, user_id: int, operation_code: str, amount: int = 1) -> Dict[str, Any]:
    """Check if a user can afford an operation.

    Returns:
        {
            "can_afford": bool,
            "operation": dict,
            "cost": int,
            "total_available": int,  # across all cascade tiers
            "cascade": [(credit_type, source, available)],
        }
    """
    from services.plan_cache import get_operation

    op = get_operation(operation_code)
    if op is None:
        return {"can_afford": False, "error": f"Unknown operation: {operation_code}", "cost": amount}

    cost = float(op.get("credit_cost", 1)) * amount
    cascade_spec = _cascade_order(op)

    # Build cascade with real balance data
    total_available = 0
    cascade = []
    for credit_type, source in cascade_spec:
        bal = get_or_create_balance(conn, user_id, credit_type)
        if source == "monthly":
            avail = max(0, get_monthly_remaining(bal))
        else:  # purchased
            avail = float(bal.get("purchased", 0))
        total_available += avail
        cascade.append({
            "credit_type": credit_type,
            "source": source,
            "available": avail,
        })

    return {
        "can_afford": total_available >= cost,
        "operation": op,
        "cost": cost,
        "total_available": total_available,
        "cascade": cascade,
    }


# ======================================================================
# Cascade: reserve → commit / refund
# ======================================================================

def _charge_tier(conn, user_id: int, credit_type: str, source: str, amount) -> float:
    """Deduct credits from a specific tier. Returns amount actually deducted."""
    amount = float(amount)
    if amount <= 0:
        return 0

    bal = get_or_create_balance(conn, user_id, credit_type)
    balance_id = bal["id"]

    if source == "monthly":
        remaining = get_monthly_remaining(bal)
        deduct = min(amount, max(0, remaining))
        if deduct > 0:
            conn.execute(
                "UPDATE user_credit_balances SET used = used + %s, updated_at = NOW() WHERE id = %s",
                (deduct, balance_id),
            )
        return deduct
    else:  # purchased
        purchased = float(bal.get("purchased", 0))
        deduct = min(amount, purchased)
        if deduct > 0:
            conn.execute(
                "UPDATE user_credit_balances SET purchased = purchased - %s, updated_at = NOW() WHERE id = %s",
                (deduct, balance_id),
            )
        return deduct


def _record_transaction(
    conn,
    user_id: int,
    credit_type: str,
    operation_id: Optional[int],
    credits: int,
    source: str,
    status: str = "charged",
    cost_usd: float = 0,
    project_id: Optional[int] = None,
    session_id: Optional[int] = None,
    model: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    duration_ms: int = 0,
    provider: Optional[str] = None,
):
    """Write an audit row to credit_transactions."""
    conn.execute(
        """INSERT INTO credit_transactions
           (user_id, operation_id, credit_type, project_id, session_id, credits,
            source, status, cost_usd, model, input_tokens, output_tokens,
            total_tokens, duration_ms, provider)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            user_id, operation_id, credit_type, project_id, session_id, credits,
            source, status, cost_usd, model, input_tokens, output_tokens,
            total_tokens, duration_ms, provider,
        ),
    )


def reserve_credits(conn, user_id: int, operation_code: str, amount: int = 1) -> Dict[str, Any]:
    """Check + reserve credits atomically in cascade order.

    This is a temporary hold.  After the AI operation completes, call
    charge_token_usage() with precharged_amount to reconcile.  If the
    operation fails or consumes fewer tokens than reserved, refund_credits()
    reverses this hold.

    If insufficient, returns {"success": False, ...} WITHOUT modifying balances.
    If sufficient, deducts immediately and returns success.

    Returns:
        {
            "success": bool,
            "operation": dict,
            "cost": int,
            "charged": [{"credit_type", "source", "amount"}, ...],
            "total_available": int,
        }
    """
    from services.plan_cache import get_operation

    op = get_operation(operation_code)
    if op is None:
        return {"success": False, "error": f"Unknown operation: {operation_code}"}

    cost = float(op.get("credit_cost", 1)) * amount

    # Pre-check
    check = can_afford(conn, user_id, operation_code, amount)
    if not check["can_afford"]:
        return {
            "success": False,
            "error": "insufficient_credits",
            "cost": cost,
            "total_available": check["total_available"],
            "operation": op,
        }

    # Cascade charge
    remaining_to_charge = cost
    charged = []

    for tier in check["cascade"]:
        if remaining_to_charge <= 0:
            break
        deduct = _charge_tier(conn, user_id, tier["credit_type"], tier["source"], remaining_to_charge)
        if deduct > 0:
            charged.append({
                "credit_type": tier["credit_type"],
                "source": tier["source"],
                "amount": deduct,
            })
            remaining_to_charge -= deduct

    if remaining_to_charge > 0:
        # Shouldn't happen since we pre-checked, but guard anyway
        return {
            "success": False,
            "error": "insufficient_credits",
            "cost": cost,
            "charged": charged,
            "operation": op,
        }

    # Record transactions as "reserved" (temporary hold — reconciled later)
    for c in charged:
        _record_transaction(
            conn, user_id, c["credit_type"], op.get("id"), -c["amount"], c["source"],
            status="reserved",
        )

    return {
        "success": True,
        "operation": op,
        "cost": cost,
        "charged": charged,
    }


def refund_credits(conn, user_id: int, operation_code: str, charged: List[Dict[str, Any]]):
    """Refund credits from a previous charge (reverses the cascade).

    `charged` is the list returned by reserve_credits()["charged"].
    Records a 'refunded' transaction row for auditability.
    """
    from services.plan_cache import get_operation

    op = get_operation(operation_code)
    op_id = op.get("id") if op else None

    for c in reversed(charged):
        bal = get_or_create_balance(conn, user_id, c["credit_type"])
        balance_id = bal["id"]

        if c["source"] == "monthly":
            conn.execute(
                "UPDATE user_credit_balances SET used = GREATEST(used - %s, 0), updated_at = NOW() WHERE id = %s",
                (c["amount"], balance_id),
            )
        else:  # purchased
            conn.execute(
                "UPDATE user_credit_balances SET purchased = purchased + %s, updated_at = NOW() WHERE id = %s",
                (c["amount"], balance_id),
            )

        # Record refund transaction for audit trail
        _record_transaction(
            conn, user_id, c["credit_type"], op_id, +c["amount"], c["source"],
            status="refunded",
        )




# ======================================================================
# High-level: token-based charge (post-edit reconciliation)
# ======================================================================

def charge_token_usage(
    conn,
    user_id: int,
    total_tokens: int,
    operation_code: str = "ADD_FEATURE",
    project_id: Optional[int] = None,
    session_id: Optional[int] = None,
    model: Optional[str] = None,
    precharged_amount: int = 0,
    cache_read_tokens: int = 0,
) -> Dict[str, Any]:
    """Deduct actual tokens consumed AFTER an AI operation completes.

    This reconciles the temporary pre-charge hold:
      - If actual billable tokens > pre-charged: charge the difference.
      - If actual billable tokens < pre-charged: the excess remains charged
        (the flat admission cost covers it). No additional charge.
      - If actual billable tokens == 0: no charge (pre-charge remains as-is).

    Cache-read tokens are excluded from billing because they are re-reads
    of previously cached context that cost a fraction to process.

    Billable = total_tokens - cache_read_tokens
    Net charge = max(0, billable - precharged_amount)

    Args:
        total_tokens: raw total tokens (input + output, includes cache reads).
        precharged_amount: credits already deducted by the pre-charge hold.
        cache_read_tokens: tokens from cache reads (excluded from charge).

    Returns:
        {"success": bool, "charged": [...], "net_tokens": int,
         "precharged": int, "billable": int, "total_tokens": int}
    """
    from services.plan_cache import get_operation

    op = get_operation(operation_code)
    op_id = op.get("id") if op else None

    if total_tokens <= 0:
        return {
            "success": True, "charged": [], "net_tokens": 0,
            "precharged": precharged_amount, "billable": 0, "total_tokens": 0,
        }

    # Exclude cache-read tokens — they're cheap re-reads, not new processing.
    # Also guard against cache reads > total (shouldn't happen, but be safe).
    billable_tokens = max(0, total_tokens - cache_read_tokens)

    # Subtract what was already pre-charged (flat credits) so we don't
    # double-deduct.  The pre-charge covers the first N tokens.
    net_tokens = max(0, billable_tokens - precharged_amount)

    logger.info(
        f"[BILLING] Token reconciliation for user {user_id}: "
        f"total={total_tokens}, cache_read={cache_read_tokens}, "
        f"billable={billable_tokens}, pre-charged={precharged_amount}, "
        f"net_to_charge={net_tokens}"
    )

    if net_tokens == 0:
        return {
            "success": True, "charged": [], "net_tokens": 0,
            "precharged": precharged_amount, "billable": billable_tokens,
            "total_tokens": total_tokens,
        }

    # Determine cascade: edit_token → project_ai(monthly) → project_ai(purchased)
    cascade = _cascade_order(op or {"category": "edit"})

    remaining = net_tokens  # raw token count
    charged = []

    for tier in cascade:
        if remaining <= 0:
            break
        tier_type, tier_source = tier[0], tier[1]

        # edit_token: 1:1 (raw tokens). project_ai: 1 credit = TOKENS_PER_CREDIT tokens.
        if tier_type == "project_ai":
            charge_amount = remaining // TOKENS_PER_CREDIT  # convert tokens → credits
        else:
            charge_amount = remaining  # edit_token: raw tokens (1:1)

        deduct = _charge_tier(conn, user_id, tier_type, tier_source, charge_amount)
        if deduct > 0:
            charged.append({
                "credit_type": tier_type,
                "source": tier_source,
                "amount": deduct,
            })
            # Convert credits back to tokens for the remaining tally when
            # charging project_ai (so the remainder is in token units for
            # the next tier or the remaining_uncharged report).
            if tier_type == "project_ai":
                remaining -= deduct * TOKENS_PER_CREDIT
            else:
                remaining -= deduct

    # Record audit transactions
    for c in charged:
        _record_transaction(
            conn, user_id, c["credit_type"], op_id, -c["amount"], c["source"],
            status="charged", project_id=project_id, session_id=session_id,
            model=model, total_tokens=total_tokens,
        )

    logger.info(
        f"[BILLING] Token charge applied for user {user_id}: "
        f"net_tokens={net_tokens}, charged={charged}, "
        f"remaining_uncharged={remaining}"
    )

    return {
        "success": True,
        "charged": charged,
        "net_tokens": net_tokens,
        "precharged": precharged_amount,
        "billable": billable_tokens,
        "total_tokens": total_tokens,
        "remaining_uncharged": remaining,  # >0 means user exhausted all tiers
    }


# ======================================================================
# High-level: project creation charge
# ======================================================================

def charge_project_creation(
    conn,
    user_id: int,
    project_type_id: int = None,
    project_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Charge credits for creating a project.

    Looks up the AI operation for the given project_type_id (or defaults to
    the website creation operation). Creation is a final charge rather than a
    temporary reservation because there is no later token reconciliation step.
    """
    from services.plan_cache import get_operation, get_operation_for_type

    fallback_by_type = {
        1: "WEBSITE",
        2: "TELEGRAM_BOT",
        3: "DISCORD_BOT",
        5: "SCHEDULER",
    }
    op_code = fallback_by_type.get(project_type_id, "WEBSITE")
    if project_type_id:
        op = get_operation_for_type(project_type_id)
        if op:
            op_code = op["code"]

    op = get_operation(op_code)
    if op is None:
        return {"success": False, "error": f"Unknown operation: {op_code}"}

    check = can_afford(conn, user_id, op_code, amount=1)
    if not check.get("can_afford"):
        return {
            "success": False,
            "error": "insufficient_credits",
            "cost": check.get("cost"),
            "total_available": check.get("total_available", 0),
            "operation": op,
        }

    remaining_to_charge = float(op.get("credit_cost", 1))
    charged = []

    for tier in check["cascade"]:
        if remaining_to_charge <= 0:
            break
        deduct = _charge_tier(conn, user_id, tier["credit_type"], tier["source"], remaining_to_charge)
        if deduct > 0:
            charged.append({
                "credit_type": tier["credit_type"],
                "source": tier["source"],
                "amount": deduct,
            })
            remaining_to_charge -= deduct

    if remaining_to_charge > 0:
        return {
            "success": False,
            "error": "insufficient_credits",
            "cost": float(op.get("credit_cost", 1)),
            "charged": charged,
            "operation": op,
        }

    for c in charged:
        _record_transaction(
            conn,
            user_id,
            c["credit_type"],
            op.get("id"),
            -c["amount"],
            c["source"],
            status="charged",
            project_id=project_id,
        )

    logger.info(
        "[BILLING] Project creation charge applied for user %s project=%s type=%s op=%s charged=%s",
        user_id,
        project_id,
        project_type_id,
        op_code,
        charged,
    )

    return {
        "success": True,
        "operation": op,
        "cost": float(op.get("credit_cost", 1)),
        "charged": charged,
    }


# ======================================================================
# Purchased credits
# ======================================================================

def add_purchased_credits(conn, user_id: int, credit_type: str, amount: int,
                          source_ref: str = None, source_id: str = None):
    """Add purchased credits (from credit pack purchase, admin grant, etc.).

    Records a credit_transaction with source='purchased'.
    """
    bal = get_or_create_balance(conn, user_id, credit_type)
    conn.execute(
        "UPDATE user_credit_balances SET purchased = purchased + %s, updated_at = NOW() WHERE id = %s",
        (amount, bal["id"]),
    )
    _record_transaction(
        conn, user_id, credit_type, None, +amount, "purchased", status="charged",
    )


# ======================================================================
# Plan sync
# ======================================================================

def sync_balances_to_plan(conn, user_id: int, plan_id: int = None):
    """Update monthly_limit on all balance rows to match the user's plan grants.

    Called when a user's plan changes (upgrade/downgrade).
    Does NOT touch used/purchased — only updates the monthly_limit ceiling.
    """
    from services.plan_cache import get_plan, get_plan_grants, invalidate

    if plan_id is None:
        plan = _get_user_plan(conn, user_id)
        plan_id = plan["id"] if plan else None

    if plan_id is None:
        logger.warning(f"[BILLING] sync_balances_to_plan: no plan for user {user_id}")
        return

    plan = get_plan(plan_id)
    grants = get_plan_grants(plan_id)

    for credit_type, monthly_limit in grants.items():
        # Ensure balance row exists, then update limit
        bal = get_or_create_balance(conn, user_id, credit_type)
        conn.execute(
            "UPDATE user_credit_balances SET monthly_limit = %s, updated_at = NOW() WHERE id = %s",
            (monthly_limit, bal["id"]),
        )

    invalidate("plans")
    logger.info(f"[BILLING] Synced balances for user {user_id} to plan {plan_id}")


def assign_plan(conn, user_id: int, plan_slug_or_id):
    """Assign a plan to a user and sync balances.

    Args:
        plan_slug_or_id: plan slug (str) or id (int)
    """
    from services.plan_cache import get_plan

    plan = get_plan(plan_slug_or_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_slug_or_id}")

    conn.execute("UPDATE users SET plan_id = %s WHERE id = %s", (plan["id"], user_id))
    sync_balances_to_plan(conn, user_id, plan["id"])
    return plan


# ======================================================================
# Summary / reporting
# ======================================================================

def get_user_billing_summary(conn, user_id: int) -> Dict[str, Any]:
    """Get a complete billing summary for a user (for dashboard / frontend)."""
    plan = _get_user_plan(conn, user_id)
    balances = get_all_balances(conn, user_id)

    balance_summaries = []
    for bal in balances:
        monthly_remaining = get_monthly_remaining(bal)
        purchased = float(bal.get("purchased", 0))
        balance_summaries.append({
            "credit_type": bal["credit_type"],
            "monthly_limit": float(bal["monthly_limit"]),
            "used": float(bal["used"]),
            "monthly_remaining": monthly_remaining,
            "purchased": purchased,
            "total_available": max(0, monthly_remaining) + purchased,
            "reset_date": bal.get("reset_date"),
        })

    # Recent transactions
    tx_rows = conn.execute(
        """SELECT ct.*, p.name as project_name, s.label as session_name
           FROM credit_transactions ct
           LEFT JOIN projects p ON ct.project_id = p.id
           LEFT JOIN sessions s ON ct.session_id = s.id
           WHERE ct.user_id = %s
           ORDER BY ct.created_at DESC LIMIT 20""",
        (user_id,),
    ).fetchall()
    transactions = [dict(r) if not isinstance(r, dict) else r for r in tx_rows]

    # Current subscription
    sub_row = conn.execute(
        """SELECT * FROM subscriptions WHERE user_id = %s AND status = 'active'
           ORDER BY created_at DESC LIMIT 1""",
        (user_id,),
    ).fetchone()
    subscription = dict(sub_row) if sub_row and not isinstance(sub_row, dict) else sub_row

    return {
        "plan": plan,
        "balances": balance_summaries,
        "transactions": transactions,
        "subscription": subscription,
        "early_access_enabled": is_early_access_enabled(),
    }


# ======================================================================
# Monthly reset
# ======================================================================

def reset_monthly_credits(conn, user_id: int = None):
    """Reset `used` to 0 for all (or one user's) monthly balances.

    Should be called by the monthly cron job.
    """
    if user_id:
        rows = conn.execute(
            "SELECT id, user_id, credit_type FROM user_credit_balances WHERE user_id = %s",
            (user_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, user_id, credit_type FROM user_credit_balances"
        ).fetchall()

    count = 0
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        conn.execute(
            """UPDATE user_credit_balances
               SET used = 0,
                   reset_date = (CURRENT_DATE + INTERVAL '1 month' - (EXTRACT(DAY FROM CURRENT_DATE)::int - 1))::date,
                   updated_at = NOW()
               WHERE id = %s""",
            (d["id"],),
        )
        _record_transaction(
            conn, d["user_id"], d["credit_type"], None, 0, "system", status="system",
        )
        count += 1

    logger.info(f"[BILLING] Reset monthly credits for {count} balance rows")
    return count
