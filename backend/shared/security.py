"""Small, reusable security guards for outbound integrations and secrets."""

from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse


_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata",
}


def validate_outbound_url(value: str, *, allow_private: bool | None = None, require_https: bool | None = None) -> tuple[bool, str]:
    """Validate an outbound URL before credentials are used."""
    raw = str(value or "").strip()
    if not raw:
        return False, "URL is required"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http:// and https:// URLs are supported"
    if parsed.username or parsed.password:
        return False, "Credentials in URL are not allowed"
    if not parsed.hostname:
        return False, "URL hostname is required"
    if require_https is None:
        require_https = os.getenv("REQUIRE_HTTPS_OUTBOUND", "true").lower() not in {"0", "false", "no"}
    if require_https and parsed.scheme != "https":
        return False, "HTTPS is required for credentialed outbound requests"
    if allow_private is None:
        allow_private = os.getenv("ALLOW_PRIVATE_NODE_URLS", "false").lower() in {"1", "true", "yes", "on"}
    host = parsed.hostname.rstrip(".").lower()
    if host in _BLOCKED_HOSTNAMES:
        return False, "Local and metadata destinations are not allowed"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
            return False, "Loopback, link-local, multicast and unspecified destinations are not allowed"
        if address.is_private and not allow_private:
            return False, "Private destinations require ALLOW_PRIVATE_NODE_URLS=true"
        if address.is_reserved:
            return False, "Reserved destinations are not allowed"
    return True, ""


def redact_url(value: str) -> str:
    """Return a log-safe URL without userinfo, query or fragment material."""
    parsed = urlparse(str(value or ""))
    if not parsed.scheme or not parsed.hostname:
        return "<invalid-url>"
    port = ":" + str(parsed.port) if parsed.port else ""
    path = parsed.path.rstrip("/")
    return parsed.scheme + "://" + parsed.hostname + port + path
