import pytest

from services.subscription_client_settings import DEFAULT_CLIENTS, default_settings, validate_settings
from services.subscription_regex import validate_admin_regex


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a+)+$",
        r"(a|a)+",
        r"(.*)*",
        r"(\w+)\1",
        r".*.*.*.*",
        r"(a+){1,50}$",
        r"(a{1,50}){1,50}$",
        r"(a|ab){1,50}$",
        r"(a{2,5}){2,5}",
        r".{1,99999}.{1,99999}.{1,99999}.{1,99999}",
    ],
)
def test_validate_admin_regex_rejects_dangerous_patterns(pattern):
    with pytest.raises(ValueError):
        validate_admin_regex(pattern)


@pytest.mark.parametrize(
    "pattern",
    [
        r"\bhapp\b",
        r"^foo.*bar$",
        r"[a-z]+",
        r"\d+",
        r"^(?:foo|bar)?baz",
        r"(?:a+)?b",
        r"a{1,99999}b",
    ],
)
def test_validate_admin_regex_accepts_supported_patterns(pattern):
    validate_admin_regex(pattern)


def test_default_clients_regexes_are_accepted():
    for client in DEFAULT_CLIENTS:
        validate_admin_regex(client["user_agent_regex"])


def test_dangerous_user_agent_regex_is_rejected_with_field_name():
    settings = default_settings()
    settings["clients"][0]["user_agent_regex"] = r"(a+)+$"
    with pytest.raises(ValueError, match="^user_agent_regex$"):
        validate_settings(settings)


def test_dangerous_response_rule_regex_is_rejected_with_value_name():
    settings = default_settings()
    settings["response_rules"]["rules"] = (
        '[{"name":"dangerous","response":"default","conditions":'
        '[{"header":"User-Agent","op":"regex","value":"(a+)+$"}]}]'
    )
    with pytest.raises(ValueError, match="^value$"):
        validate_settings(settings)
