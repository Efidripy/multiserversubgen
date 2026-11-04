"""Happ crypt5 link encryption."""
from __future__ import annotations

import base64
import hashlib

import secrets
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

_PUBLIC_KEY_PEM = b'-----BEGIN PUBLIC KEY-----\r\nMIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA9+umWSxp8coKnMONnI4u\r\nNvtPErJZt8VNgNb2XS+RrCMc9AFWZQH01ILr3Py/mviuqFgNLMEcPs3k6+ZPh6Sa\r\nOCXHmjQicGPJAw6Co6GQwO/b4vspHgOM4HSvX5r6SY1EKIHUSLIyRV28DfwJKdFv\r\nx2EKqypewlrAo4AV76uI/9U+1t40yHcVCj/OtFxsq+mMM6qySieTsA1q6C5raBrJ\r\nu3l/RWMxFYvDInYDs1IaTFGDFwSdFDqhNU19gPGloT/GApy+U32R6AGSxJymS2nh\r\ne6pm/M9bvsH0o0Oc1kyXsBpVN04n/a9gVVUoqODzrUyXDx7/jAzNJD43PWtblcz0\r\nZNBKN50wvpSD5UuAQydwMT7xWJIpPaZqTUj/sg8hIm57XGlUxRCge17nB0Ff7sKO\r\nJAgaXVdbfqDdzx+PhSaZY9xfcAh/sHfE6hKaCQ9kIn5cjbx9bcYqZWnpuSOzSFg+\r\nCgMSqvG6rV6d+96dNMHuE0tRIUJ83xrLcm9hZJmJ6WDm6hteZbnb1k3eQF9c+XCF\r\nwSEvsWiXyduQmkVNJaCRXwy8tSaZp9JftALhRHMvd7Eq6ctAkvn7w0upynsAtLeL\r\nN8xZ5q1gcRgboydr588D3m8KF7mVuX/XRp2AG7hzyYdkQov9bfEfXIaBVlwHMKhy\r\nuPTxeM4Les6fvaHMSWJ+8EUCAwEAAQ==\r\n-----END PUBLIC KEY-----\r\n'
_PUBLIC_KEY_SHA256 = "22319c7b13647897bf5fd4f827ba92bf3946d738007a0054ccd931c31f221768"
_ALPHANUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _load_public_key(key_data=None):
    data = _PUBLIC_KEY_PEM if key_data is None else key_data
    key = data if hasattr(data, "encrypt") else serialization.load_pem_public_key(data)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 4096 or key.public_numbers().e != 65537:
        raise ValueError("public_key")
    if key_data is None:
        der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        if hashlib.sha256(der).hexdigest() != _PUBLIC_KEY_SHA256:
            raise ValueError("public_key")
    return key


_DEFAULT_PUBLIC_KEY = _load_public_key()


def _swap_pairs(data: bytes) -> bytes:
    out = bytearray(data)
    for i in range(0, len(out) - 1, 2):
        out[i], out[i + 1] = out[i + 1], out[i]
    return bytes(out)


def _shuffle_frame(data: bytes) -> bytes:
    out = bytearray(data)
    for i in range(0, len(out) - 3, 4):
        out[i:i + 4] = bytes((data[i + 2], data[i + 3], data[i], data[i + 1]))
    return bytes(out)


def _validate_source(source_url: str) -> bytes:
    if not isinstance(source_url, str):
        raise ValueError("source_url")
    try:
        raw = source_url.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("source_url") from exc
    if not raw or len(raw) > 8192 or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in source_url):
        raise ValueError("source_url")
    try:
        parts = urlsplit(source_url)
        if parts.scheme not in ("http", "https") or not parts.netloc or not parts.hostname:
            raise ValueError
        if parts.username is not None or parts.password is not None:
            raise ValueError
        _ = parts.port
    except (ValueError, UnicodeError) as exc:
        raise ValueError("source_url") from exc
    return raw


def _encrypt_with_key(source_url: str, public_key=None) -> str:
    source = _validate_source(source_url)
    key = _DEFAULT_PUBLIC_KEY if public_key is None else _load_public_key(public_key)
    session_key = secrets.token_bytes(32)
    nonce = "".join(secrets.choice(_ALPHANUM) for _ in range(12))
    tag = "".join(secrets.choice(_ALPHA) for _ in range(2))
    salt = "".join(secrets.choice(_ALPHANUM) for _ in range(8))
    salt_bytes = salt.encode("ascii")
    wrapped = bytes(v ^ salt_bytes[i % 8] for i, v in enumerate(session_key))
    rsa_plain = _swap_pairs(base64.b64encode(wrapped))
    rsa_cipher = key.encrypt(rsa_plain, padding.PKCS1v15())
    plain = _swap_pairs(base64.b64encode(source))
    cipher = ChaCha20Poly1305(session_key).encrypt(nonce.encode("ascii"), plain, None)
    cipher_b64 = base64.b64encode(cipher).decode("ascii")
    body = nonce + tag + salt + str(len(cipher_b64)) + "V" + cipher_b64 + base64.b64encode(rsa_cipher).decode("ascii")
    frame = _shuffle_frame(("vdfz" + body + "foff").encode("ascii"))
    return "happ://crypt5/" + frame.decode("ascii")


def encrypt_happ_link(source_url: str) -> str:
    """Encrypt an absolute subscription URL into a Happ crypt5 link."""
    try:
        return _encrypt_with_key(source_url)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("source_url") from exc


def _encrypt_happ_link(source_url: str, public_key=None) -> str:
    return _encrypt_with_key(source_url, public_key)
