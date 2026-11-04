from __future__ import annotations
import base64
import pytest
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from services.subscription_happ_crypto import _encrypt_happ_link, _swap_pairs, encrypt_happ_link


def decode_frame(link, private_key):
    raw = bytearray(link[len("happ://crypt5/") :].encode("ascii"))
    for i in range(0, len(raw) - 3, 4):
        raw[i : i + 4] = bytes((raw[i + 2], raw[i + 3], raw[i], raw[i + 1]))
    frame = bytes(raw).decode("ascii")
    assert frame.startswith("vdfz") and frame.endswith("foff")
    body = frame[4:-4]
    nonce, tag, salt = body[:12], body[12:14], body[14:22]
    pos = 22
    while body[pos].isdigit():
        pos += 1
    size = int(body[22:pos])
    assert body[pos] == "V"
    cipher_b64 = body[pos + 1 : pos + 1 + size]
    wrapped = base64.b64decode(
        _swap_pairs(
            private_key.decrypt(
                base64.b64decode(body[pos + 1 + size :]), padding.PKCS1v15()
            )
        )
    )
    key = bytes(v ^ salt.encode()[i % 8] for i, v in enumerate(wrapped))
    plain = ChaCha20Poly1305(key).decrypt(
        nonce.encode(), base64.b64decode(cipher_b64), None
    )
    return base64.b64decode(_swap_pairs(plain)).decode(), tag


def test_round_trip_protocol():
    private = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    source = "https://example.com/sub?q=тест"
    assert (
        decode_frame(_encrypt_happ_link(source, private.public_key()), private)[0]
        == source
    )


@pytest.mark.parametrize(
    "source",
    [
        "ftp://example.com",
        "https://user:p@example.com",
        "https://example.com/\n",
        "https://",
    ],
)
def test_rejects_invalid_source(source):
    with pytest.raises(ValueError):
        _encrypt_happ_link(
            source,
            rsa.generate_private_key(public_exponent=65537, key_size=4096).public_key(),
        )


def test_rejects_oversized_source():
    with pytest.raises(ValueError):
        _encrypt_happ_link(
            "https://example.com/" + "a" * 8192,
            rsa.generate_private_key(public_exponent=65537, key_size=4096).public_key(),
        )


def test_real_client_key_produces_link():
    link = encrypt_happ_link("https://example.com/sub")
    assert link.startswith("happ://crypt5/")
    assert link != encrypt_happ_link("https://example.com/sub")
