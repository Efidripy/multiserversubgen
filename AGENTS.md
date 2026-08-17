# Agent Rules

## Обязательный старт

Проект наследует обязательный workspace-процесс из `E:\GitHub\AGENTS.md`.
Сначала выполнить bootstrap в указанном там порядке, затем прочитать
`PROJECT.md`, этот файл, `README.md` и канонический remediation record.
При расхождении правил действует workspace-канон.

## Scope and ownership

- Keep one change stream and one final integrator for a remediation task.
- Read [`PROJECT.md`](PROJECT.md) and the relevant documents in `docs/` before
  changing a subsystem.
- Preserve unrelated local work. Do not deploy, push, rewrite Git history or
  access production credentials unless the user explicitly authorises that
  operation.

## Security and operations

- Treat installer, updater, systemd and deployment changes as high risk.
- Never emit secrets, persist them to logs, or add them to systemd unit files.
- Keep production secrets in root-only host storage and document migration and
  rollback behaviour.
- Validate destructive shell targets before `rm`, extraction or rollback.

## Required checks

- Add or update focused regression coverage for behaviour changes.
- Run the owning package's lint, tests and build checks before handoff.
- Run the full tracked-shell ShellCheck gate after shell changes.
- Update the canonical remediation record when a finding is fixed, deferred or
  blocked by an external operation.
