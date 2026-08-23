from services.system_clients import (
    annotate_system_clients,
    has_system_comment,
    system_client_emails_from_inbounds,
)
from services.snapshot_push import flatten_snapshot_tables


def test_system_marker_matches_a_standalone_comment_token_only():
    assert has_system_comment("SYSTEM") is True
    assert has_system_comment("managed by system") is True
    assert has_system_comment("ecosystem") is False
    assert has_system_comment(None) is False


def test_system_client_annotation_and_inbound_email_lookup_are_case_insensitive():
    clients = annotate_system_clients([
        {"email": "service@example.test", "comment": "System account"},
        {"email": "customer@example.test", "comment": "personal"},
    ])
    assert [client["is_system"] for client in clients] == [True, False]

    emails = system_client_emails_from_inbounds([
        {
            "settings": {
                "clients": [
                    {"email": " Service@Example.test ", "comment": "SYSTEM"},
                    {"email": "customer@example.test", "comment": "personal"},
                ]
            }
        }
    ])
    assert emails == {"service@example.test"}


def test_v3_client_mapping_preserves_comment_for_system_classification():
    from client_manager import ClientManager

    mapped = ClientManager(decrypt_func=lambda value: value)._map_v3_client(
        {"uuid": "client-id", "email": "service@example.test", "comment": "SYSTEM"},
        {"id": 5, "name": "cholera"},
    )

    assert mapped["comment"] == "SYSTEM"


def test_collector_snapshot_rows_preserve_comment_and_system_marker():
    tables = flatten_snapshot_tables({
        "name": "cholera",
        "node_id": 5,
        "inbounds": [{
            "id": 12,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": "client-id", "email": "service@example.test", "comment": "SYSTEM"}]
            },
            "clientStats": [{"email": "service@example.test", "up": 10, "down": 20}],
        }],
    })

    assert tables["clients"] == [
        {
            "id": "client-id",
            "email": "service@example.test",
            "enable": True,
            "expiryTime": 0,
            "total": 0,
            "totalGB": 0,
            "up": 10,
            "down": 20,
            "flow": "",
            "comment": "SYSTEM",
            "is_system": True,
            "node_id": 5,
            "node_name": "cholera",
            "node_ip": "cholera",
            "inbound_id": 12,
            "inbound_remark": "",
            "protocol": "vless",
            "password": "",
            "security": "",
            "network": "",
        }
    ]
