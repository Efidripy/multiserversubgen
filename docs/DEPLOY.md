# Деплой

> **Смотрите также:** [UPDATE.md](./UPDATE.md) — технические детали механизма обновления.

## Локальная конфигурация целей

Отслеживаемый файл [`scripts/deploy/targets.psd1`](../scripts/deploy/targets.psd1)
служит только шаблоном и не содержит рабочих параметров. Перед первым деплоем
скопируйте его в `scripts/deploy/targets.local.psd1`, затем заполните локальный
файл значениями своей инфраструктуры. `targets.local.psd1` игнорируется Git и
обязателен для запуска `deploy.ps1`.

| Алиас | Хост | Назначение |
|-------|------|-----------|
| `prod` | `example.invalid` (порт `<ssh-port>`) | Производственный сервер |
| `vm3` | `host-a.example.invalid` / `192.0.2.130` (порт `<ssh-port>`) | Тестовая машина |

> [!IMPORTANT]
> Деструктивное тестирование на производственном сервере запрещено. Для
> экспериментальных деплоев используйте тестовую цель.

## Быстрый старт

```powershell
# Из чистого checkout ветки main:
Copy-Item scripts/deploy/targets.psd1 scripts/deploy/targets.local.psd1
# Заполните targets.local.psd1 локальными параметрами, затем:
pwsh scripts/deploy/deploy.ps1 -Target prod
```

Скрипт сам добавит `E:\Git\usr\bin` (ssh/scp) в конец `PATH`, чтобы не
затронуть `tar.exe` из `C:\Windows\System32`.

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

Используйте параметры из `targets.local.psd1` для подключения к серверу и
восстанавливайте только проверенный архив бэкапа. После восстановления
проверьте health endpoint.

## SSH-ключ и алиасы

Путь к ключу задаётся локально в `scripts/deploy/targets.local.psd1` как
`<path-to-ssh-key>` и при необходимости переопределяется флагом `-KeyPath`.
Не добавляйте рабочие подключения или ключи в отслеживаемые файлы.

## Playwright

Для запуска e2e-тестов нужно явно задать все переменные окружения:

```powershell
$env:PLAYWRIGHT_BASE_URL = 'https://example.invalid/<panel-base-path>/'
$env:PLAYWRIGHT_AUTH_USER = '<test-user>'
$env:PLAYWRIGHT_AUTH_PASS = '<test-password>'
```

Конфигурация Playwright не использует значения по умолчанию: отсутствие любой
из этих переменных завершает запуск с понятной ошибкой.
