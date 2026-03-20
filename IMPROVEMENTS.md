# Статус улучшений (источник правды)

Обновлено: 2026-03-20 (завершены шаги 1–11, e2e deploy to vm1 validated)

## ✅ Уже сделано (подтверждено по коду)

1. Backend gzip-сжатие включено (`GZipMiddleware` в `backend/main.py`).
2. WebSocket endpoint есть (`/ws` в `backend/routers/realtime.py`, подключается через `router_registration`).
3. Service Worker добавлен (`frontend/public/sw.js` + менеджер).
4. Performance monitoring добавлен (`frontend/src/services/performanceMonitoring.ts`).
5. Delta updates протокол добавлен (`frontend/src/services/deltaUpdates.ts`).
6. IndexedDB-кэш добавлен (`frontend/src/services/indexedDBManager.ts`).
7. Error boundary есть (в `frontend/src/main.tsx` используется `RootErrorBoundary`).
8. Статус узлов реализован (Online/Offline/Checking в `frontend/src/components/NodeManager.tsx`).
9. Test Connection реализован:
   - UI: кнопка в `NodeManager.tsx`
   - API: `/v1/nodes/check-connection`
10. Шифрование паролей узлов уже реализовано (Fernet в `backend/crypto.py`, применение в роутерах/сервисах).
11. Prometheus endpoint `/metrics` уже реализован (`backend/routers/observability.py`).
12. Python unit/smoke tests уже есть (`backend/tests/*.py`).
13. Real-time интеграция во фронтенд завершена:
   - `useTrafficStatsSubscription` подключен в `TrafficStats.tsx`, `ClientManager.tsx`, `MonitoringDashboard.tsx`.
14. WebSocket broadcasting на backend завершён:
   - отправка `server_status` / `traffic_update` / `client_update` из `backend/services/collector.py` (1 broadcast call ✓);
   - отправка `client_update`/`traffic_update` из мутаций `backend/routers/clients.py` (7 broadcast calls ✓).
15. Фронтенд сборка проходит (`npm run build`), i18n baseline обновлён (233).
16. Backend синтаксис/смоук проходят:
   - `python -m compileall backend`
   - `python -m pytest -q backend/tests/test_api_smoke.py backend/tests/test_security_hardening.py`.
17. **Deploy на vm1 успешен (2026-03-20 23:43 UTC):**
   - Все Python файлы развернуты в `/opt/sub-manager/` с корректной иерархией (core/, routers/, services/ как подпапки);
   - Frontend build (`backend/build/`) развёрнут и обслуживается;
   - Service статус: active ✓
   - Health endpoint: HTTP 200 ✓
   - API StatsByPeriod: HTTP 200 ✓
   - Panel доступен по пути `/27b3dl1c/`: HTTP 200 ✓
   - WebSocket endpoint регистрация: `@router.websocket("/ws")` найдена в коде ✓

## 🟡 Начато, но не доведено до полного завершения

1. WebSocket e2e тестирование:
   - Backend broadcasts код развернут и подтвержден (grep_search);
   - HTTP endpoint доступен;
   - WebSocket connection с клиента не тестирована (требует `websockets` lib на vm1 или browser WebSocket API);
   - **Путь вперёд**: использовать браузер для прямого подключения в DevTools, или установить websockets на vm1 и запустить Python e2e тест.

2. Деплой/путь панели:
   - рабочий путь сейчас `https://vm1.kleva.ru/27b3dl1c/` (200),
   - старый `.../unkau9du/` не активен (404), нужно не путать в runbook’ах.

## ⏳ Не начато

1. Docker containerization (`Dockerfile`, `docker-compose.yml`).
2. Telegram notifications.
3. Pre-commit hooks (`.pre-commit-config.yaml`).
4. Полное вычищение heredoc-генерации из `install.sh` в сторону 100% file-based шаблонов (частично структурировано, но не закрыто как задача).

## Ближайший порядок работ

1. **WebSocket полная e2e проверка** (рекомендуется):
   - Способ 1: Установить `websockets` на vm1 и запустить `test-ws-e2e-vm1.py` локально или на vm1;
   - Способ 2: Открыть браузер на `https://vm1.kleva.ru/27b3dl1c/`, перейти в Network (DevTools), и проверить что WS upgrade происходит;
   - Ожидаемо: WebSocket connection successful → subscribe message sent → broadcast messages received.

2. Обновить runbook'и под текущий `WEB_PATH` (`/27b3dl1c/`) и убрать старые ссылки из документации.

3. Решить по Docker/Telegram/pre-commit как следующей очереди задач.