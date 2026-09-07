"""Encrypted, write-only Bot API token configuration for the admin panel."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from services.db_bootstrap import connect


_BOT_TOKEN = re.compile(r"^[0-9]{6,20}:[A-Za-z0-9_-]{20,128}$")


class TelegramBotConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramBotConfigurationStatus:
    configured: bool
    token_suffix: str | None
    row_version: int
    updated_by: str
    updated_at: str
    source: str


class TelegramBotTokenProvider:
    """Resolve an encrypted local override without ever returning it to HTTP."""

    def __init__(self, *, db_path: str, encrypt: Callable[[str], str], decrypt: Callable[[str], str], fallback_token: str = ""):
        self._db_path = db_path
        self._encrypt = encrypt
        self._decrypt = decrypt
        self._fallback_token = fallback_token.strip()

    @staticmethod
    def validate_token(value: object) -> str:
        if not isinstance(value, str):
            raise TelegramBotConfigurationError("Bot API token must be text")
        token = value.strip()
        if not _BOT_TOKEN.fullmatch(token):
            raise TelegramBotConfigurationError("Bot API token format is invalid")
        return token

    def status(self) -> TelegramBotConfigurationStatus:
        with connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT encrypted_bot_token, token_suffix, row_version, updated_by, updated_at "
                "FROM telegram_bot_configuration WHERE singleton_id = 1"
            ).fetchone()
        encrypted = str(row[0]) if row and row[0] else ""
        if encrypted:
            return TelegramBotConfigurationStatus(
                configured=True, token_suffix=str(row[1]) if row[1] else None, row_version=int(row[2]),
                updated_by=str(row[3]), updated_at=str(row[4]), source="panel",
            )
        return TelegramBotConfigurationStatus(
            configured=bool(self._fallback_token),
            token_suffix=(self._fallback_token[-4:] if self._fallback_token else None),
            row_version=int(row[2]) if row else 1, updated_by=str(row[3]) if row else "system",
            updated_at=str(row[4]) if row else "", source="environment" if self._fallback_token else "none",
        )

    def get_token(self) -> str:
        with connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT encrypted_bot_token FROM telegram_bot_configuration WHERE singleton_id = 1"
            ).fetchone()
        encrypted = str(row[0]) if row and row[0] else ""
        if encrypted:
            try:
                return self.validate_token(self._decrypt(encrypted))
            except Exception as exc:
                raise TelegramBotConfigurationError("stored Bot API token cannot be decrypted") from exc
        if self._fallback_token:
            return self.validate_token(self._fallback_token)
        raise TelegramBotConfigurationError("Bot API token is not configured")

    def set_token(self, *, token: object, expected_row_version: object, updated_by: str) -> TelegramBotConfigurationStatus:
        plain = self.validate_token(token)
        if isinstance(expected_row_version, bool):
            raise TelegramBotConfigurationError("token configuration version is invalid")
        try:
            version = int(expected_row_version)
        except (TypeError, ValueError) as exc:
            raise TelegramBotConfigurationError("token configuration version is invalid") from exc
        if version < 1:
            raise TelegramBotConfigurationError("token configuration version is invalid")
        actor = str(updated_by).strip()
        if not actor:
            raise TelegramBotConfigurationError("token configuration actor is required")
        encrypted = self._encrypt(plain)
        with connect(self._db_path) as conn:
            updated = conn.execute(
                """
                UPDATE telegram_bot_configuration
                SET encrypted_bot_token = ?, token_suffix = ?, row_version = row_version + 1,
                    updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE singleton_id = 1 AND row_version = ?
                """,
                (encrypted, plain[-4:], actor, version),
            )
            if updated.rowcount != 1:
                raise TelegramBotConfigurationError("Bot API token configuration changed concurrently")
        return self.status()

    def clear_token(self, *, expected_row_version: object, updated_by: str) -> TelegramBotConfigurationStatus:
        if isinstance(expected_row_version, bool):
            raise TelegramBotConfigurationError("token configuration version is invalid")
        try:
            version = int(expected_row_version)
        except (TypeError, ValueError) as exc:
            raise TelegramBotConfigurationError("token configuration version is invalid") from exc
        actor = str(updated_by).strip()
        with connect(self._db_path) as conn:
            updated = conn.execute(
                """
                UPDATE telegram_bot_configuration
                SET encrypted_bot_token = NULL, token_suffix = NULL, row_version = row_version + 1,
                    updated_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE singleton_id = 1 AND row_version = ?
                """,
                (actor, version),
            )
            if updated.rowcount != 1:
                raise TelegramBotConfigurationError("Bot API token configuration changed concurrently")
        return self.status()
