"""PM2 environment hygiene for customer-deployed services.

Customer apps (website backends/frontends, Telegram/Discord bots) must NEVER
inherit the platform worker's environment: without an explicit ``env=``,
``subprocess.run(["pm2", ...])`` copies the caller's full backpack —
OPENROUTER_API_KEY, DB_PASSWORD, NANGO_SECRET_KEY, INTERNAL_API_SECRET, … —
straight into the customer process (observed in production: a deployed app
used a credit-less platform OpenRouter key that shadowed the customer's own
``backend/.env`` key; 402s until the priority was hacked around).

The container path already solves this with _CONTAINER_ENV_ALLOWLIST; this
module is the PM2 equivalent. Project-specific values reach apps through the
ecosystem config ``env`` block and each project's ``.env`` file — never
through inherited environment.
"""

import os

# Non-secret plumbing every process needs. Copied from the CURRENT
# environment (so PATH resolves node/pm2 wherever they live) — these carry
# no secrets. Everything else is dropped.
_SAFE_BASE_KEYS = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    # PM2 daemon socket location (only set when a custom root is used;
    # default ~/.pm2 needs only HOME).
    "PM2_HOME",
)


def clean_pm2_env(extra: dict | None = None) -> dict:
    """Minimal, secret-free environment for pm2 CLI invocations.

    Returns ONLY the safe base keys above (plus ``extra`` for the rare
    caller that must add a project var explicitly). Pass as ``env=`` to
    every ``subprocess.run(["pm2", ...])`` that starts or restarts a
    customer service.
    """
    env = {k: os.environ[k] for k in _SAFE_BASE_KEYS if os.environ.get(k)}
    if extra:
        env.update(extra)
    return env


# Platform secrets that must NEVER appear in a customer process's
# environment. Used by scripts/pm2_env_scrub.py to VERIFY exposure and
# confirm the scrub worked (checked against /proc/<pid>/environ, the
# ground truth for what a running process actually carries).
PLATFORM_SECRET_KEYS = (
    "DB_PASSWORD",
    "DB_USER",
    "DB_HOST",
    "DB_NAME",
    "DATABASE_URL",
    "NANGO_SECRET_KEY",
    "INTERNAL_API_SECRET",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ZAI_API_KEY",
    "Z_AI_API_KEY",
    "GITHUB_TOKEN",
    "GITHUB_CLIENT_SECRET",
    "LEMONSQUEEZY_WEBHOOK_SECRET",
    "STRIPE_SECRET_KEY",
    "RAZORPAY_KEY_SECRET",
    "HOSTINGER_TOKEN",
    "SENTRY_DSN",
    "WORKER_VPS_URL",
    "SMTP_PASS",
)
