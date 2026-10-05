# ADR-0003: ownership-first installer and updater

## Status

Accepted.

## Context

`multiserversubgen` is often installed beside manually administered software:
Grafana, Prometheus, 3x-ui, nginx and other host components. A normal panel
update must never turn into an implicit package upgrade, global configuration
rewrite or destructive cleanup of that software.

## Decision

The installer keeps an ownership registry at
`/var/lib/<project>/component-ownership.json` (default:
`/var/lib/sub-manager/component-ownership.json`). Its states are:

- `mssg-managed` — installed and reconciled by MSSG;
- `external` — pre-existing or released to the operator;
- `adopted` — explicitly transferred to MSSG;
- `unknown` — fail closed.

For a legacy installation without a registry, an installed monitoring
component is discovered as `external`, never silently adopted. Version drift
from the recorded version also fails closed before monitoring reconciliation.

The normal updater is **panel-only**:

- it updates Sub-Manager code and its own service;
- it does not run package upgrades for present packages;
- it does not install or configure external/unknown Grafana or Prometheus;
- it does not update 3x-ui.

MSSG Grafana files are namespaced: provisioning files, dashboard directory and
the `grafana-server.service.d/40-sub-manager.conf` drop-in. The updater no
longer rewrites `/etc/grafana/grafana.ini` or recursively changes ownership of
the shared dashboard directory.

Removal is also ownership-first. It removes only registry-proven MSSG
monitoring fragments. The historical host-wide package/path purge is retired;
Grafana, 3x-ui, nginx and other shared components remain for their owner.

## Operator workflow

Inspect without mutation:

```bash
sudo bash scripts/installer/component-ownership.sh report
```

Adopt an existing Grafana/Prometheus only after a backup and compatibility
review. Adoption updates only the local registry; it does not restart a
service, alter a package or rewrite configuration:

```bash
sudo bash scripts/installer/component-ownership.sh adopt grafana prometheus
```

Before manually maintaining an MSSG-managed monitoring component, release it:

```bash
sudo bash scripts/installer/component-ownership.sh release grafana prometheus
```

3x-ui version changes remain a separate operator operation. The normal panel
updater never invokes `xui_install_release`, `x-ui migrate` or an x-ui
restart.

## Consequences

- Legacy Grafana/Prometheus no longer receive automatic MSSG provisioning
  until the operator explicitly adopts them.
- A version changed outside MSSG requires a conscious adoption/release decision
  before MSSG can reconcile monitoring again.
- Dependency upgrades are intentional operations, not a side effect of a
  panel update or reinstall.
