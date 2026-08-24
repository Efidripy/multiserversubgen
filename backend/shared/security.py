"""Small, reusable security guards for outbound integrations and secrets."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from collections.abc import Mapping
from urllib.parse import urlparse


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}

MAX_LOG_COUNT = 500
MAX_BACKUP_BYTES = 8 * 1024 * 1024
MAX_BACKUP_B64_CHARS = MAX_BACKUP_BYTES * 2
MAX_REQUEST_ID_LENGTH = 96
_SQLITE_DATABASE_SIGNATURE = b"SQLite format 3\x00"
_SQLITE_DUMP_PREFIXES = (b"PRAGMA", b"BEGIN TRANSACTION")
_SAFE_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")


def _is_forbidden_address(address: ipaddress._BaseAddress, *, allow_private: bool) -> bool:
    return bool(
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or (address.is_private and not allow_private)
    )


def _resolve_host_addresses(host: str, *, allow_private: bool) -> tuple[tuple[str, ...], str]:
    """Resolve a hostname, returning only addresses that passed the egress policy."""
    try:
        resolved = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return (), "Destination hostname could not be resolved"
    if not resolved:
        return (), "Destination hostname has no addresses"
    addresses: list[str] = []
    for item in resolved:
        try:
            address_text = item[4][0]
            address = ipaddress.ip_address(address_text)
        except (ValueError, IndexError):
            return (), "Destination hostname resolved to an invalid address"
        if _is_forbidden_address(address, allow_private=allow_private):
            return (), "Destination resolves to a private or otherwise unsafe address"
        if address_text not in addresses:
            addresses.append(address_text)
    return tuple(addresses), ""


def validate_outbound_url(
    value: str,
    *,
    allow_private: bool | None = None,
    require_https: bool | None = None,
    resolve_dns: bool = True,
) -> tuple[bool, str]:
    """Validate an outbound URL before credentials are used."""
    valid, error, _ = validate_and_resolve_outbound_url(
        value,
        allow_private=allow_private,
        require_https=require_https,
        resolve_dns=resolve_dns,
    )
    return valid, error


def validate_and_resolve_outbound_url(
    value: str,
    *,
    allow_private: bool | None = None,
    require_https: bool | None = None,
    resolve_dns: bool = True,
) -> tuple[bool, str, str | None]:
    """Validate a URL and return the approved address used for its connection."""
    raw = str(value or "").strip()
    if not raw:
        return False, "URL is required", None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http:// and https:// URLs are supported", None
    if parsed.username or parsed.password:
        return False, "Credentials in URL are not allowed", None
    if not parsed.hostname:
        return False, "URL hostname is required", None
    if require_https is None:
        require_https = os.getenv("REQUIRE_HTTPS_OUTBOUND", "true").lower() not in {"0", "false", "no"}
    if require_https and parsed.scheme != "https":
        return False, "HTTPS is required for credentialed outbound requests", None
    if allow_private is None:
        allow_private = os.getenv("ALLOW_PRIVATE_NODE_URLS", "false").lower() in {"1", "true", "yes", "on"}
    host = parsed.hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES:
        return False, "Local and metadata destinations are not allowed", None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
            return False, "Loopback, link-local, multicast and unspecified destinations are not allowed", None
        if _is_forbidden_address(address, allow_private=allow_private):
            return False, "Private or otherwise unsafe destinations are not allowed", None
        return True, "", host
    elif resolve_dns:
        addresses, resolved_error = _resolve_host_addresses(host, allow_private=allow_private)
        if not addresses:
            return False, resolved_error, None
        return True, "", addresses[0]
    return True, "", None


def redact_url(value: str) -> str:
    """Return a log-safe URL without userinfo, query or fragment material."""
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.hostname:
        return "<invalid-url>"
    port = ":" + str(parsed.port) if parsed.port else ""
    path = parsed.path.rstrip("/")
    return parsed.scheme + "://" + parsed.hostname + port + path


def bounded_log_count(value: object, default: int = 100) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(count, MAX_LOG_COUNT))


def validate_path_segment(value: object, *, field: str = "value") -> str:
    candidate = str(value or "").strip()
    if not _SAFE_PATH_SEGMENT.fullmatch(candidate) or candidate in {".", ".."}:
        raise ValueError(f"Invalid {field}")
    return candidate


def safe_request_id(value: object) -> str:
    candidate = str(value or "").strip()
    return candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else ""


def is_supported_sqlite_backup(content: object) -> bool:
    """Match the current 3x-ui SQLite restore-file type discriminator.

    A full database integrity check belongs to the remote panel before it
    replaces its database.  The control plane must still reject arbitrary
    uploads before forwarding them to that destructive remote endpoint.
    """
    if not isinstance(content, (bytes, bytearray)):
        return False
    header = bytes(content[:64])
    if header.startswith(_SQLITE_DATABASE_SIGNATURE):
        return True
    if header.startswith(b"\xef\xbb\xbf"):
        header = header[3:]
    header = header.lstrip(b" \t\r\n")
    return header.startswith(_SQLITE_DUMP_PREFIXES)


def safe_content_disposition_filename(value: object, fallback: str = "download.bin") -> str:
    candidate = str(value or "").replace("\r", "").replace("\n", "")
    candidate = re.sub(r"[^A-Za-z0-9._-]", "_", candidate).strip("._")
    if not candidate:
        candidate = fallback
    return f"attachment; filename=\"{candidate[:128]}\""


def redact_mapping(value: object) -> object:
    """Redact credential-bearing mapping values before logging."""
    sensitive = {"authorization", "cookie", "set-cookie", "password", "token", "secret", "api_key"}
    if isinstance(value, Mapping):
        return {str(key): ("<redacted>" if str(key).lower() in sensitive else redact_mapping(item)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item) for item in value]
    return value
