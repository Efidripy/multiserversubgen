"""Unit tests for backend/utils.py"""
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import parse_field_as_dict


class TestParseFieldAsDict:
    def test_none_returns_empty_dict(self):
        assert parse_field_as_dict(None) == {}

    def test_dict_returned_as_is(self):
        d = {"security": "reality", "network": "tcp"}
        assert parse_field_as_dict(d) is d

    def test_valid_json_string_returns_dict(self):
        s = '{"security": "reality", "network": "tcp"}'
        assert parse_field_as_dict(s) == {"security": "reality", "network": "tcp"}

    def test_pretty_json_string_returns_dict(self):
        s = json.dumps({"clients": [{"id": "abc", "email": "test@example.com"}]}, indent=2)
        result = parse_field_as_dict(s)
        assert result == {"clients": [{"id": "abc", "email": "test@example.com"}]}

    def test_empty_json_string_returns_empty_dict(self):
        assert parse_field_as_dict("{}") == {}

    def test_invalid_json_string_returns_empty_dict(self):
        assert parse_field_as_dict("not valid json") == {}

    def test_json_array_string_returns_empty_dict(self):
        # JSON arrays are not dicts — should return {}
        assert parse_field_as_dict("[1, 2, 3]") == {}

    def test_integer_returns_empty_dict(self):
        assert parse_field_as_dict(42) == {}

    def test_list_returns_empty_dict(self):
        assert parse_field_as_dict([1, 2, 3]) == {}

    def test_node_id_and_field_name_do_not_raise(self):
        result = parse_field_as_dict(
            "bad json", node_id="my-node", field_name="streamSettings"
        )
        assert result == {}

    def test_security_extracted_from_string(self):
        """Regression: streamSettings as JSON string must not raise AttributeError."""
        raw = json.dumps({"security": "reality", "network": "tcp"})
        parsed = parse_field_as_dict(raw, node_id="node1", field_name="streamSettings")
        assert parsed.get("security") == "reality"

    def test_clients_extracted_from_settings_string(self):
        """Regression: settings as JSON string must expose clients list."""
        raw = json.dumps({"clients": [{"email": "user@example.com", "id": "uuid"}]})
        parsed = parse_field_as_dict(raw, node_id="node1", field_name="settings")
        assert parsed.get("clients")[0]["email"] == "user@example.com"
