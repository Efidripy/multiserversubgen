"""Small SQL construction helpers for allowlisted dynamic fragments."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def checked_identifier(name: str) -> str:
    """Return a SQL identifier only if it is a plain column/table name."""
    if not _SQL_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return name


def assignment_list(columns: Iterable[str]) -> str:
    """Build a comma-separated ``column = ?`` list from checked names."""
    checked = [f"{checked_identifier(column)} = ?" for column in columns]
    if not checked:
        raise ValueError("At least one SQL assignment is required")
    return ", ".join(checked)


def placeholders(values: Sequence[object]) -> str:
    """Build placeholders for an existing parameter sequence."""
    if not values:
        raise ValueError("At least one SQL placeholder is required")
    return ",".join("?" for _ in values)


def update_by_id_query(table: str, columns: Iterable[str], *, extra_set: Sequence[str] = ()) -> str:
    """Build an UPDATE query for an allowlisted table and checked columns."""
    set_clause = assignment_list(columns)
    if extra_set:
        set_clause = ", ".join([set_clause, *extra_set])
    return " ".join(
        [
            "UPDATE",
            checked_identifier(table),
            "SET",
            set_clause,
            "WHERE id = ?",
        ]
    )


def delete_by_ids_query(table: str, id_column: str, values: Sequence[object]) -> str:
    """Build a DELETE query with checked identifiers and parameter placeholders."""
    return " ".join(
        [
            "DELETE FROM",
            checked_identifier(table),
            "WHERE",
            checked_identifier(id_column),
            "IN",
            f"({placeholders(values)})",
        ]
    )
