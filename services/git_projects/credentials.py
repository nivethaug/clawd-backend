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


class GitCredentialService:
    """Manage per-user Git provider credentials (multi-account)."""

    @staticmethod
    def _encrypt(token: str) -> str:
        from secure_value import encrypt_value
        return encrypt_value(token)

    @staticmethod
    def _decrypt(encrypted: str) -> str:
        from secure_value import decrypt_value
        return decrypt_value(encrypted)

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
        encrypted = GitCredentialService._encrypt(token)

        from database_adapter import get_db

        with get_db() as conn:
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
        from database_adapter import get_db
        with get_db() as conn:
            result = conn.execute(
                "UPDATE git_credentials SET status = 'disconnected' WHERE id = %s AND user_id = %s RETURNING id",
                (credential_id, user_id),
            ).fetchone()
            conn.commit()
        return bool(result)

    @staticmethod
    def list_credentials(user_id: int) -> list:
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
        try:
            return GitCredentialService._decrypt(encrypted)
        except Exception as exc:
            logger.error("[GIT-CRED] decrypt failed for user %s: %s", user_id, exc)
            return None

    @staticmethod
    def set_default(user_id: int, credential_id: int) -> bool:
        from database_adapter import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT provider FROM git_credentials WHERE id = %s AND user_id = %s",
                (credential_id, user_id),
            ).fetchone()
            if not row:
                return False
            provider = row["provider"] if isinstance(row, dict) else row[0]
            conn.execute(
                "UPDATE git_credentials SET is_default = FALSE WHERE user_id = %s AND provider = %s AND is_default = TRUE",
                (user_id, provider),
            )
            conn.execute(
                "UPDATE git_credentials SET is_default = TRUE WHERE id = %s",
                (credential_id,),
            )
            conn.commit()
        return True
