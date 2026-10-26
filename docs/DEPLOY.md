# Деплой

> **Смотрите также:** [UPDATE.md](./UPDATE.md) — технические детали механизма обновления.

## Хосты

| Алиас | Хост | Назначение |
|-------|------|-----------|
| `prod` | **dev.kleva.ru** (порт 1452) | **Производственный сервер** |
| `vm3`  | vm3.kleva.ru / 192.168.48.130 (порт 22) | Локальная VMware-машина для тестов |

> [!IMPORTANT]
> `prod` = `dev.kleva.ru`. Деструктивное тестирование на проде **запрещено**.
> Для экспериментальных деплоев используйте `vm3`.

## Быстрый старт: деплой на прод

```powershell
# Из чистого checkout ветки main:
pwsh scripts/deploy/deploy.ps1 -Target prod
```

Скрипт сам добавит `E:\Git\usr\bin` (ssh/scp) в конец `PATH`, чтобы не
затронуть `tar.exe` из `C:\Windows\System32` (GNU tar из Git ломает Windows tar).

### Флаги

| Флаг | Описание |
|------|---------|
| `-Target prod\|vm3` | Цель деплоя (обязательно) |
| `-DryRun` | Только preflight и pre-check, без деплоя |
| `-Yes` | Пропустить интерактивное подтверждение |
| `-KeyPath <path>` | Переопределить путь к SSH-ключу |

## Что проверяется

### Preflight (до деплоя)

1. `git fetch origin` — синхронизация с remote.
2. **Чистое рабочее дерево** — незакоммиченные изменения запрещены.
3. **Только для `prod`:** ветка должна быть `main`, `HEAD == origin/main`.
4. **Только для `prod`:** все CI checks зелёные (через `gh pr checks` / `gh api`).
5. Информация о текущей версии на сервере и числе коммитов к деплою.
6. Интерактивное подтверждение вводом `yes` (пропускается с `-Yes`).

### Pre-check (read-only SSH, перед деплоем)

- `sub-manager` active.
- Health endpoint (`http://127.0.0.1:666/health`) → 200.
- Свободное место на `/` ≥ 3 GB.
- Наличие последнего бэкапа в `/var/backups/sub-manager_deploy/`.

### Деплой

Вызывает `scripts/installer/windows/invoke-remote-deploy.ps1 -Mode update`.
На сервере выполняется `scripts/deploy/server-deploy.sh` с `ROLLBACK_ON_FAIL=1`:
backup-first → staged build → health-check → автоматический rollback при сбое.

### Post-check (после деплоя)

- Health 200 три раза подряд с паузой 5 с.
- Проверка journalctl за последние 3 минуты на `ERROR`/`Traceback`.

## Как откатить

> [!WARNING]
> Автоматический rollback уже выполняется `server-deploy.sh` при `ROLLBACK_ON_FAIL=1`.
> Ручной откат нужен только если автоматический не сработал.

```bash
# Найти последний бэкап:
ssh root@dev.kleva.ru -p 1452 'ls -lt /var/backups/sub-manager_deploy/*.tgz | head -5'

# Остановить сервис и восстановить из бэкапа:
ssh root@dev.kleva.ru -p 1452 '
  systemctl stop sub-manager
  tar -xzf /var/backups/sub-manager_deploy/<backup>.tgz -C /
  systemctl start sub-manager
'

# Проверить здоровье:
ssh root@dev.kleva.ru -p 1452 'curl -sf http://127.0.0.1:666/health'
```

## SSH-ключ и алиасы

- Ключ prod: `%USERPROFILE%\.ssh\id_ed25519_dev_kleva_codex`
- SSH config alias: `dev-kleva-codex`
- vm3 alias: `vm3` / `vm3-root`

Путь к ключу задаётся в [`scripts/deploy/targets.psd1`](../scripts/deploy/targets.psd1).
Переопределяется флагом `-KeyPath`.

## targets.psd1 — таблица целей

[`scripts/deploy/targets.psd1`](../scripts/deploy/targets.psd1) хранит все параметры
подключения. **Никаких секретов и паролей в файле нет.**
