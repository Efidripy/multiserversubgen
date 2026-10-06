# Обновление

## Рекомендуемый путь

```bash
cd multiserversubgen
git pull
sudo ./update.sh
```

Запускайте updater из полного Git checkout или из проверенного flat release
bundle. Скрипт до остановки сервиса проверяет обязательные backend, frontend,
ops, deploy, monitoring и systemd файлы. Неполный или произвольный архив он
отклоняет до изменения runtime-state.

## Режимы `update.sh`

1. Полное обновление (backend + frontend)
2. Только backend
3. Только frontend
4. Только nginx-конфиг

## Внешние компоненты на том же сервере

Обычный updater обновляет только Sub-Manager. Он не обновляет вручную
установленные Grafana, Prometheus, 3x-ui и другие уже существующие пакеты.
Для legacy-хоста без ownership registry обнаруженные Grafana/Prometheus
считаются `external`: updater не трогает их APT source, сервис или глобальные
конфиги.

Перед обновлением можно безопасно вывести отчёт:

```bash
sudo bash scripts/installer/component-ownership.sh report
```

Если оператор хочет передать существующие Grafana и Prometheus под управление
MSSG, это отдельное подтверждаемое действие. Оно меняет только registry, без
перезапуска и изменения конфигурации:

```bash
sudo bash scripts/installer/component-ownership.sh adopt grafana prometheus
```

Перед ручным обновлением компонента, установленного MSSG, снимите с него
управление MSSG:

```bash
sudo bash scripts/installer/component-ownership.sh release grafana prometheus
```

Полные правила и границы: [ADR-0003](./ADR-0003-component-ownership.md).

## Рекомендация перед обновлением

Сделайте backup перед применением обновления:

```bash
curl -u admin:password https://<your-domain>/<web-path>/api/v1/backup/all -o backups_$(date +%Y%m%d).zip
```

## Rollback в canonical deploy

В `scripts/deploy/server-deploy.sh` при включённом `ROLLBACK_ON_FAIL=1`
ошибка команды или провал health gate запускает восстановление предыдущего
runtime. Отсутствие staging-каталога или временного unit после swap считается
успешной очисткой. Ошибка удаления одного временного артефакта не мешает
попытке удалить второй и не блокирует переход к восстановлению; deploy
выводит предупреждение, а неудалённый артефакт остаётся для разбора оператором.
Обработчик ошибки команды сохраняет её исходный exit code при успешном
выполнении восстановления; провал health gate завершается с кодом `1`.
При `ROLLBACK_ON_FAIL=0` восстановление не запускается.

Rollback возвращает предыдущий каталог runtime вместе с его состоянием БД.
Это не универсальный безопасный restore после новых записей: восстановление
данных требует отдельной оценки. Проверка функций на временных fixtures
не подтверждает успешный откат на реальном хосте или исправность backup.

## Проверка после обновления

```bash
systemctl is-active sub-manager
APP_PORT="${APP_PORT:-666}"
curl -s -o /dev/null -w 'health=%{http_code}\n' "http://127.0.0.1:${APP_PORT}/health"
curl -fsSL -o /dev/null -w 'panel=%{http_code}\n' https://<your-domain>/<web-path>/
```

## Частый кейс: 404 на assets после обновления

Если панель открывается, но JS/CSS 404:

1. пересоберите frontend с корректным base path (`VITE_BASE`)
2. опубликуйте новый `backend/build`
3. проверьте nginx routes для `/<web-path>/assets/`
4. очистите кэш браузера / Service Worker

Подробности: [OPS.md](./OPS.md)
