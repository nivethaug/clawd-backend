"""Email guard unit tests — disposable-domain blocklist + normalization.

Pure-unit style (no DB, no network), matching the plain pytest convention
of tests/test_completion_service.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.email_guard import (
    DISPOSABLE_MESSAGE,
    INVALID_MESSAGE,
    is_disposable_email,
    normalize_email,
)


# ---------------------------------------------------------------------------
# normalize_email
# ---------------------------------------------------------------------------

def test_normalize_strips_and_lowercases():
    assert normalize_email("  Foo.Bar@GMAIL.COM ") == "foo.bar@gmail.com"


def test_normalize_handles_none_safely():
    assert normalize_email(None) == ""
    assert normalize_email("") == ""


# ---------------------------------------------------------------------------
# Valid emails pass
# ---------------------------------------------------------------------------

def _passes(email):
    blocked, reason = is_disposable_email(email)
    assert blocked is False, (email, reason)
    assert reason is None


def test_valid_regular_emails_pass():
    for email in (
        "user@gmail.com",
        "first.last@outlook.com",
        "o'brian@example.co.uk",
        "dev+signup@my-startup.io",
        "a@sub.domain.org",
        "USER@COMPANY.COM",
        "  padded@gmail.com  ",
    ):
        _passes(email)


# ---------------------------------------------------------------------------
# Disposable domains blocked
# ---------------------------------------------------------------------------

def _blocked(email, expected_reason=DISPOSABLE_MESSAGE):
    blocked, reason = is_disposable_email(email)
    assert blocked is True, email
    assert reason == expected_reason, (email, reason)


def test_known_disposable_domains_blocked():
    for domain in (
        "mailinator.com", "10minutemail.com", "temp-mail.org",
        "guerrillamail.com", "sharklasers.com", "yopmail.com",
        "trashmail.com", "maildrop.cc", "getnada.com", "1secmail.com",
        "yzcalo.com", "mail.tm", "tempmail.plus",
    ):
        _blocked(f"someone@{domain}")


def test_uppercase_disposable_domain_blocked():
    # Normalization means case variants are caught too.
    _blocked("Someone@MAILINATOR.COM")
    _blocked("someone@Mailinator.Com")


def test_plus_tag_still_detected_via_domain():
    _blocked("mytag+spam@guerrillamail.com")


def test_subdomain_of_disposable_not_whitelisted():
    # A subdomain of a blocked domain is a DIFFERENT domain string — the
    # guard is exact-match by design (no false positives on lookalikes).
    blocked, _ = is_disposable_email("x@fake.mailinator.com")
    assert blocked is False


# ---------------------------------------------------------------------------
# Invalid formats rejected
# ---------------------------------------------------------------------------

def test_invalid_formats_rejected():
    for bad in (
        "no-at-sign.com",
        "double@@example.com",
        "@example.com",           # empty local part
        "user@",                  # empty domain
        "user@nopdot",            # domain without a dot
        "user name@example.com",  # space
        "",                       # empty
    ):
        blocked, reason = is_disposable_email(bad)
        assert blocked is True, bad
        assert reason == INVALID_MESSAGE


def test_reason_messages_distinct():
    assert DISPOSABLE_MESSAGE != INVALID_MESSAGE
    assert "disposable" in DISPOSABLE_MESSAGE.lower()
    assert "valid" in INVALID_MESSAGE.lower()
