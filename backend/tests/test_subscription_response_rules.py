from __future__ import annotations

import json
from typing import Any
import pytest

from services.subscription_response_rules import (
    ALLOWED_OPS,
    ALLOWED_RESPONSES,
    evaluate,
    parse_rules,
    validate_response_rules,
)


def _make_rule(
    name: str = "test-rule",
    enabled: bool = True,
    match: str = "all",
    conditions: list[dict[str, Any]] | None = None,
    response: str = "base64",
    modifications: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "enabled": enabled,
        "match": match,
        "conditions": conditions if conditions is not None else [],
        "response": response,
        "modifications": modifications if modifications is not None else {},
    }


def test_parse_rules_empty_and_whitespace():
    assert parse_rules("") == []
    assert parse_rules("   \n\t  ") == []
    assert parse_rules("[]") == []
    validate_response_rules("")
    validate_response_rules("   ")
    validate_response_rules("[]")


def test_parse_rules_valid_complete():
    raw = [
        {
            "name": "clash-rule",
            "enabled": True,
            "match": "all",
            "conditions": [
                {
                    "header": "user-agent",
                    "op": "contains",
                    "value": "clash",
                    "case_sensitive": False,
                }
            ],
            "response": "clash",
            "modifications": {
                "headers": [{"key": "X-Custom", "value": "val"}],
                "exclude_nodes": ["node1", "node2"],
                "remark_template": "{{NODE}} - VIP",
                "skip_device_limit": True,
            },
        }
    ]
    parsed = parse_rules(json.dumps(raw))
    assert len(parsed) == 1
    assert parsed[0]["name"] == "clash-rule"
    assert parsed[0]["enabled"] is True
    assert parsed[0]["match"] == "all"
    assert len(parsed[0]["conditions"]) == 1
    assert parsed[0]["conditions"][0]["header"] == "user-agent"
    assert parsed[0]["response"] == "clash"
    assert parsed[0]["modifications"]["headers"] == [{"key": "X-Custom", "value": "val"}]
    assert parsed[0]["modifications"]["exclude_nodes"] == ["node1", "node2"]
    assert parsed[0]["modifications"]["remark_template"] == "{{NODE}} - VIP"
    assert parsed[0]["modifications"]["skip_device_limit"] is True


def test_parse_rules_minimal_fields_default_applied():
    raw = [{"name": "simple", "response": "singbox"}]
    parsed = parse_rules(json.dumps(raw))
    assert len(parsed) == 1
    rule = parsed[0]
    assert rule["name"] == "simple"
    assert rule["enabled"] is True
    assert rule["match"] == "all"
    assert rule["conditions"] == []
    assert rule["response"] == "singbox"
    assert rule["modifications"] == {
        "headers": [],
        "exclude_nodes": [],
        "remark_template": "",
        "skip_device_limit": False,
    }


def test_parse_rules_all_allowed_responses():
    for resp in ALLOWED_RESPONSES:
        raw = [_make_rule(response=resp)]
        parsed = parse_rules(json.dumps(raw))
        assert parsed[0]["response"] == resp


def test_parse_rules_all_allowed_ops():
    for op in ALLOWED_OPS:
        val = "test" if op not in ("regex", "not_regex") else r"^test\d+$"
        cond = {"header": "user-agent", "op": op, "value": val}
        raw = [_make_rule(conditions=[cond])]
        parsed = parse_rules(json.dumps(raw))
        assert parsed[0]["conditions"][0]["op"] == op


def test_parse_rules_rejects_non_string():
    for bad in (None, 123, [], {}):
        with pytest.raises(ValueError) as exc:
            parse_rules(bad)  # type: ignore[arg-type]
        assert str(exc.value) == "rules"


def test_parse_rules_rejects_invalid_json():
    with pytest.raises(ValueError):
        parse_rules("{invalid json")


def test_parse_rules_rejects_non_list_root():
    for bad in ("{}", "123", "true", "null", '"string"'):
        with pytest.raises(ValueError) as exc:
            parse_rules(bad)
        assert str(exc.value) == "rules"


def test_parse_rules_max_rules_limit():
    valid = [_make_rule(name=f"r{i}") for i in range(64)]
    assert len(parse_rules(json.dumps(valid))) == 64

    invalid = [_make_rule(name=f"r{i}") for i in range(65)]
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps(invalid))
    assert str(exc.value) == "rules"


def test_parse_rules_rejects_non_dict_rule():
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps(["not-a-dict"]))
    assert str(exc.value) == "rules"


def test_parse_rules_rejects_bad_name():
    for bad in ({"response": "base64"}, {"name": "", "response": "base64"}, {"name": 123, "response": "base64"}, {"name": "a" * 129, "response": "base64"}):
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([bad]))
        assert str(exc.value) == "name"


def test_parse_rules_rejects_bad_enabled():
    for bad in ("true", 1, None, []):
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([_make_rule(enabled=bad)]))  # type: ignore[arg-type]
        assert str(exc.value) == "enabled"


def test_parse_rules_rejects_bad_match():
    for bad in ("both", "none", "", 123):
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([_make_rule(match=bad)]))  # type: ignore[arg-type]
        assert str(exc.value) == "match"


def test_parse_rules_rejects_bad_response():
    for bad in ("unknown", "", "json", 123, None):
        rule = _make_rule()
        rule["response"] = bad
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([rule]))
        assert str(exc.value) == "response"


def test_parse_rules_conditions_limits():
    valid_conds = [{"header": "user-agent", "op": "equals", "value": f"val{i}"} for i in range(16)]
    assert len(parse_rules(json.dumps([_make_rule(conditions=valid_conds)]))[0]["conditions"]) == 16

    invalid_conds = [{"header": "user-agent", "op": "equals", "value": f"val{i}"} for i in range(17)]
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(conditions=invalid_conds)]))
    assert str(exc.value) == "conditions"

    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(conditions="not-a-list")]))  # type: ignore[arg-type]
    assert str(exc.value) == "conditions"

    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(conditions=["not-a-dict"])]))
    assert str(exc.value) == "conditions"


def test_parse_rules_rejects_bad_condition_header():
    # Forbidden headers
    for forbidden in ("content-type", "Content-Type", "Set-Cookie", "subscription-userinfo", "strict-transport-security"):
        cond = {"header": forbidden, "op": "equals", "value": "x"}
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([_make_rule(conditions=[cond])]))
        assert str(exc.value) == "header"

    # Malformed headers
    for bad in ("", "Header With Space", "Header:Colon", "Header@At", 123, None, "a" * 129):
        cond = {"header": bad, "op": "equals", "value": "x"}
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([_make_rule(conditions=[cond])]))
        assert str(exc.value) == "header"


def test_parse_rules_rejects_bad_condition_op():
    for bad_op in ("like", "in", "matches", "", 123, None):
        cond = {"header": "user-agent", "op": bad_op, "value": "x"}
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([_make_rule(conditions=[cond])]))
        assert str(exc.value) == "op"


def test_parse_rules_rejects_bad_condition_value():
    # Missing value for equals
    cond = {"header": "user-agent", "op": "equals"}
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(conditions=[cond])]))
    assert str(exc.value) == "value"

    # Value too long (> 512)
    cond = {"header": "user-agent", "op": "equals", "value": "a" * 513}
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(conditions=[cond])]))
    assert str(exc.value) == "value"

    # Exactly 512 is allowed
    cond = {"header": "user-agent", "op": "equals", "value": "a" * 512}
    assert parse_rules(json.dumps([_make_rule(conditions=[cond])]))

    # Invalid regex
    for op in ("regex", "not_regex"):
        cond = {"header": "user-agent", "op": op, "value": "[unclosed"}
        with pytest.raises(ValueError) as exc:
            parse_rules(json.dumps([_make_rule(conditions=[cond])]))
        assert str(exc.value) == "value"


def test_parse_rules_rejects_bad_condition_case_sensitive():
    cond = {"header": "user-agent", "op": "equals", "value": "x", "case_sensitive": "true"}
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(conditions=[cond])]))
    assert str(exc.value) == "case_sensitive"


def test_parse_rules_rejects_bad_modifications():
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications="not-a-dict")]))  # type: ignore[arg-type]
    assert str(exc.value) == "modifications"

    # Headers not list
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"headers": "not-list"})]))
    assert str(exc.value) == "headers"

    # Headers > 16
    too_many = [{"key": f"X-Hdr-{i}", "value": "1"} for i in range(17)]
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"headers": too_many})]))
    assert str(exc.value) == "headers"

    # Forbidden header in modifications
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"headers": [{"key": "Content-Type", "value": "text/html"}]})]))
    assert str(exc.value) == "headers"

    # Invalid header key
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"headers": [{"key": "Bad Key", "value": "1"}]})]))
    assert str(exc.value) == "headers"

    # Header value > 512 chars
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"headers": [{"key": "X-Custom", "value": "a" * 513}]})]))
    assert str(exc.value) == "headers"

    # Bad exclude_nodes
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"exclude_nodes": "not-list"})]))
    assert str(exc.value) == "exclude_nodes"

    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"exclude_nodes": [123]})]))
    assert str(exc.value) == "exclude_nodes"

    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"exclude_nodes": ["a" * 513]})]))
    assert str(exc.value) == "exclude_nodes"

    # Bad remark_template
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"remark_template": 123})]))
    assert str(exc.value) == "remark_template"

    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"remark_template": "a" * 513})]))
    assert str(exc.value) == "remark_template"

    # Bad skip_device_limit
    with pytest.raises(ValueError) as exc:
        parse_rules(json.dumps([_make_rule(modifications={"skip_device_limit": "true"})]))
    assert str(exc.value) == "skip_device_limit"


def test_evaluate_empty_rules_or_invalid():
    assert evaluate([], {"user-agent": "test"}) is None
    assert evaluate(None, {"user-agent": "test"}) is None  # type: ignore[arg-type]
    assert evaluate("not-list", {"user-agent": "test"}) is None  # type: ignore[arg-type]


def test_evaluate_rule_without_conditions_matches_always():
    rule = _make_rule(name="always-match", response="mihomo")
    result = evaluate([rule], {"user-agent": "curl/7.68.0"})
    assert result is not None
    assert result["rule"] == "always-match"
    assert result["response"] == "mihomo"
    assert result["headers"] == []
    assert result["exclude_nodes"] == []
    assert result["remark_template"] == ""
    assert result["skip_device_limit"] is False


def test_evaluate_skips_disabled_rules_and_preserves_order():
    r1 = _make_rule(name="r1-disabled", enabled=False, response="clash")
    r2 = _make_rule(name="r2-enabled", enabled=True, response="singbox")
    r3 = _make_rule(name="r3-enabled", enabled=True, response="mihomo")
    result = evaluate([r1, r2, r3], {})
    assert result is not None
    assert result["rule"] == "r2-enabled"
    assert result["response"] == "singbox"


def test_evaluate_match_all_vs_match_any():
    c1 = {"header": "x-foo", "op": "equals", "value": "1"}
    c2 = {"header": "x-bar", "op": "equals", "value": "2"}

    # match all: both required
    r_all = _make_rule(name="all", match="all", conditions=[c1, c2])
    assert evaluate([r_all], {"x-foo": "1"}) is None
    assert evaluate([r_all], {"x-foo": "1", "x-bar": "wrong"}) is None
    res = evaluate([r_all], {"x-foo": "1", "x-bar": "2"})
    assert res is not None and res["rule"] == "all"

    # match any: either is enough
    r_any = _make_rule(name="any", match="any", conditions=[c1, c2])
    assert evaluate([r_any], {"x-other": "0"}) is None
    res1 = evaluate([r_any], {"x-foo": "1"})
    assert res1 is not None and res1["rule"] == "any"
    res2 = evaluate([r_any], {"x-bar": "2"})
    assert res2 is not None and res2["rule"] == "any"


def test_evaluate_ops_equals_and_not_equals():
    r_eq = _make_rule(name="eq", conditions=[{"header": "user-agent", "op": "equals", "value": "Clash"}])
    # Case-insensitive by default
    assert evaluate([r_eq], {"user-agent": "clash"}) is not None
    assert evaluate([r_eq], {"user-agent": "CLASH"}) is not None
    assert evaluate([r_eq], {"user-agent": "v2ray"}) is None

    # Case-sensitive
    r_eq_cs = _make_rule(name="eq-cs", conditions=[{"header": "user-agent", "op": "equals", "value": "Clash", "case_sensitive": True}])
    assert evaluate([r_eq_cs], {"user-agent": "clash"}) is None
    assert evaluate([r_eq_cs], {"user-agent": "Clash"}) is not None

    # not_equals
    r_neq = _make_rule(name="neq", conditions=[{"header": "user-agent", "op": "not_equals", "value": "clash"}])
    assert evaluate([r_neq], {"user-agent": "clash"}) is None
    assert evaluate([r_neq], {"user-agent": "v2ray"}) is not None


def test_evaluate_ops_contains_and_not_contains():
    r_contains = _make_rule(name="contains", conditions=[{"header": "user-agent", "op": "contains", "value": "meta"}])
    assert evaluate([r_contains], {"user-agent": "Clash.Meta-1.0"}) is not None
    assert evaluate([r_contains], {"user-agent": "singbox"}) is None

    r_not_contains = _make_rule(name="not_contains", conditions=[{"header": "user-agent", "op": "not_contains", "value": "meta"}])
    assert evaluate([r_not_contains], {"user-agent": "Clash.Meta-1.0"}) is None
    assert evaluate([r_not_contains], {"user-agent": "singbox"}) is not None


def test_evaluate_ops_regex_and_not_regex():
    r_regex = _make_rule(name="regex", conditions=[{"header": "user-agent", "op": "regex", "value": r"^flclash|mihomo"}])
    assert evaluate([r_regex], {"user-agent": "FlClash/0.8.0"}) is not None
    assert evaluate([r_regex], {"user-agent": "mihomo-party"}) is not None
    assert evaluate([r_regex], {"user-agent": "v2rayNG"}) is None

    r_not_regex = _make_rule(name="not_regex", conditions=[{"header": "user-agent", "op": "not_regex", "value": r"^curl"}])
    assert evaluate([r_not_regex], {"user-agent": "curl/7.88.1"}) is None
    assert evaluate([r_not_regex], {"user-agent": "Wget/1.21"}) is not None


def test_evaluate_ops_exists_and_not_exists():
    r_exists = _make_rule(name="exists", conditions=[{"header": "x-hwid", "op": "exists"}])
    assert evaluate([r_exists], {"x-hwid": "device123"}) is not None
    assert evaluate([r_exists], {"x-hwid": ""}) is not None  # empty value still exists
    assert evaluate([r_exists], {}) is None

    r_not_exists = _make_rule(name="not_exists", conditions=[{"header": "x-hwid", "op": "not_exists"}])
    assert evaluate([r_not_exists], {"x-hwid": "device123"}) is None
    assert evaluate([r_not_exists], {}) is not None


def test_evaluate_missing_header_behavior():
    # Contract: отсутствующий заголовок для equals, contains, regex = нет совпадения, для not_* = совпадение.
    r_eq = _make_rule(conditions=[{"header": "x-missing", "op": "equals", "value": "val"}])
    assert evaluate([r_eq], {}) is None

    r_contains = _make_rule(conditions=[{"header": "x-missing", "op": "contains", "value": "val"}])
    assert evaluate([r_contains], {}) is None

    r_regex = _make_rule(conditions=[{"header": "x-missing", "op": "regex", "value": r".*"}])
    assert evaluate([r_regex], {}) is None

    r_exists = _make_rule(conditions=[{"header": "x-missing", "op": "exists"}])
    assert evaluate([r_exists], {}) is None

    r_neq = _make_rule(conditions=[{"header": "x-missing", "op": "not_equals", "value": "val"}])
    assert evaluate([r_neq], {}) is not None

    r_ncontains = _make_rule(conditions=[{"header": "x-missing", "op": "not_contains", "value": "val"}])
    assert evaluate([r_ncontains], {}) is not None

    r_nregex = _make_rule(conditions=[{"header": "x-missing", "op": "not_regex", "value": r".*"}])
    assert evaluate([r_nregex], {}) is not None

    r_nexists = _make_rule(conditions=[{"header": "x-missing", "op": "not_exists"}])
    assert evaluate([r_nexists], {}) is not None


def test_evaluate_value_truncated_to_512_chars():
    # Header value is longer than 512 characters
    prefix = "a" * 512
    full_val = prefix + "EXTRATEXT"

    # Header value is sliced to first 512 chars before comparison
    r_truncated_eq = _make_rule(conditions=[{"header": "user-agent", "op": "equals", "value": prefix}])
    assert evaluate([r_truncated_eq], {"user-agent": full_val}) is not None

    # Searching for text beyond 512 characters should not match
    r_extra = _make_rule(conditions=[{"header": "user-agent", "op": "contains", "value": "EXTRATEXT"}])
    assert evaluate([r_extra], {"user-agent": full_val}) is None


def test_evaluate_header_lookup_case_insensitivity_and_mappings():
    r = _make_rule(name="r", conditions=[{"header": "user-agent", "op": "equals", "value": "clash"}])

    # Header with different case
    assert evaluate([r], {"User-Agent": "clash"}) is not None
    assert evaluate([r], {"USER-AGENT": "clash"}) is not None

    # List of tuples
    assert evaluate([r], [("User-Agent", "clash")]) is not None

    # None headers
    assert evaluate([r], None) is None


def test_evaluate_modifications_returned_correctly():
    rule = _make_rule(
        name="custom-action",
        response="unavailable",
        modifications={
            "headers": [{"key": "Retry-After", "value": "3600"}],
            "exclude_nodes": ["node-bad"],
            "remark_template": "{{NODE}} - Expired",
            "skip_device_limit": True,
        },
    )
    result = evaluate([rule], {})
    assert result == {
        "rule": "custom-action",
        "response": "unavailable",
        "headers": [{"key": "Retry-After", "value": "3600"}],
        "exclude_nodes": ["node-bad"],
        "remark_template": "{{NODE}} - Expired",
        "skip_device_limit": True,
    }

    # Ensure return dict contains copies
    result["headers"].append({"key": "Other", "value": "1"})
    result["exclude_nodes"].append("other-node")
    assert len(rule["modifications"]["headers"]) == 1
    assert len(rule["modifications"]["exclude_nodes"]) == 1
