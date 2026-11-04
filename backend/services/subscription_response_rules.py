from __future__ import annotations

from collections.abc import Mapping
import json
import re
from typing import Any

from services.subscription_client_settings import _FORBIDDEN_HEADERS, _HEADER_NAME
from services.subscription_regex import validate_admin_regex

MAX_RULES = 64
MAX_CONDITIONS = 16
MAX_MOD_HEADERS = 16
MAX_VALUE_LEN = 512
MAX_HEADER_NAME_LEN = 128
MAX_RULE_NAME_LEN = 128

ALLOWED_OPS = {
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "regex",
    "not_regex",
    "exists",
    "not_exists",
}

ALLOWED_RESPONSES = {
    "default",
    "base64",
    "mihomo",
    "clash",
    "singbox",
    "xray_json",
    "page",
    "block",
    "not_found",
    "unavailable",
}


def _validate_condition(cond: Any) -> dict[str, Any]:
    if not isinstance(cond, dict):
        raise ValueError("conditions")

    header = cond.get("header")
    if not isinstance(header, str) or not header or len(header) > MAX_HEADER_NAME_LEN:
        raise ValueError("header")
    if not _HEADER_NAME.fullmatch(header) or header.lower() in _FORBIDDEN_HEADERS:
        raise ValueError("header")

    op = cond.get("op")
    if not isinstance(op, str) or op not in ALLOWED_OPS:
        raise ValueError("op")

    if op in ("exists", "not_exists"):
        val = cond.get("value", "")
        if not isinstance(val, str) or len(val) > MAX_VALUE_LEN:
            raise ValueError("value")
    else:
        if "value" not in cond:
            raise ValueError("value")
        val = cond["value"]
        if not isinstance(val, str) or len(val) > MAX_VALUE_LEN:
            raise ValueError("value")
        if op in ("regex", "not_regex"):
            try:
                validate_admin_regex(val)
            except ValueError as exc:
                raise ValueError("value") from exc

    case_sensitive = cond.get("case_sensitive", False)
    if not isinstance(case_sensitive, bool):
        raise ValueError("case_sensitive")

    return {
        "header": header,
        "op": op,
        "value": val,
        "case_sensitive": case_sensitive,
    }


def _validate_modifications(mods: Any) -> dict[str, Any]:
    if not isinstance(mods, dict):
        raise ValueError("modifications")

    clean_headers: list[dict[str, str]] = []
    if "headers" in mods:
        headers_val = mods["headers"]
        if not isinstance(headers_val, list) or len(headers_val) > MAX_MOD_HEADERS:
            raise ValueError("headers")
        for item in headers_val:
            if not isinstance(item, dict):
                raise ValueError("headers")
            key = item.get("key")
            value = item.get("value", "")
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("headers")
            if not key or len(key) > MAX_HEADER_NAME_LEN or len(value) > MAX_VALUE_LEN:
                raise ValueError("headers")
            if not _HEADER_NAME.fullmatch(key) or key.lower() in _FORBIDDEN_HEADERS:
                raise ValueError("headers")
            clean_headers.append({"key": key, "value": value})

    clean_exclude_nodes: list[str] = []
    if "exclude_nodes" in mods:
        exclude_val = mods["exclude_nodes"]
        if not isinstance(exclude_val, list):
            raise ValueError("exclude_nodes")
        for node in exclude_val:
            if not isinstance(node, str) or len(node) > MAX_VALUE_LEN:
                raise ValueError("exclude_nodes")
            clean_exclude_nodes.append(node)

    remark_template = mods.get("remark_template", "")
    if not isinstance(remark_template, str) or len(remark_template) > MAX_VALUE_LEN:
        raise ValueError("remark_template")

    skip_device_limit = mods.get("skip_device_limit", False)
    if not isinstance(skip_device_limit, bool):
        raise ValueError("skip_device_limit")

    return {
        "headers": clean_headers,
        "exclude_nodes": clean_exclude_nodes,
        "remark_template": remark_template,
        "skip_device_limit": skip_device_limit,
    }


def _validate_rule(rule: Any) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise ValueError("rules")

    name = rule.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= MAX_RULE_NAME_LEN):
        raise ValueError("name")

    enabled = rule.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError("enabled")

    match = rule.get("match", "all")
    if not isinstance(match, str) or match not in ("all", "any"):
        raise ValueError("match")

    conditions_raw = rule.get("conditions", [])
    if not isinstance(conditions_raw, list) or len(conditions_raw) > MAX_CONDITIONS:
        raise ValueError("conditions")
    clean_conditions = [_validate_condition(cond) for cond in conditions_raw]

    response = rule.get("response")
    if not isinstance(response, str) or response not in ALLOWED_RESPONSES:
        raise ValueError("response")

    mods_raw = rule.get("modifications", {})
    clean_mods = _validate_modifications(mods_raw)

    return {
        "name": name,
        "enabled": enabled,
        "match": match,
        "conditions": clean_conditions,
        "response": response,
        "modifications": clean_mods,
    }


def parse_rules(text: str) -> list[dict]:
    if not isinstance(text, str):
        raise ValueError("rules")
    stripped = text.strip()
    if not stripped:
        return []
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("rules") from exc

    if not isinstance(data, list) or len(data) > MAX_RULES:
        raise ValueError("rules")

    return [_validate_rule(item) for item in data]


def validate_response_rules(text: str) -> None:
    parse_rules(text)


def _lookup_header(headers: Any, target_name: str) -> tuple[bool, str]:
    if headers is None:
        return False, ""
    target_lower = target_name.lower()
    if isinstance(headers, Mapping):
        val = headers.get(target_name)
        if val is None and target_name != target_lower:
            val = headers.get(target_lower)
        if val is not None:
            return True, str(val)[:MAX_VALUE_LEN]
        for k, v in headers.items():
            if str(k).lower() == target_lower:
                return True, ("" if v is None else str(v))[:MAX_VALUE_LEN]
        return False, ""
    if isinstance(headers, (list, tuple)):
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                if str(item[0]).lower() == target_lower:
                    v = item[1]
                    return True, ("" if v is None else str(v))[:MAX_VALUE_LEN]
        return False, ""
    if hasattr(headers, "items"):
        for k, v in headers.items():
            if str(k).lower() == target_lower:
                return True, ("" if v is None else str(v))[:MAX_VALUE_LEN]
    return False, ""


def _eval_condition(cond: dict[str, Any], headers: Any) -> bool:
    header_name = cond.get("header", "")
    op = cond.get("op", "")
    expected = cond.get("value", "")
    case_sensitive = bool(cond.get("case_sensitive", False))

    exists, actual = _lookup_header(headers, header_name)

    if not exists:
        if op in ("equals", "contains", "regex", "exists"):
            return False
        if op in ("not_equals", "not_contains", "not_regex", "not_exists"):
            return True
        return False

    if op == "exists":
        return True
    if op == "not_exists":
        return False
    if op == "equals":
        return actual == expected if case_sensitive else actual.lower() == expected.lower()
    if op == "not_equals":
        return actual != expected if case_sensitive else actual.lower() != expected.lower()
    if op == "contains":
        return expected in actual if case_sensitive else expected.lower() in actual.lower()
    if op == "not_contains":
        return expected not in actual if case_sensitive else expected.lower() not in actual.lower()
    if op == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return bool(re.search(expected, actual[:MAX_VALUE_LEN], flags=flags))
        except re.error:
            return False
    if op == "not_regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return not bool(re.search(expected, actual[:MAX_VALUE_LEN], flags=flags))
        except re.error:
            return True

    return False


def _matches_rule(rule: dict[str, Any], headers: Any) -> bool:
    conditions = rule.get("conditions")
    if not conditions:
        return True
    match_mode = rule.get("match", "all")
    if match_mode == "any":
        return any(_eval_condition(cond, headers) for cond in conditions)
    return all(_eval_condition(cond, headers) for cond in conditions)


def evaluate(rules: list[dict], headers: Any = None) -> dict | None:
    if not isinstance(rules, list):
        return None

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if not rule.get("enabled", True):
            continue
        if _matches_rule(rule, headers):
            mods = rule.get("modifications") or {}
            raw_headers = mods.get("headers") or []
            headers_copy = [
                {"key": str(h.get("key", "")), "value": str(h.get("value", ""))}
                for h in raw_headers
                if isinstance(h, dict) and "key" in h
            ]
            raw_exclude = mods.get("exclude_nodes") or []
            exclude_nodes_copy = [str(node) for node in raw_exclude if isinstance(node, str)]
            remark_template = str(mods.get("remark_template", ""))
            skip_device_limit = bool(mods.get("skip_device_limit", False))

            return {
                "rule": str(rule.get("name", "")),
                "response": str(rule.get("response", "default")),
                "headers": headers_copy,
                "exclude_nodes": exclude_nodes_copy,
                "remark_template": remark_template,
                "skip_device_limit": skip_device_limit,
            }

    return None
