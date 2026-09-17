"""Email Guard — block disposable/temporary email domains at registration.

Scope (deliberate):
- NEW signups only: existing users are never touched.
- Curated built-in list (~100 well-known disposable domains). No external
  dependency, no network call, instant. Extend by adding to the frozenset
  (or later via a billing_config-style DB key if it needs to be runtime
  editable).

Also fixes a latent normalization gap: signup used the raw email string,
so Foo@X.com and foo@x.com created separate accounts. normalize_email()
is applied before the duplicate check and INSERT at both signup paths.
"""

import re

# Well-known disposable / temporary email domains (lowercase).
DISPOSABLE_DOMAINS: frozenset = frozenset({
    # Classic temp-mail services
    "mailinator.com", "mailinator.net", "sogetthis.com", "spamhere.com",
    "trashmail.com", "trashmail.de", "trash-mail.com", "kurzepost.de",
    "10minutemail.com", "10minutemail.net", "20minutemail.com",
    "tempmail.com", "temp-mail.org", "temp-mail.io", "tempmailo.com",
    "tempr.email", "tempail.com", "tempinbox.com", "tempemail.co",
    "throwawaymail.com", "throwam.com", "mailexpire.com",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org",
    "guerrillamail.biz", "guerrillamailblock.com", "grr.la", "sharklasers.com",
    "spam4.me", "pokemail.net",
    "yopmail.com", "yopmail.net", "yopmail.fr", "yopmail.net",
    "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc",
    "getnada.com", "nada.email", "inboxbear.com", "tafmail.com",
    "dispostable.com", "maildrop.cc", "fakeinbox.com", "mailnesia.com",
    "mytemp.email", "emailondeck.com", "moakt.com", "mvrht.net",
    "linshiyouxiang.net", "bccto.me", "chacuo.net", "027168.com",
    # Dropmail / generic generators
    "dropmail.me", "dropmail.net", "emltmp.com", "mailtemp.net",
    "spamgourmet.com", "spamhole.com", "spambog.com", "spambox.us",
    "burnermail.io", "burner-mail.com",
    # Anon / relay style
    "anonbox.net", "anon.email", "anonbox.org", "mailnull.com",
    "incognitomail.com", "incognitomail.org", "incognitomail.net",
    "mytrashmail.com", "mailcatch.com", "mintemail.com", "meltmail.com",
    "maileater.com", "jetable.org", "jetable.com",
    # Aliasing services commonly abused for one-off signups
    "mail7.io", "1secmail.com", "1secmail.org", "1secmail.net", "1secmail.net",
    "esiix.com", "wwjmp.com", "xojxe.com", "yoggm.com",
    "vjuum.com", "laafd.net", "txcct.com",
    "email-fake.com", "emailfake.com", "fakemail.net", "fakemailgenerator.com",
    "freemail.temp", "instantemailaddress.com", "harakirimail.com",
    "mailtemp.info", "temporaryemail.net", "temporaryinbox.com",
    "discard.email", "discardmail.com", "discardmail.de",
    "fake-mail.net", "fleckens.hu", "gufum.com", "hits1.net",
    "byom.de", "elhamar.com", "fviain.com", "inboxalias.com",
    "zetmail.com", "spam4.me", "tmpmail.org", "tmpmail.net",
    "mailde.de", "mailde.info", "mail-temp.com", "mailtemp.uk",
    "instant-mail.de", "trash2009.com", "mega-z.com", "spamfree24.org",
    "keepmymail.com", "sneakemail.com", "binkmail.com", "bobmail.info",
    "chammy.info", "devnullmail.com", "letthemeatspam.com",
    "mailin8r.com", "mailinater.com", "mailinator2.com", "reallymymail.com",
    "sofort-mail.de", "sofortmail.de", "superrito.com", "teleworm.us",
    "upliftnow.com", "venompen.com", "safetymail.info", "sendspamhere.com",
})

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
