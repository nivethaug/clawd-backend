#!/usr/bin/env python3
"""
Email Service - Sends emails via shared SMTP (same as scheduler validator).
Used for email verification on signup.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from dotenv import load_dotenv

import logging
logger = logging.getLogger(__name__)

from domain_config import DEFAULT_SUPPORT_EMAIL, DEFAULT_FROM_EMAIL

load_dotenv()

# SMTP configuration (same defaults as scheduler/validator.py)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", DEFAULT_SUPPORT_EMAIL)
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", DEFAULT_FROM_EMAIL)

# Admin support emails (Admin Users grid → Mail) go out from this alias.
# Overridable via ADMIN_EMAIL_FROM; the SMTP account must be allowed to
# send as this alias (Hostinger: any alias on the authenticated mailbox).
ADMIN_EMAIL_FROM = os.getenv("ADMIN_EMAIL_FROM", "help@dreamagent.cloud")

# Frontend URL for verification links (static — always dreamagent.cloud)
FRONTEND_URL = "https://dreamagent.cloud"


def send_verification_email(to_email: str, token: str, user_name: Optional[str] = None) -> bool:
    """
    Send an email verification link to the user.

    Args:
        to_email: Recipient email address
        token: Verification token
        user_name: Optional user name for personalization

    Returns:
        True if sent successfully, False otherwise
    """
    verify_url = f"{FRONTEND_URL}/verify-email?token={token}"
    display_name = user_name or to_email.split("@")[0]

    html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
  <div style="text-align: center; margin-bottom: 32px;">
    <h1 style="font-size: 28px; font-weight: bold; margin: 0; background: linear-gradient(135deg, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">DreamAgent</h1>
    <p style="color: #6b7280; margin-top: 8px;">Your friendly VPS assistant</p>
  </div>
  <div style="background: #ffffff; border-radius: 16px; padding: 32px; border: 1px solid #e5e7eb;">
    <h2 style="font-size: 20px; margin: 0 0 16px;">Verify your email ✅</h2>
    <p style="color: #4b5563; font-size: 15px; line-height: 1.6;">
      Hi {display_name},<br><br>
      Welcome to DreamAgent! Please verify your email address to activate your account and start building.
    </p>
    <div style="text-align: center; margin: 28px 0;">
      <a href="{verify_url}" style="display: inline-block; background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #ffffff; font-size: 15px; font-weight: 600; padding: 14px 32px; border-radius: 12px; text-decoration: none;">
        Verify Email
      </a>
    </div>
    <p style="color: #9ca3af; font-size: 13px; line-height: 1.5;">
      Or paste this link into your browser:<br>
      <a href="{verify_url}" style="color: #6366f1; word-break: break-all;">{verify_url}</a>
    </p>
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
    <p style="color: #9ca3af; font-size: 12px; margin: 0;">
      If you didn't create an account, you can safely ignore this email.
    </p>
  </div>
  <p style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 24px;">
    © 2026 DreamAgent. All rights reserved.
  </p>
</div>"""

    text_body = f"""DreamAgent - Verify Your Email

Hi {display_name},

Welcome to DreamAgent! Please verify your email address to activate your account.

Click here: {verify_url}

Or paste this link into your browser:
{verify_url}

If you didn't create an account, you can safely ignore this email.
"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Verify your email - DreamAgent"
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())

        logger.info(f"Verification email sent to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP auth failed sending to {to_email}: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send verification email to {to_email}: {e}")
        return False


def send_admin_email(to_email: str, subject: str, message: str,
                     user_name: Optional[str] = None) -> bool:
    """
    Send an admin-composed support email to a user (Admin Users grid → Mail).

    Uses the exact same SMTP relay/credentials and branded wrapper as the
    signup verification email. `message` may be plain text (blank-line
    paragraphs) or HTML from the admin rich text editor — HTML is sanitized
    to a strict allowlist (b/strong/i/em/u/s/ul/ol/li/a, http(s)/mailto
    links only) before it reaches the template.

    Returns True if sent successfully, False otherwise.
    """
    import html as _html

    display_name = user_name or to_email.split("@")[0]
    safe_subject = _html.escape(subject.strip())[:200]

    if "<" in message and ">" in message:
        content_html = _sanitize_admin_html(message)
        text_content = _html_to_text(message)
    else:
        content_html = "".join(
            f"<p style='color: #4b5563; font-size: 15px; line-height: 1.6;'>{_html.escape(p)}</p>"
            for p in message.strip().split("\n\n") if p.strip()
        )
        text_content = message.strip()

    html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
  <div style="text-align: center; margin-bottom: 32px;">
    <h1 style="font-size: 28px; font-weight: bold; margin: 0; background: linear-gradient(135deg, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">DreamAgent</h1>
    <p style="color: #6b7280; margin-top: 8px;">Your friendly VPS assistant</p>
  </div>
  <div style="background: #ffffff; border-radius: 16px; padding: 32px; border: 1px solid #e5e7eb;">
    <p style="color: #4b5563; font-size: 15px; line-height: 1.6;">Hi {display_name},</p>
    {content_html}
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
    <p style="color: #9ca3af; font-size: 12px; margin: 0;">
      This is a message from the DreamAgent team. Reply to this email to reach us.
    </p>
  </div>
  <p style="text-align: center; color: #9ca3af; font-size: 12px; margin-top: 24px;">
    © 2026 DreamAgent. All rights reserved.
  </p>
</div>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"{safe_subject} - DreamAgent"
        msg["From"] = ADMIN_EMAIL_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(ADMIN_EMAIL_FROM, to_email, msg.as_string())

        logger.info(f"Admin email sent to {to_email} (subject: {safe_subject[:60]})")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP auth failed sending admin email to {to_email}: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending admin email to {to_email}: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send admin email to {to_email}: {e}")
        return False


# ----------------------------------------------------------------------
# Admin-message HTML sanitizer (stdlib only — no extra dependency)
# ----------------------------------------------------------------------

import html as _html_mod
from html.parser import HTMLParser

_ADMIN_ALLOWED_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "s", "strike", "ul", "ol", "li", "a"}
_ADMIN_LINK_SCHEMES = ("http://", "https://", "mailto:")
_ADMIN_DROP_WITH_CONTENT = {"script", "style", "title", "head"}


class _AdminHtmlSanitizer(HTMLParser):
    """Rebuilds HTML keeping only allowlisted tags; escapes everything else.

    <script>/<style> content is dropped entirely, disallowed tags are
    unwrapped (their text survives, the tag does not), and links are
    re-emitted with only a scheme-checked href plus target=_blank
    rel="noopener noreferrer".
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list = []
        self.stack: list = []
        self.drop_depth = 0

    def handle_starttag(self, tag, attrs):
        if self.drop_depth:
            if tag in _ADMIN_DROP_WITH_CONTENT:
                self.drop_depth += 1
            return
        if tag in _ADMIN_DROP_WITH_CONTENT:
            self.drop_depth = 1
            return
        if tag not in _ADMIN_ALLOWED_TAGS:
            return  # unwrap: keep the children, drop the tag
        if tag == "br":
            self.out.append("<br/>")
            return
        if tag == "a":
            href = ""
            for key, val in attrs:
                if key == "href" and val:
                    href = val.strip()
                    break
            if href.lower().startswith(_ADMIN_LINK_SCHEMES):
                self.out.append(
                    f'<a href="{_html_mod.escape(href, quote=True)}" '
                    f'target="_blank" rel="noopener noreferrer">'
                )
                self.stack.append("a")
            return
        self.out.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if self.drop_depth:
            if tag in _ADMIN_DROP_WITH_CONTENT:
                self.drop_depth -= 1
            return
        if tag not in _ADMIN_ALLOWED_TAGS or tag == "br":
            return
        if tag in self.stack:
            # Close intermediates so emitted tags stay balanced.
            while self.stack:
                open_tag = self.stack.pop()
                self.out.append(f"</{open_tag}>")
                if open_tag == tag:
                    break

    def handle_data(self, data):
        if not self.drop_depth:
            self.out.append(_html_mod.escape(data))


def _sanitize_admin_html(raw: str) -> str:
    parser = _AdminHtmlSanitizer()
    parser.feed(raw)
    parser.close()
    while parser.stack:
        parser.out.append(f"</{parser.stack.pop()}>")
    return "".join(parser.out)


class _AdminHtmlToText(HTMLParser):
    """Crude HTML → plain-text fallback for the text/plain MIME part."""

    _BLOCKISH = {"br", "p", "li", "ul", "ol", "div"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list = []

    def handle_starttag(self, tag, attrs):
        if tag in self._BLOCKISH:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def _html_to_text(raw: str) -> str:
    parser = _AdminHtmlToText()
    parser.feed(raw)
    parser.close()
    return "".join(parser.parts).strip()
