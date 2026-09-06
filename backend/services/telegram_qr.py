"""Local-only QR encoding for a user's opaque subscription URL."""

from __future__ import annotations

import struct
import zlib

import qrcode


class TelegramQrError(ValueError):
    """The input cannot safely be represented as the compact QR payload."""


def _png_chunk(kind: bytes, value: bytes) -> bytes:
    return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xFFFFFFFF)


def _matrix_to_png(matrix: list[list[bool]], *, scale: int) -> bytes:
    """Encode a monochrome QR matrix as a dependency-free PNG."""

    side = len(matrix)
    if side <= 0 or any(len(row) != side for row in matrix):
        raise TelegramQrError("subscription QR matrix is invalid")
    width = side * scale
    if width > 4096:
        raise TelegramQrError("subscription QR image is too large")
    scanlines = bytearray()
    for row in matrix:
        pixels = b"".join((b"\x00" if value else b"\xff") * scale for value in row)
        for _ in range(scale):
            scanlines.extend(b"\x00")
            scanlines.extend(pixels)
    return b"".join((
        b"\x89PNG\r\n\x1a\n",
        _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, width, 8, 0, 0, 0, 0)),
        _png_chunk(b"IDAT", zlib.compress(bytes(scanlines), level=9)),
        _png_chunk(b"IEND", b""),
    ))


def build_subscription_qr_png(subscription_url: str) -> bytes:
    """Return a PNG without sending the URL to any third-party service."""

    value = str(subscription_url or "").strip()
    if not value.startswith("https://") or len(value) > 2048:
        raise TelegramQrError("subscription URL is not suitable for QR encoding")
    try:
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2,
        )
        qr.add_data(value)
        qr.make(fit=True)
        png = _matrix_to_png(qr.get_matrix(), scale=8)
    except Exception as exc:  # qrcode exposes several implementation exceptions.
        raise TelegramQrError("subscription QR generation failed") from exc
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 1_000_000:
        raise TelegramQrError("subscription QR payload is invalid")
    return png
