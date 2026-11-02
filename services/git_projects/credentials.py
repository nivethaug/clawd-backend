"""Git credential management — multi-account, encrypted at rest.

Tokens are stored in the git_credentials table using SecretBox encryption
(same as global integrations). Never returned to the client; only decrypted
in-memory for the duration of a single git operation.
"""
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


def _get_secret_box():
    """Get or create the SecretBox for git credentials."""
    from secure_value import SecretBox
    return SecretBox()


class GitCredentialService:
    """Manage per-user Git provider credentials (multi-account)."""

    @staticmethod
    def connect(
        user_id: int,
        provider: str,
        account_ref: str,
        token: str,
        display_label: Optional[str] = None,
        scopes: Optional[str] = None,
    ) -> dict:
        """Save a credential (upsert by user+provider+account_ref)."""
        box = _get_secret_box()
        encrypted = box.encrypt(token)

        from database_adapter import get_db

        with get_db() as conn:
            # If this is the first credential for this provider, make it default
            existing = conn.execute(
                """SELECT COUNT(*) as n FROM git_credentials
                   WHERE user_id = %s AND provider = %s AND status = 'active'""",
                (user_id, provider),
            ).fetchone()
            is_first = int(existing["n"] if isinstance(existing, dict) else existing[0]) == 0

            conn.execute(
                """INSERT INTO git_credentials
                   (user_id, provider, account_ref, token_encrypted, display_label, scopes, is_default, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'active')
                   ON CONFLICT (user_id, provider, account_ref) DO UPDATE SET
                     token_encrypted = EXCLUDED.token_encrypted,
                     display_label = EXCLUDED.display_label,
                     scopes = EXCLUDED.scopes,
                     status = 'active'""",
                (user_id, provider, account_ref, encrypted, display_label or account_ref, scopes, is_first),
            )
            conn.commit()

        logger.info("[GIT-CRED] user %s connected %s account %s", user_id, provider, account_ref)
        return {"success": True, "provider": provider, "account_ref": account_ref}

    @staticmethod
    def disconnect(user_id: int, credential_id: int) -> bool:
        """Remove a credential (soft-delete)."""
        from database_adapter import get_db

        with get_db() as conn:
            conn.execute(
                "UPDATE git_credentials SET status = 'disconnected' WHERE id = %s AND user_id = %s",
                (credential_id, user_id),
            )
            conn.commit()
        return True

    @staticmethod
    def list_credentials(user_id: int) -> list:
        """List active credentials for a user (masked — no tokens)."""
        from database_adapter import get_db

        with get_db() as conn:
            rows = conn.execute(
                """SELECT id, provider, account_ref, display_label, is_default,
                          scopes, connected_at
                   FROM git_credentials
                   WHERE user_id = %s AND status = 'active'
                   ORDER BY provider, is_default DESC, connected_at DESC""",
                (user_id,),
            ).fetchall()

        result = []
        for row in rows:
            d = row if isinstance(row, dict) else dict(zip(
                ("id", "provider", "account_ref", "display_label", "is_default", "scopes", "connected_at"), row))
            result.append({
                "id": d["id"],
                "provider": d["provider"],
                "account_ref": d["account_ref"],
                "display_label": d.get("display_label"),
                "is_default": bool(d.get("is_default")),
                "scopes": d.get("scopes"),
                "connected_at": str(d.get("connected_at", "")),
            })
        return result

    @staticmethod
    def get_token(user_id: int, credential_id: Optional[int] = None) -> Optional[str]:
        """Decrypt and return a token (in-memory only, never logged).
        
        If credential_id is None, returns the default credential's token.
        """
        from database_adapter import get_db

        with get_db() as conn:
            if credential_id:
                row = conn.execute(
                    """SELECT token_encrypted FROM git_credentials
                       WHERE id = %s AND user_id = %s AND status = 'active'""",
                    (credential_id, user_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT token_encrypted FROM git_credentials
                       WHERE user_id = %s AND status = 'active'
                       ORDER BY is_default DESC, connected_at DESC LIMIT 1""",
                    (user_id,),
                ).fetchone()

        if not row:
            return None

        encrypted = row["token_encrypted"] if isinstance(row, dict) else row[0]
        box = _get_secret_box()
        try:
            return box.decrypt(encrypted)
        except Exception as exc:
            logger.error("[GIT-CRED] decrypt failed for user %s cred %s: %s", user_id, credential_id, exc)
            return None

    @staticmethod
    def set_default(user_id: int, credential_id: int) -> bool:
        """Set a credential as the default for its provider."""
        from database_adapter import get_db

        with get_db() as conn:
            # Get the provider of this credential
            row = conn.execute(
                "SELECT provider FROM git_credentials WHERE id = %s AND user_id = %s",
                (credential_id, user_id),
            ).fetchone()
            if not row:
                return False
            provider = row["provider"] if isinstance(row, dict) else row[0]

            # Clear existing default
            conn.execute(
                """UPDATE git_credentials SET is_default = FALSE
                   WHERE user_id = %s AND provider = %s AND is_default = TRUE""",
                (user_id, provider),
            )
            # Set new default
            conn.execute(
                "UPDATE git_credentials SET is_default = TRUE WHERE id = %s",
                (credential_id,),
            )
            conn.commit()
        return True
