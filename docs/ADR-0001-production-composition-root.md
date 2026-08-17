# ADR-0001: Production Composition Root

**Status:** Accepted
**Date:** 2026-08-10

## Context

The repository contains an experimental `core.ModuleRegistry` and modules with
their own lifecycle abstractions. The production service, however, is composed
by `backend/main.py`: it builds one runtime bundle, registers the FastAPI
routers through `core.router_registration`, and starts background work through
`core.lifespan`. No production bootstrap creates or starts `ModuleRegistry`.

Leaving both models undocumented makes ownership, lifecycle ordering and
failure handling ambiguous.

## Decision

`backend/main.py` is the sole production composition root.

- Runtime services are constructed through `core.app_runtime_bundle`.
- HTTP routers are registered only through `core.router_registration`.
- Startup and shutdown responsibilities are owned by `core.lifespan`.
- `core.ModuleRegistry` and `backend/modules/*/module.py` are experimental
  library code, not a second production bootstrap contract.

New production capabilities must be wired through the existing composition
root. A future module-registry migration needs a separate ADR, an explicit
feature gate and lifecycle integration tests before any production router or
worker is moved.

## Consequences

This preserves the running deployment model and makes the migration boundary
testable. It intentionally does not delete experimental module code: tests and
non-production consumers may still use it until a separately approved removal
or migration is complete.

## Validation

`backend/tests/test_composition_root_contract.py` guards the current boundary:
the production root uses the router and lifespan composition helpers and does
not instantiate `ModuleRegistry`.
