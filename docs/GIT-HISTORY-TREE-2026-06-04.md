# Git History Tree - 2026-06-04

## Goal

A compact source-of-truth snapshot of the current Git topology for `multiserversubgen`: branches, commit lines, known push events, divergence against `origin`, and the current detached work state.

## Repository state at capture time

- Captured on: `2026-06-04`
- Remote: `origin -> https://github.com/Efidripy/multiserversubgen.git`
- Total reachable commits: `367`
- Current HEAD: `896511d` - `Refine dashboard figma migration slice`
- Current mode: detached `HEAD`
- Detached base line: current detached work sits above `feature/sprint-1-dashboard-redesign-v2` (`b04a488`)
- Working tree is dirty
- Stash present: `0930be8` - `pre-slice-deploy stash`

## Important limitation

Git does not store a canonical "list of all pushes" as a first-class history object.
This file uses:

- remote refs under `origin/*`
- local reflog entries such as `update by push`
- branch/upstream divergence

That means push history here is "confirmed from local evidence", not a guaranteed full server-side audit log.

## Topology summary

### Active local heads

| Branch | Commit | Status | Notes |
|---|---|---|---|
| `main` | `3509d82` | ahead of `origin/main` by 2 | local main has 2 unpublished commits |
| `chore/ui-audit-and-security-redaction-20260531` | `89d94d6` | ahead of upstream by 1 | local branch moved past pushed `b50462c` |
| `feature/admin-redesign-sprint2` | `48e297f` | no upstream configured, but matches `origin/feature/admin-redesign-sprint2` | current Figma migration branch tip |
| `codex/dashboard-to-figma-design-migration` | `48e297f` | no upstream | alias branch pointing at same commit as sprint2 |
| `feature/sprint-1-dashboard-redesign-v2` | `b04a488` | local only | base line for current detached commit |
| `feature/bearer-token` | `4e159bf` | local only, matches remote tip | historic auth branch |

### Backup / archive heads

| Branch | Commit | Purpose |
|---|---|---|
| `backup/working-state-before-design-migration` | `3ba2bd2` | preserved UI state before redesign line split |
| `backup/bearer-token-2026-05-14` | `493e9be` | preserved bearer-token milestone |
| `backup/pre-knowledge-index-purge-20260321` | `f50c165` | pre docs cleanup snapshot |
| `backup/pre-docs-root-rewrite-20260321` | `3c9f908` | pre docs move snapshot |
| `backup/pre-history-rewrite-20260321` | `1ea82d7` | pre history rewrite snapshot |
| `backup/main-before-history-rewrite-2026-03-13` | `b7f8abc` | historic baseline |
| `backup/pre-cleanup-working-state` | `b7f8abc` | alias to same historic baseline |

### Tags

| Tag | Object | Notes |
|---|---|---|
| `working-state-v3.0-before-design-migration` | annotated tag -> commit `3ba2bd2` | preserved redesign baseline |
| `backup-before-cleanup` | `b7f8abc` | lightweight tag |
| `backup-before-history-rewrite-2026-03-13` | `b7f8abc` | lightweight tag |

## Confirmed divergence against origin

| Local branch | Upstream | Ahead | Behind | Meaning |
|---|---|---:|---:|---|
| `main` | `origin/main` | 2 | 0 | local `main` contains unpublished work on top of remote |
| `chore/ui-audit-and-security-redaction-20260531` | `origin/chore/ui-audit-and-security-redaction-20260531` | 1 | 0 | one local-only WIP commit not pushed |

Branches without upstream config are intentionally left out of this table.

## Commit tree - current high-signal view

```text
896511d (HEAD) Refine dashboard figma migration slice
|
| b04a488 (feature/sprint-1-dashboard-redesign-v2) feat: Implement Sprint 1 dashboard redesign with DashboardSummary component
| 9e7314f feat: Sprint 1 Dashboard Redesign - implement Figma design with Tailwind CSS
|/
3ba2bd2 (tag: working-state-v3.0-before-design-migration, backup/working-state-before-design-migration)
 feat: add activity log panel UI support
|
d38181d feat: fix encoding, add activity log panel, improve node/traffic UI
f713b4d feat: add file logging, improve client operation debug logging, UI and backend fixes
3509d82 (main) UI layout fixes, monitoring updates, and redact audit credentials
a18ea16 fix: Traffic Stats period filtering and layout
57b5454 (origin/main) chore(deps-dev): bump vite (#35)
299bc05 Initial plan (#36)
4e159bf (origin/feature/bearer-token, feature/bearer-token)
 feat: add bearer token authentication support for node management
...

36bea02 feat: Figma variant4 redesign slices 1-6
bccd9da feat: slice7 - TrafficStats preset-4 styles and chart color fix
08e29a1 feat: slice8 - exact Figma variant4 match
7ef8612 feat: slice8b - Figma exact icon gradients and metric bars
48e297f (feature/admin-redesign-sprint2, codex/dashboard-to-figma-design-migration,
 origin/feature/admin-redesign-sprint2)
 refactor: ServerStatus Core section - match Figma design (v4)
```

## Current branch relationships

### Detached line

- `HEAD -> 896511d`
- parent commit: `b04a488`
- this commit is not attached to any branch yet
- if it matters, the safest landing options are:
  - attach it to `feature/sprint-1-dashboard-redesign-v2`
  - create a fresh branch from current detached `HEAD`

### Figma redesign line

- `feature/admin-redesign-sprint2`
- `codex/dashboard-to-figma-design-migration`
- `origin/feature/admin-redesign-sprint2`

All three point to the same commit `48e297f`.

### Audit / Tailwind experiment line

- remote tip: `b50462c`
- local tip: `89d94d6`

This means the local branch advanced one commit after the last confirmed push.

### Main line

- remote tip: `57b5454`
- local tip: `3509d82`
- unpublished local commits:
  - `a18ea16` - `fix: Traffic Stats period filtering and layout`
  - `3509d82` - `UI layout fixes, monitoring updates, and redact audit credentials`

## Confirmed push evidence from reflog

These are the push-related events visible from local reflog:

| Date | Ref | Commit | Event |
|---|---|---|---|
| `2026-06-02 15:36:44 +0300` | `origin/feature/admin-redesign-sprint2` | `48e297f` | `update by push` |
| `2026-06-02 02:46:41 +0300` | `origin/chore/ui-audit-and-security-redaction-20260531` | `b50462c` | `update by push` |
| `2026-06-01 01:45:41 +0300` | `origin/chore/ui-audit-and-security-redaction-20260531` | `f713b4d` | `update by push` |
| `2026-05-31 16:37:09 +0300` | `origin/chore/ui-audit-and-security-redaction-20260531` | `3509d82` | `update by push` |
| `2026-05-14 11:18:06 +0300` | `origin/main` | `4e159bf` | `update by push` |
| `2026-05-14 11:15:40 +0300` | `origin/feature/bearer-token` | `4e159bf` | `update by push` |

## Merge-heavy historical zone

The older part of history contains many PR merges from `copilot/*` lines, including:

- PR `#32` - `copilot/refactor-multiserversubgen-architecture`
- PR `#31` - `copilot/reduce-cpu-load-idle`
- PR `#30` - `copilot/optimize-systemd-service-cpu-load`
- PR `#29` - `revert-28-copilot/update-subscription-link-format`
- PR `#28` - `copilot/update-subscription-link-format`
- PR `#13` through `#26` - multiple UI/backend incremental merges

This explains why the full graph becomes wide quickly: the repository has both direct local commits and mirrored merge commits from remote PR workflows.

## Practical reading of the repo today

1. Stable published baseline is still `origin/main` at `57b5454`.
2. Local `main` is ahead and unpublished.
3. The most coherent redesign line is `48e297f`, because local and remote sprint branches agree there.
4. The current `HEAD` at `896511d` is isolated and easy to lose if checked out away without branching.
5. The repo also keeps several explicit backup refs, so history preservation is being used intentionally.

## Regeneration commands

```powershell
git -C E:\GitHub\repos\multiserversubgen status --short --branch
git -C E:\GitHub\repos\multiserversubgen remote -v
git -C E:\GitHub\repos\multiserversubgen branch -a -vv
git -C E:\GitHub\repos\multiserversubgen log --graph --decorate --oneline --all --date-order --max-count=120
git -C E:\GitHub\repos\multiserversubgen reflog --date=iso --format="%h|%gd|%gs|%cd" --all -n 80
git -C E:\GitHub\repos\multiserversubgen for-each-ref --format="%(refname:short)|%(objectname:short)|%(committerdate:iso8601)|%(authorname)|%(subject)|%(upstream:short)" refs/heads refs/remotes
```
