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
    signup verification email. The admin's message is rendered as simple
    paragraphs; minimal HTML escaping prevents injection into the template.

    Returns True if sent successfully, False otherwise.
    """
    import html as _html

    display_name = user_name or to_email.split("@")[0]
    safe_subject = _html.escape(subject.strip())[:200]
    paragraphs = "".join(
        f"<p style='color: #4b5563; font-size: 15px; line-height: 1.6;'>{_html.escape(p)}</p>"
        for p in message.strip().split("\n\n") if p.strip()
    )

    html_body = f"""\
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 32px;">
  <div style="text-align: center; margin-bottom: 32px;">
    <h1 style="font-size: 28px; font-weight: bold; margin: 0; background: linear-gradient(135deg, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">DreamAgent</h1>
    <p style="color: #6b7280; margin-top: 8px;">Your friendly VPS assistant</p>
  </div>
  <div style="background: #ffffff; border-radius: 16px; padding: 32px; border: 1px solid #e5e7eb;">
    <p style="color: #4b5563; font-size: 15px; line-height: 1.6;">Hi {display_name},</p>
    {paragraphs}
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
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        msg.attach(MIMEText(message.strip(), "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            if SMTP_PASS:
                server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())

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
