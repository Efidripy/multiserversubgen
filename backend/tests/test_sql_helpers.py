import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from shared.sql import (
    assignment_list,
    checked_identifier,
    delete_by_ids_query,
    placeholders,
    update_by_id_query,
)


def test_checked_identifier_accepts_plain_column_names():
    assert checked_identifier("read_only") == "read_only"
    assert checked_identifier("name2") == "name2"


@pytest.mark.parametrize(
    "value",
    ["", "name = ?", "nodes; DROP TABLE nodes", "node-name", "1name"],
)
def test_checked_identifier_rejects_unsafe_fragments(value):
    with pytest.raises(ValueError):
        checked_identifier(value)


def test_assignment_list_builds_parameterized_set_clause():
    assert assignment_list(["name", "read_only"]) == "name = ?, read_only = ?"


def test_update_by_id_query_builds_checked_update_statement():
    assert (
        update_by_id_query("nodes", ["name"], extra_set=("updated_at = CURRENT_TIMESTAMP",))
        == "UPDATE nodes SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
    )


def test_placeholders_match_value_count():
    assert placeholders([1, 2, 3]) == "?,?,?"


def test_delete_by_ids_query_builds_checked_delete_statement():
    assert delete_by_ids_query("audit_events", "id", [1, 2]) == "DELETE FROM audit_events WHERE id IN (?,?)"


def test_empty_dynamic_fragments_are_rejected():
    with pytest.raises(ValueError):
        assignment_list([])
    with pytest.raises(ValueError):
        placeholders([])
