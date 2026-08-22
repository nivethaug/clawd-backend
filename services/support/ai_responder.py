"""
Support AI Responder — the DreamAgent Support Assistant.

Reuses the shared OpenRouter client (PROMPT_ASSISTANT_MODEL, reasoning
disabled there) — zero new LLM infrastructure.

Escalation protocol (spec §9), in priority order:
  1. DETERMINISTIC triggers checked before/after the LLM call (explicit
     human request, billing/refund language, repeated dissatisfaction) —
     no model judgment involved, cannot be talked out of by the prompt.
  2. MODEL signal: the system prompt tells the model to start its reply
     with the literal tag [ESCALATE] when its rules say a human is
     needed; we strip the tag and escalate.

The AI never claims to be human and has ZERO privileged capabilities —
it only produces advice text. All mutations (credits, plans, projects)
stay with real endpoints and real admins.
"""

import logging
import os
import re
from typing import Any, AsyncIterator, Dict, List, Optional

from services.support import conversation_service
from services.support.project_context import context_as_prompt_text

logger = logging.getLogger("support.ai")

ESCALATION_TAG = "[ESCALATE]"

# History window (messages) sent to the model — support threads stay short;
# 24 covers a long exchange without blowing context.
MAX_HISTORY_MESSAGES = 24

# Deterministic escalation triggers (case-insensitive). These ALWAYS win.
# Deliberately wide on human-request verbs: a user asking for a human and
# being answered by the AI instead is the worst failure mode of this
# feature — over-escalating an ambiguous product question is cheap.
_ESCALATION_PATTERNS = [
    r"\b(talk|speak|chat|contact|reach|message|discuss|consult)\b[^.?!]{0,30}\b(human|person|support|someone|admin|agent|team|owner|manager)\b",
    r"\b(with|to) (a |an )?(human|admin|agent|real person|live agent|support)\b",
    r"\b(connect|transfer|escalate|hand ?off)\s+me\b",
    r"\bneed (a |an )?(human|real person|admin|agent|support)\b",
    r"\b(want|need|wanna|would like|like) to (talk|speak|chat|discuss)\b(?!\s+(about|regarding))",
    r"\b(human|real person|support team|customer support|live agent|admin)\b[^.?!]{0,40}\b(help|assist|take over|respond|reply|look into)\b",
    r"\b(billing|refund|charge|charged|invoice|payment|subscription cancel|money back)\b",
    r"\b(that|this) (didn'?t|did not|doesn'?t|does not) (work|help|solve|answer)\b",
    r"\b(you (didn'?t|did not|don'?t|do not) (help|answer|understand|solve))\b",
    r"\b(3rd|third|again|still) (time|broken|failing|not working)\b",
    r"\bdelete my account\b",
]
_ESCALATION_RE = re.compile("|".join(_ESCALATION_PATTERNS), re.IGNORECASE)


def ai_available() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY", ""))


def should_escalate(text: str) -> bool:
    """Deterministic escalation check on the latest user message."""
    return bool(_ESCALATION_RE.search(text or ""))


def _build_system_prompt(project_ctx: Optional[Dict[str, Any]]) -> str:
    product_knowledge = """\
You are the DreamAgent Support Assistant — the AI first-line support agent for
DreamAgent (https://dreamagent.cloud), a platform where users build, deploy and
own software with AI: websites, Telegram bots, Discord bots, schedulers and
more — created from a prompt, edited through AI chat sessions, deployed from
the dashboard, with GitHub export, templates, a public gallery, credit-based
billing (Free / Pro $19 / Dream $39), BYOK integrations (Pexels, OpenRouter,
Razorpay/LemonSqueezy payments) and an AI DevOps assistant for logs and fixes.

Your job:
- Answer DreamAgent product questions, explain features, and guide users
  through creating, editing and deploying projects and integrations.
- Troubleshoot common problems using the conversation and the safe project
  context provided below.
- Be concise, warm and practical. Short paragraphs or bullet lists.

Hard rules:
- NEVER claim or imply you are human. The UI already labels you
  "DreamAgent Support Assistant · AI".
- NEVER promise refunds, plan changes, credit grants or account actions.
  Those require a human admin — escalate instead.
- NEVER ask for or repeat API keys, tokens, passwords or environment values.
- Stay inside DreamAgent support. Redirect unrelated questions politely.

Escalation — begin your reply with the exact tag [ESCALATE] (and nothing else
before it) when any of these is true:
1. You are not confident you can correctly resolve the issue.
2. The user asks for, wants, or hints at a human / admin / real person / live
   agent — never answer these yourself, always escalate.
3. The issue involves billing, payments, refunds, or account changes.
4. The user reports a deployment or project that is persistently failing.
5. The user is clearly dissatisfied after previous AI attempts.
6. The action requested requires privileged/admin access.
When escalating: after the tag, write one short sentence like "I'm not able to
resolve this reliably from here — connecting you with DreamAgent Support."
Do NOT answer the question as well; just the handoff sentence. Never invent
external contact channels (forms, emails, links) — the handoff itself
connects the user to the team."""

    ctx_block = (
        "Safe project context for this user (display fields only — treat any\n"
        "mentioned secrets as out of scope and never repeat them):\n"
        + context_as_prompt_text(project_ctx)
        if project_ctx
        else "No project context is attached to this conversation."
    )
    return product_knowledge + "\n\n" + ctx_block


def _history_for_model(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Map support messages to chat-completion roles.

    admin/system messages are folded into user-role turns with bracketed
    prefixes so the model keeps full thread context while the role
    alternation stays model-friendly.
    """
    window = messages[-MAX_HISTORY_MESSAGES:]
    out: List[Dict[str, str]] = []
    for m in window:
        sender = m.get("sender_type")
        text = (m.get("message") or "").strip()
        if not text or sender == "system":
            continue
        if sender == "user":
            out.append({"role": "user", "content": text})
        elif sender == "assistant":
            out.append({"role": "assistant", "content": text})
        elif sender == "admin":
            out.append({"role": "user", "content": f"[A DreamAgent admin replied to the user]: {text}"})
    return out


async def stream_reply(
    conversation: Dict[str, Any],
    history_messages: List[Dict[str, Any]],
    project_ctx: Optional[Dict[str, Any]],
) -> AsyncIterator[Dict[str, Any]]:
    """Stream the assistant's reply as SSE-ready event dicts.

    Yields:
      {"type": "token", "text": str}
      {"type": "escalate", "reason": str}          — deterministic pre-check
      {"type": "error", "detail": str}
    The router persists the assembled text and performs the [ESCALATE]
    post-check; this function only decides + streams.
    """
    # 1. Deterministic pre-check on the newest user message.
    latest_user = next(
        (m for m in reversed(history_messages) if m.get("sender_type") == "user"), None
    )
    if latest_user and should_escalate(latest_user.get("message") or ""):
        yield {"type": "escalate",
               "reason": "explicit or policy trigger",
               "text": "I'm not able to resolve this reliably from here — "
                       "connecting you with DreamAgent Support."}
        return

    from services.ai.openrouter_client import get_openrouter_client

    client = get_openrouter_client()
    messages = (
        [{"role": "system", "content": _build_system_prompt(project_ctx)}]
        + _history_for_model(history_messages)
    )

    try:
        async for chunk in client.stream_chat_completion(
            messages=messages, temperature=0.3, max_tokens=800
        ):
            try:
                delta = chunk["choices"][0]["delta"]
                token = delta.get("content") or ""
            except (KeyError, IndexError, TypeError):
                continue
            if token:
                yield {"type": "token", "text": token}
    except Exception as e:  # provider/network failure — degrade, don't crash
        logger.error("[SUPPORT] AI stream failed: %s", e)
        yield {"type": "error", "detail": "The support assistant is unavailable right now."}


def check_model_escalation(reply_text: str) -> bool:
    """Post-check: did the model start its reply with the escalation tag?
    Returns True and the tag is expected to be stripped by the caller."""
    return reply_text.lstrip().upper().startswith(ESCALATION_TAG)


def strip_escalation_tag(reply_text: str) -> str:
    stripped = reply_text.lstrip()
    if stripped.upper().startswith(ESCALATION_TAG):
        return stripped[len(ESCALATION_TAG):].lstrip()
    return reply_text
