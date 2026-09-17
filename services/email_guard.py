"""Email Guard — block disposable/temporary email domains at registration.

Domain sources (union, loaded once at import):
1. data/disposable_email_domains.txt — the community blocklist
   (github.com/disposable-email-domains/disposable-email-domains, ~8.9k
   domains). REFRESH with: python scripts/update_disposable_domains.py
2. _EXTRA_DOMAINS below — curated additions the community list misses
   (temp-mail.io rotating domains, mail.tm family, etc).

Scope (deliberate):
- NEW signups only: existing users are never touched.
- No network calls at runtime — the list ships as a data file.

Also fixes a latent normalization gap: signup used the raw email string,
so Foo@X.com and foo@x.com created separate accounts. normalize_email()
is applied before the duplicate check and INSERT at both signup paths.
"""

import re
from pathlib import Path

# Curated additions not in the community list (keep sorted-ish by service).
_EXTRA_DOMAINS: frozenset = frozenset({
    # temp-mail.io rotating family
    "yzcalo.com", "laafd.net", "txcct.com", "vjuum.com", "emltmp.com",
    "temp-mail.io",
    # mail.tm service family
    "mttmm.net",
    # misc confirmed
    "tempemail.co", "freemail.temp", "fake-mail.net", "instaemail.net",
    "summarli.com", "burner-mail.com", "sneakemail.com", "anon.email",
    "anonbox.org", "hits1.net", "fviain.com",
})


def _load_domains() -> frozenset:
    """Load community list + curated extras (union). Fail-open to extras
    only if the data file is missing (deploy mistakes ship the file)."""
    path = Path(__file__).resolve().parent.parent / "data" / "disposable_email_domains.txt"
    try:
        domains = {
            line.strip().lower()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#") and "." in line
        }
    except OSError:
        domains = set()
    return frozenset(domains | _EXTRA_DOMAINS)


DISPOSABLE_DOMAINS: frozenset = _load_domains()

# Minimal format sanity: exactly one @, non-empty local part, domain with a
# dot, allowed chars only. Not a full RFC validator — catches typos/junk.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")

DISPOSABLE_MESSAGE = (
    "Please use a permanent email address — disposable email domains "
    "are not allowed."
)
INVALID_MESSAGE = "Please enter a valid email address."


def normalize_email(email: str) -> str:
    """Strip + lowercase an email so case/whitespace variants dedupe."""
    return (email or "").strip().lower()


def is_disposable_email(email: str) -> "tuple[bool, str | None]":
    """Validate an email and check its domain against the blocklist.

    Returns (blocked, reason): reason is a user-facing message when
    blocked is True, else None.
    """
    normalized = normalize_email(email)
    if not _EMAIL_RE.match(normalized):
        return True, INVALID_MESSAGE
    domain = normalized.rsplit("@", 1)[1]
    if domain in DISPOSABLE_DOMAINS:
        return True, DISPOSABLE_MESSAGE
    return False, None
