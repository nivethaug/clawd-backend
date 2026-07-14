"""Shared billing summary formatting for external bot integrations."""

from typing import Any


def _format_int(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except Exception:
        return str(value or 0)


def _format_money_cents(value: Any) -> str:
    try:
        cents = int(value or 0)
        return "$0/mo" if cents == 0 else f"${cents / 100:.0f}/mo"
    except Exception:
        return "$0/mo"


def _credit_label(credit_type: str) -> str:
    labels = {
        "project_ai": "AI credits",
        "edit_token": "Edit tokens",
    }
    return labels.get((credit_type or "").lower(), (credit_type or "Credits").replace("_", " ").title())


def _bold(text: str, marker: str) -> str:
    return f"{marker}{text}{marker}" if marker else text


def format_billing_summary(conn, user_id: int, *, bold_marker: str = "*") -> str:
    """Return the same concise billing summary for Telegram and Discord."""
    from services.billing_service import get_user_billing_summary

    summary = get_user_billing_summary(conn, user_id)
    plan = summary.get("plan") or {}
    plan_name = plan.get("name") or plan.get("slug") or "Free"
    plan_price = _format_money_cents(plan.get("price_monthly_cents"))

    lines = [
        _bold("Billing & Credits", bold_marker),
        f"Plan: {_bold(plan_name, bold_marker)} ({plan_price})",
        "",
        _bold("Balances", bold_marker),
    ]

    balances = summary.get("balances") or []
    if balances:
        for bal in balances:
            label = _credit_label(bal.get("credit_type"))
            total = _format_int(bal.get("total_available"))
            used = _format_int(bal.get("used"))
            limit = _format_int(bal.get("monthly_limit"))
            purchased = int(bal.get("purchased") or 0)
            extra = f", {_format_int(purchased)} purchased" if purchased else ""
            lines.append(f"- {label}: {_bold(f'{total} available', bold_marker)} ({used}/{limit} used{extra})")
    else:
        lines.append("- No credit balances found yet.")

    transactions = summary.get("transactions") or []
    if transactions:
        lines.extend(["", _bold("Recent activity", bold_marker)])
        for tx in transactions[:3]:
            credits = int(tx.get("credits") or 0)
            sign = "+" if credits > 0 else ""
            label = _credit_label(tx.get("credit_type"))
            status = (tx.get("status") or "").replace("_", " ").title()
            project = tx.get("project_name") or tx.get("session_name")
            context = f" - {project}" if project else ""
            lines.append(f"- {sign}{_format_int(credits)} {label} ({status}){context}")

    lines.extend([
        "",
        "Open Billing in DreamAgent to upgrade plans or buy credit packs.",
    ])
    return "\n".join(lines)
