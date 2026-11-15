# Проверка установщика на vm3

Этот runbook предназначен только для тестовой машины `vm3`. `prod` запрещён. Все команды ниже выполняются оператором на рабочей станции из корня репозитория; перед фактическим прогоном сверяйте параметры только в локальном, игнорируемом `scripts/deploy/targets.local.psd1` (его содержимое не копируйте в отчёт).

## До начала

1. Создайте снимок ВМ vm3 и проверьте, что есть независимая копия `admin.db`, `metrics.db` (если используется), `/etc/sub-manager/runtime-secrets.env` и `/opt/sub-manager/.encryption_key`. Убедитесь, что можно вернуть снимок без обращения к prod.
2. Проверьте доступность ключа SSH, pinned `known_hosts`, свободное место (не менее 3 GiB) и окно обслуживания. Не используйте `targets.local.psd1` в архиве, не меняйте DNS или firewall prod и не запускайте команды с `-Target prod`.
3. Подготовьте локальный файл ответов по образцу `scripts/installer/windows/install-answers.example.txt`. Не записывайте секреты в Git.
4. Зафиксируйте исходное состояние vm3: `systemctl is-active sub-manager`, `systemctl cat sub-manager`, `journalctl -u sub-manager -n 100 --no-pager`.

## Общие правила наблюдения

После каждого изменения проверяйте:

```sh
sudo systemctl is-active sub-manager
curl -fsS http://127.0.0.1:666/health
sudo journalctl -u sub-manager --since "10 min ago" --no-pager
```

В журнале не должно быть нового traceback, циклических рестартов или ошибок миграции. Если сервис не healthy, остановите дальнейшие шаги и сохраните журнал.

## Сценарии

### 1. Предварительный dry-run deploy

```powershell
pwsh scripts/deploy/deploy.ps1 -Target vm3 -DryRun
```

Ожидается успешный preflight/read-only pre-check без вызова `invoke-remote-deploy.ps1`. Откат не требуется. Проверьте вывод и журнал только для подтверждения текущего состояния.

### 2. Чистая установка с install-answers

Перед запуском убедитесь, что снимок создан и старый сервис удалён согласно сценарию 5 либо это новая ВМ.

```powershell
pwsh scripts/installer/windows/windows-install.ps1 `
  -HostName '<vm3-host>' -UserName '<user>' -Port <ssh-port> -KeyPath '<key>' `
  -AnswersFile '.\scripts\installer\windows\install-answers.example.txt' `
  -RemoteDir '/opt/multiserversubgen-remote'
```

Ожидается успешная установка, активный `sub-manager`, HTTP 200 `/health`, созданный systemd unit и запись install log. При сбое не повторяйте установку поверх частичного состояния: верните снимок либо выполните безопасное удаление после сохранения журнала. Проверьте `journalctl -u sub-manager -b --no-pager`.

### 3. Update поверх установки

Канонический полный update запускается через deploy wrapper:

```powershell
pwsh scripts/deploy/deploy.ps1 -Target vm3
```

Для проверки Windows transport без deploy preflight:

```powershell
pwsh scripts/installer/windows/windows-update.ps1 `
  -HostName '<vm3-host>' -UserName '<user>' -Port <ssh-port> -KeyPath '<key>' -UpdateChoice 1
```

Ожидается созданный `/var/backups/sub-manager_deploy/*.tgz`, успешный health и активный сервис. При ошибке deploy должен сохранить предыдущий release; проверьте `journalctl -u sub-manager --since "15 min ago" --no-pager`, наличие backup и `systemctl status sub-manager`.

### 4. Имитация сбоя health и проверка auto-rollback

Ожидаемый контракт: staged deploy не заменяет рабочий release, если health не становится 200; при `ROLLBACK_ON_FAIL=1` предыдущий release и unit восстанавливаются. Проверка должна проводиться только контролируемым способом на vm3 (например, отдельным тестовым commit, который гарантированно не стартует).

В текущем проекте нет флага или harness для безопасной инъекции health-сбоя через `deploy.ps1`/`windows-update.ps1`. Не выключайте сеть, не удаляйте unit и не редактируйте production-like секреты для имитации. Зафиксируйте этот пробел и ограничьтесь проверкой кода rollback-контракта и уже произошедшего естественного сбоя:

```powershell
pwsh scripts/deploy/deploy.ps1 -Target vm3
```

Ожидается либо успешный deploy, либо сообщение о rollback с прежним commit и HTTP 200 после восстановления. Проверьте `journalctl -u sub-manager --since "20 min ago" --no-pager`, `systemctl show sub-manager -p ExecMainStatus -p Result` и последний `.tgz`.

### 5. Remove (soft, keep-db)

Сначала сохраните журнал и имя backup. Команда требует интерактивного `yes`:

```powershell
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -p <ssh-port> <user>@<vm3-host> `
  "sudo REMOVE_MODE=keep-db REMOVE_SCOPE=soft bash /opt/sub-manager/scripts/installer/remove.sh"
```

Ожидается остановленный и disabled `sub-manager`, удалённые unit и runtime secrets, сохранённый `/var/backups/sub-manager_remove_<timestamp>/admin.db`, отсутствие `/opt/sub-manager`. Откат — восстановить снимок или выполнить повторную установку; перед этим проверьте `journalctl -u sub-manager -b --no-pager` и журнал удаления.

### 6. Повторная установка

```powershell
pwsh scripts/installer/windows/windows-install.ps1 `
  -HostName '<vm3-host>' -UserName '<user>' -Port <ssh-port> -KeyPath '<key>' `
  -AnswersFile '.\scripts\installer\windows\install-answers.example.txt'
```

Ожидается чистый install log, активный unit и HTTP 200. Если нужна проверка восстановления данных, сначала остановите сервис и восстановите только копию БД во временное место; live-файлы заменяйте лишь после проверки снимка и backup.

### 7. Права на секреты и runtime-файлы

```sh
sudo stat -c '%a %U:%G %n' /opt/sub-manager/.encryption_key /etc/sub-manager/runtime-secrets.env
sudo test "$(stat -c '%a' /opt/sub-manager/.encryption_key)" = 600
sudo test "$(stat -c '%a' /etc/sub-manager/runtime-secrets.env)" = 600
sudo systemctl cat sub-manager | grep -F 'EnvironmentFile=/etc/sub-manager/runtime-secrets.env'
```

Ожидается mode 600, root-владелец для secrets и загрузка `EnvironmentFile`. Секреты не выводите через `cat`; при нарушении прав остановите сервис, восстановите права и проверьте журнал.

### 8. Проверка systemd unit

```sh
sudo systemd-analyze verify /etc/systemd/system/sub-manager.service
sudo systemd-analyze security sub-manager.service
sudo systemctl daemon-reload
sudo systemctl is-enabled sub-manager
```

Ожидается отсутствие ошибок verify, unit enabled, а security-анализ не ухудшился относительно baseline снимка. Откат — восстановить unit из deploy backup/снимка, затем `daemon-reload`; проверьте `journalctl -u sub-manager -n 100 --no-pager`.

### 9. Backup и restore-check

Найдите самый свежий deploy backup и проверьте его целостность:

```sh
sudo find /var/backups/sub-manager_deploy -maxdepth 1 -type f -name '*.tgz' -printf '%T@ %p\n' | sort -nr | head -1
sudo sha256sum -c /var/backups/sub-manager_deploy/project_<stamp>.tgz.sha256
sudo tar -tzf /var/backups/sub-manager_deploy/project_<stamp>.tgz >/dev/null
```

`sqlite-restore-check.py` принимает SQLite-файл, а не deploy tarball. Извлеките `admin.db` во временный каталог без записи в live directory и запустите проверку:

```sh
tmpdir="$(mktemp -d)"
sudo tar -xzf /var/backups/sub-manager_deploy/project_<stamp>.tgz -C "$tmpdir"
sudo python3 /opt/sub-manager/scripts/deploy/sqlite-restore-check.py "$tmpdir/sub-manager/admin.db"
rm -rf "$tmpdir"
```

Ожидается integrity/restore success и удаление временного каталога. При сбое сохраните backup, вывод команды и журнал; live БД не заменяйте.

## Обёртка для последовательного прогона

По умолчанию только печатает команды и не подключается к серверу:

```powershell
pwsh scripts/installer/windows/vm3-scenarios.ps1
```

Для фактического прогона явно укажите `-Execute`, `-HostName` и параметры доступа. Скрипт жёстко отказывает для любого Target, кроме `vm3`:

```powershell
pwsh scripts/installer/windows/vm3-scenarios.ps1 -Target vm3 -Execute `
  -HostName '<vm3-host>' -UserName '<user>' -Port <ssh-port> -KeyPath '<key>'
```

Сценарий health-failure остаётся ручной контрольной точкой (см. пробелы).

## Пробелы

- Нет поддерживаемого переключателя для инъекции неуспешного health и автоматического запуска rollback-теста; нужен отдельный безопасный test harness.
- `sqlite-restore-check.py` проверяет отдельный SQLite-файл, поэтому deploy tarball сначала извлекается во временный каталог вручную.
- `remove.sh` интерактивен и не имеет dry-run; обёртка печатает команду, но не симулирует удаление.
