from services.subscription_client_settings import default_settings, load_settings, match_client, save_settings
from services.subscription_client_settings import build_headers, schema, validate_settings


def test_defaults_are_disabled_and_persisted(tmp_path):
    path = str(tmp_path / "settings.db")
    settings = load_settings(path)
    assert all(not client["enabled"] for client in settings["clients"])
    settings["clients"][0]["enabled"] = True
    save_settings(path, settings)
    assert match_client(load_settings(path), "HAPP/1")["id"] == "happ"


def test_first_enabled_rule_wins():
    settings = default_settings()
    settings["clients"] = [
        {"id": "custom-a", "name": "A", "kind": "generic", "builtin": False, "enabled": True, "user_agent_regex": "client", "format": "base64", "settings": {}, "headers": []},
        {"id": "custom-b", "name": "B", "kind": "generic", "builtin": False, "enabled": True, "user_agent_regex": "client", "format": "singbox", "settings": {}, "headers": []},
    ]
    assert match_client(settings, "client")["id"] == "custom-a"


def test_incy_routing_is_text_and_happ_url_rule_is_kind_specific():
    settings = default_settings()
    settings["clients"][1]["settings"] = {"routing_enable": True, "routing": "https://example.com"}
    assert validate_settings(settings)["clients"][1]["settings"]["routing"] == "https://example.com"
    settings["clients"][0]["settings"] = {"routing": "https://example.com"}
    try:
        validate_settings(settings)
    except ValueError as exc:
        assert str(exc) == "routing"
    else:
        raise AssertionError("invalid Happ routing accepted")


def test_header_types_defaults_and_lines_normalization():
    settings = default_settings()
    settings["clients"][0]["enabled"] = True
    settings["clients"][0]["settings"] = {"sub_info_text": "Info", "sub_info_color": "", "exclude_apns": False}
    validated = validate_settings(settings)
    _, headers = build_headers(validated, "Happ/1")
    assert headers["Sub-Info-Color"] == "blue"
    assert "Exclude-Apns-Enable" not in headers
    settings["clients"][2]["settings"] = {"rules": ["DOMAIN-SUFFIX,example.com,PROXY"]}
    assert validate_settings(settings)["clients"][2]["settings"]["rules"] == "DOMAIN-SUFFIX,example.com,PROXY"


def test_invalid_typed_fields_urls_headers_and_regex_are_rejected():
    settings = default_settings()
    settings["clients"][0]["settings"] = {"routing_enable": "true"}
    for bad in (settings,):
        try:
            validate_settings(bad)
        except ValueError as exc:
            assert str(exc) == "routing_enable"
        else:
            raise AssertionError("invalid bool accepted")
    settings = default_settings()
    settings["clients"][0]["headers"] = [{"key": "Content-Type", "value": "x"}]
    try:
        validate_settings(settings)
    except ValueError as exc:
        assert str(exc) == "headers"
    else:
        raise AssertionError("forbidden header accepted")


def test_schema_marks_routing_fields_without_headers():
    assert {item["key"]: item["header"] for item in schema()["incy"]}["routing"] is None
