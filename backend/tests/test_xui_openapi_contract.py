"""Contract tests for the pinned 3X-UI v3 OpenAPI catalog."""

from __future__ import annotations

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from integrations.xui.contract_catalog import (  # noqa: E402
    REGISTERED_V3_OPERATIONS,
    V3_EXPECTED_API_VERSION,
    V3_EXPECTED_OPENAPI_VERSION,
    V3_EXPECTED_TITLE,
    V3_SPEC_SHA256,
    legacy_v2_operations,
    load_v3_spec,
    operation_matrix,
    sha256_file,
    spec_operations,
    validate_catalog,
)
from integrations.xui import contract_catalog  # noqa: E402


def test_pinned_v3_source_identity_and_operation_count():
    spec = load_v3_spec()

    assert spec["openapi"] == V3_EXPECTED_OPENAPI_VERSION
    assert spec["info"]["title"] == V3_EXPECTED_TITLE
    assert spec["info"]["version"] == V3_EXPECTED_API_VERSION
    assert sha256_file(contract_catalog.V3_SPEC_PATH) == V3_SPEC_SHA256
    assert len(spec_operations(spec)) == 170


def test_every_v3_operation_has_an_explicit_matrix_classification():
    matrix = operation_matrix()

    assert len(matrix) == 170
    assert {(item["method"], item["path"]) for item in matrix} == {
        (item.method, item.path) for item in spec_operations()
    }
    assert {item["status"] for item in matrix} <= {"implemented", "planned", "out_of_scope"}
    assert all(item["reason"] for item in matrix)


def test_registered_v3_routes_are_declared_by_the_pinned_specification():
    assert REGISTERED_V3_OPERATIONS
    assert REGISTERED_V3_OPERATIONS <= spec_operations()


def test_v2_manifest_is_explicit_and_separate_from_default_v3_routing():
    legacy = legacy_v2_operations()

    assert legacy
    assert len(legacy) == 14
    assert all(item.method == "POST" or item.method == "GET" for item in legacy)
    assert not any(item.path == "/panel/login" for item in REGISTERED_V3_OPERATIONS)


def test_contract_catalog_has_no_integrity_errors():
    assert validate_catalog() == []
