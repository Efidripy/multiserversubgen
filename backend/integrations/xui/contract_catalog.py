"""Pinned 3X-UI API contract catalog.

The vendored OpenAPI document is the source of truth for modern (3.x) panel
routes.  This module intentionally does *not* perform HTTP requests or choose
an adapter: it supplies one small, deterministic catalog which adapters and
tests can share.  Older routes live in the separate v2 manifest and must only
be selected by an explicit legacy-capability decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal


V3_SPEC_PATH = Path(__file__).with_name("openapi") / "3x-ui-3.x.openapi.json"
V2_LEGACY_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "contracts" / "3x-ui-v2-legacy-manifest.json"
)
V3_SPEC_SHA256 = "3eeca204fe9191d495d7c455d30001b3727a41f7ba0976c93eecab4152dc9a7c"
V3_EXPECTED_OPENAPI_VERSION = "3.0.3"
V3_EXPECTED_TITLE = "3X-UI Panel API"
V3_EXPECTED_API_VERSION = "3.x"

HTTP_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put"})
OperationStatus = Literal["implemented", "planned", "out_of_scope"]


@dataclass(frozen=True, order=True)
class RouteRef:
    """A normalized OpenAPI operation key."""

    method: str
    path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", self.method.upper())
        if self.method.lower() not in HTTP_METHODS:
            raise ValueError(f"Unsupported HTTP method: {self.method}")
        if not self.path.startswith("/"):
            raise ValueError(f"OpenAPI paths must start with '/': {self.path}")

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def route(method: str, path: str) -> RouteRef:
    """Short declaration helper for the maintained v3 registry."""

    return RouteRef(method, path)


# The application-facing v3 registry.  Adding a modern outbound route means
# adding it here first; the route validation test rejects paths absent from the
# pinned OpenAPI document.
REGISTERED_V3_OPERATIONS = frozenset(
    {
        # Authentication
        route("GET", "/csrf-token"),
        route("POST", "/login"),
        # Inbounds
        route("GET", "/panel/api/inbounds/list"),
        route("GET", "/panel/api/inbounds/list/slim"),
        route("GET", "/panel/api/inbounds/options"),
        route("POST", "/panel/api/inbounds/add"),
        route("POST", "/panel/api/inbounds/del/{id}"),
        route("POST", "/panel/api/inbounds/update/{id}"),
        route("POST", "/panel/api/inbounds/setEnable/{id}"),
        route("POST", "/panel/api/inbounds/{id}/resetTraffic"),
        route("POST", "/panel/api/inbounds/{id}/delAllClients"),
        route("POST", "/panel/api/inbounds/resetAllTraffics"),
        # Clients
        route("GET", "/panel/api/clients/list"),
        route("GET", "/panel/api/clients/list/paged"),
        route("POST", "/panel/api/clients/add"),
        route("POST", "/panel/api/clients/update/{email}"),
        route("POST", "/panel/api/clients/del/{email}"),
        route("POST", "/panel/api/clients/bulkDel"),
        route("POST", "/panel/api/clients/onlines"),
        route("GET", "/panel/api/clients/traffic/{email}"),
        route("POST", "/panel/api/clients/resetTraffic/{email}"),
        route("POST", "/panel/api/clients/delDepleted"),
        route("POST", "/panel/api/clients/bulkAdjust"),
        route("GET", "/panel/api/clients/links/{email}"),
        route("POST", "/panel/api/clients/ips/{email}"),
        route("POST", "/panel/api/clients/clearIps/{email}"),
        route("POST", "/panel/api/clients/lastOnline"),
        route("POST", "/panel/api/clients/bulkResetTraffic"),
        route("POST", "/panel/api/clients/{email}/attach"),
        route("POST", "/panel/api/clients/{email}/detach"),
        route("GET", "/panel/api/clients/groups"),
        route("POST", "/panel/api/clients/groups/create"),
        route("POST", "/panel/api/clients/groups/rename"),
        route("POST", "/panel/api/clients/groups/delete"),
        route("POST", "/panel/api/clients/groups/bulkAdd"),
        route("POST", "/panel/api/clients/groups/bulkRemove"),
        route("GET", "/panel/api/clients/groups/{name}/emails"),
        route("GET", "/panel/api/clients/subLinks/{subId}"),
        # Server and operations
        route("GET", "/panel/api/server/status"),
        route("GET", "/panel/api/server/getConfigJson"),
        route("POST", "/panel/api/server/restartXrayService"),
        route("POST", "/panel/api/server/logs/{count}"),
        route("GET", "/panel/api/server/getDb"),
        route("POST", "/panel/api/server/importDB"),
        route("GET", "/panel/api/server/history/{metric}/{bucket}"),
        route("GET", "/panel/api/server/getPanelUpdateInfo"),
        route("GET", "/panel/api/server/xrayObservatory"),
        route("POST", "/panel/api/server/stopXrayService"),
        route("GET", "/panel/api/server/getXrayVersion"),
        route("POST", "/panel/api/server/installXray/{version}"),
        route("POST", "/panel/api/server/updateGeofile"),
        route("POST", "/panel/api/server/updatePanel"),
        route("POST", "/panel/api/server/xraylogs/{count}"),
        route("GET", "/panel/api/server/xrayMetricsState"),
        route("GET", "/panel/api/server/getNewUUID"),
        route("GET", "/panel/api/server/getNewX25519Cert"),
        route("GET", "/panel/api/server/getNewVlessEnc"),
        route("GET", "/panel/api/server/getNewmldsa65"),
        # API tokens, backup, Xray traffic
        route("GET", "/panel/api/setting/apiTokens"),
        route("POST", "/panel/api/setting/apiTokens/create"),
        route("POST", "/panel/api/setting/apiTokens/delete/{id}"),
        route("POST", "/panel/api/setting/apiTokens/setEnabled/{id}"),
        route("POST", "/panel/api/backuptotgbot"),
        route("GET", "/panel/api/xray/getOutboundsTraffic"),
    }
)


def load_v3_spec() -> dict[str, Any]:
    """Load the checked-in 3X-UI 3.x OpenAPI document."""

    with V3_SPEC_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA-256 digest without loading a whole file twice."""

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def spec_operations(spec: dict[str, Any] | None = None) -> frozenset[RouteRef]:
    """Return every HTTP operation declared by the pinned specification."""

    spec = load_v3_spec() if spec is None else spec
    operations: set[RouteRef] = set()
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            if method in item:
                operations.add(route(method, path))
    return frozenset(operations)


def _load_legacy_manifest() -> list[dict[str, Any]]:
    with V2_LEGACY_MANIFEST_PATH.open(encoding="utf-8") as source:
        manifest = json.load(source)
    return manifest["operations"]


def legacy_v2_operations() -> frozenset[RouteRef]:
    """Return routes retained solely for explicit 3X-UI v2 compatibility."""

    return frozenset(route(item["method"], item["path"]) for item in _load_legacy_manifest())


def validate_catalog(spec: dict[str, Any] | None = None) -> list[str]:
    """Validate the pinned source, full matrix prerequisites, and registries.

    The return value is deliberately data-only so this function can be used by
    CI, a maintenance command, or an adapter startup guard without emitting
    credentials or panel response bodies.
    """

    spec = load_v3_spec() if spec is None else spec
    errors: list[str] = []
    info = spec.get("info") if isinstance(spec.get("info"), dict) else {}
    if spec.get("openapi") != V3_EXPECTED_OPENAPI_VERSION:
        errors.append("Pinned OpenAPI version differs from the reviewed 3X-UI v3 source")
    if info.get("title") != V3_EXPECTED_TITLE or info.get("version") != V3_EXPECTED_API_VERSION:
        errors.append("Pinned OpenAPI info block differs from the reviewed 3X-UI v3 source")
    if sha256_file(V3_SPEC_PATH) != V3_SPEC_SHA256:
        errors.append("Pinned OpenAPI SHA-256 differs from the reviewed source")

    available = spec_operations(spec)
    unknown = sorted(REGISTERED_V3_OPERATIONS - available)
    if unknown:
        errors.append("Registered v3 routes absent from OpenAPI: " + ", ".join(item.key for item in unknown))
    if len(available) != 170:
        errors.append(f"Expected 170 OpenAPI operations, got {len(available)}")

    try:
        legacy = _load_legacy_manifest()
    except (KeyError, OSError, ValueError) as exc:
        errors.append(f"Invalid v2 legacy manifest: {exc}")
        legacy = []
    keys = [route(item.get("method", ""), item.get("path", "")).key for item in legacy]
    if len(keys) != len(set(keys)):
        errors.append("v2 legacy manifest contains duplicate route entries")
    for item in legacy:
        if item.get("classification") != "legacy_only" or not item.get("reason"):
            errors.append("Every v2 legacy entry requires classification=legacy_only and a reason")
            break
    return errors


def operation_matrix(spec: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Generate the complete, machine-readable 170-operation ownership matrix.

    Every spec operation is classified.  A route is never implicitly "legacy":
    the only legacy operations are in ``3x-ui-v2-legacy-manifest.json``.
    """

    matrix: list[dict[str, str]] = []
    for item in sorted(spec_operations(spec)):
        if item in REGISTERED_V3_OPERATIONS:
            status: OperationStatus = "implemented"
            reason = "Входит в control-plane API приложения; валидация пути привязана к pinned OpenAPI."
        else:
            status = "out_of_scope"
            reason = (
                "Upstream-функция панели не экспонируется продуктом; добавление требует отдельного "
                "product/API решения и contract-теста."
            )
        matrix.append({"method": item.method, "path": item.path, "status": status, "reason": reason})
    return matrix


def matrix_json(spec: dict[str, Any] | None = None) -> str:
    """Serialize the full matrix for review tooling without creating artifacts."""

    # ASCII keeps the command usable from legacy Windows terminals too; JSON
    # consumers decode the escaped Russian reason text normally.
    return json.dumps(operation_matrix(spec), ensure_ascii=True, indent=2) + "\n"


def _main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка закреплённого OpenAPI 3X-UI v3")
    parser.add_argument("--matrix", action="store_true", help="Напечатать JSON-матрицу всех операций")
    args = parser.parse_args(argv)
    errors = validate_catalog()
    if errors:
        print("\n".join(errors))
        return 1
    if args.matrix:
        print(matrix_json(), end="")
    else:
        print(f"ok: {len(spec_operations())} OpenAPI operations; {len(REGISTERED_V3_OPERATIONS)} registered v3 routes")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
