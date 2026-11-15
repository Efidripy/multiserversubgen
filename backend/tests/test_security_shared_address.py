import pytest

from shared.security import validate_and_resolve_outbound_url, validate_outbound_url


@pytest.mark.parametrize("address,allowed", [
    ("100.64.0.1", False),
    ("100.127.255.254", False),
    ("100.63.255.255", True),
    ("100.128.0.1", True),
    ("::ffff:100.64.0.1", False),
    ("::ffff:100.127.255.254", False),
])
@pytest.mark.parametrize("via_dns", [False, True])
def test_shared_address_space_policy(monkeypatch, address, allowed, via_dns):
    monkeypatch.setattr(
        "shared.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, (address, 0))],
    )
    host = "example.test" if via_dns else f"[{address}]" if ":" in address else address
    assert validate_and_resolve_outbound_url(f"http://{host}/", allow_private=False, require_https=False)[0] is allowed


@pytest.mark.parametrize("address", ["100.64.0.1", "::ffff:100.64.0.1"])
def test_shared_address_space_private_override(monkeypatch, address):
    host = f"[{address}]" if ":" in address else address
    url = f"http://{host}/"
    monkeypatch.setenv("ALLOW_PRIVATE_NODE_URLS", "true")
    assert validate_outbound_url(url, require_https=False)[0] is True
    assert validate_outbound_url(url, allow_private=False, require_https=False)[0] is False
    monkeypatch.setenv("ALLOW_PRIVATE_NODE_URLS", "false")
    assert validate_outbound_url(url, allow_private=True, require_https=False)[0] is True
