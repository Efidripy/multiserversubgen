"""Validation for administrator-provided regular expressions."""

from __future__ import annotations

import re
from typing import Any


def _parser_and_maxrepeat():
    parser = getattr(re, "_parser", None)
    if parser is not None:
        constants = getattr(re, "_constants", None)
        maxrepeat = getattr(constants, "MAXREPEAT", None) if constants is not None else None
        if maxrepeat is None:
            maxrepeat = getattr(parser, "MAXREPEAT", None)
        if maxrepeat is not None:
            return parser, maxrepeat

    try:
        import sre_parse as parser  # type: ignore[no-redef]
        import sre_constants

        return parser, sre_constants.MAXREPEAT
    except Exception:
        return None, None


def _op_name(op: Any) -> str:
    return str(getattr(op, "name", op))


def _is_node(value: Any) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and (hasattr(value[0], "name") or isinstance(value[0], str))
    )


def _contains_branch(value: Any) -> bool:
    if hasattr(value, "data"):
        value = value.data
    if _is_node(value):
        op, arg = value
        if _op_name(op) == "BRANCH":
            return True
        return _contains_branch(arg)
    if isinstance(value, (list, tuple)):
        return any(_contains_branch(item) for item in value)
    return False


def validate_admin_regex(pattern: str) -> None:
    """Reject administrator regexes with constructs that can cause runaway work."""

    if not isinstance(pattern, str):
        raise ValueError("invalid regular expression")

    parser, maxrepeat = _parser_and_maxrepeat()
    if parser is None or maxrepeat is None:
        raise ValueError("invalid regular expression")

    try:
        re.compile(pattern)
        tree = parser.parse(pattern, 0)
        if not hasattr(tree, "data") and not isinstance(tree, (list, tuple)):
            raise ValueError("invalid parse tree")
    except Exception as exc:
        raise ValueError("invalid regular expression") from exc

    wide_repeats = 0

    def walk(value: Any, inside_multiple: bool = False) -> None:
        nonlocal wide_repeats
        if hasattr(value, "data"):
            value = value.data
        if _is_node(value):
            op, arg = value
            name = _op_name(op)
            if name.startswith("GROUPREF"):
                raise ValueError("backreference")
            if name in {"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"}:
                try:
                    _minimum, maximum, body = arg
                except (TypeError, ValueError) as exc:
                    raise ValueError("invalid parse tree") from exc
                multiple = maximum > 1
                if multiple and inside_multiple:
                    raise ValueError("nested multiple repeat")
                if multiple and _contains_branch(body):
                    raise ValueError("multiple repeat over alternative")
                if maximum > 16:
                    wide_repeats += 1
                    if wide_repeats > 3:
                        raise ValueError("too many wide repeats")
                walk(body, inside_multiple or multiple)
                return
            if name == "SUBPATTERN":
                if isinstance(arg, tuple) and arg:
                    walk(arg[-1], inside_multiple)
                return
            if name == "BRANCH":
                if isinstance(arg, tuple) and len(arg) >= 2:
                    walk(arg[1], inside_multiple)
                return
            walk(arg, inside_multiple)
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                walk(item, inside_multiple)

    try:
        walk(tree)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("invalid parse tree") from exc
