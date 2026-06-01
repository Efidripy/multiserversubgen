# Code Cleanup Plan - 2026-05-31

Цель: системно вычистить мусор, hardcoded UI-текст, молчаливые ошибки и рискованные места без больших переписываний и без потери текущей стабильности.

## Текущая база

- Backend lint: `ruff` чистый.
- Backend tests: `157 passed`.
- Frontend lint/build: чистые.
- Frontend dependency audit: `0 vulnerabilities`.
- Backend dependency audit: `No known vulnerabilities found`.
- Backend security scan: `bandit` без medium/high issues.
- i18n hardcoded baseline: `773`, текущие findings: `765`.
- Broad `except Exception` вне тестов: около 40 мест.
- Frontend debug logging: есть production `console.log` в init/performance/SW/WS helpers.

## Принципы работы

1. Малые итерации: один класс долга за проход.
2. После каждого прохода: `ruff`, backend tests, frontend lint/build по затронутой зоне.
3. Не переписывать архитектуру ради красоты.
4. Не удалять legacy fallback без тестов или явного решения.
5. Любой security false positive должен иметь кодовую причину: allowlist, параметризация или отдельный helper.

## P0 - не оставлять явные дыры

- WebSocket credentials не должны попадать в URL/query string.
- Dependency audit должен оставаться чистым для medium/high.
- Backend `bandit -ll` должен оставаться без findings.
- Новые hardcoded UI strings должны блокироваться i18n gate.

Критерий готовности:
- `npm audit --audit-level=moderate`
- `python -m pip_audit -r backend/requirements.txt`
- `python -m bandit -r backend -x backend/tests -ll`

## P1 - убрать основной мусор

1. Frontend production logs
   - заменить `console.log` на dev-only logger;
   - оставить `console.warn/error` только для реальных ошибок;
   - убрать тестовые UI-only логи из production paths.

2. i18n hardcoded text
   - выгрузить top files по количеству findings;
   - идти по компонентам, начиная с admin/user-facing экранов;
   - добавлять ключи сразу в `en.json` и `ru.json`;
   - снижать baseline count итерациями.

3. Backend broad exceptions
   - заменить `pass/continue` на typed exceptions там, где понятно;
   - добавить warning/debug logs для non-critical fallbacks;
   - оставить intentional fallback только с коротким объяснением.

4. Dynamic SQL cleanup
   - вынести allowlisted update fields в helper;
   - сохранить параметризацию значений;
   - убрать необходимость `# nosec` там, где разумно.

Критерий готовности:
- i18n findings меньше текущих `765`;
- нет production `console.log` в `frontend/src`;
- broad exception count снижен и оставшиеся объяснены.

## P2 - консистентность и поддерживаемость

- Удалить устаревшие дубли и неиспользуемые compatibility paths после проверки.
- Выровнять имена `user/username`, node service/router boundaries.
- Документировать security invariants: auth, TOTP, node secret handling, WebSocket auth flow.
- Добавить focused tests на helpers, где будет рефакторинг.

## Рабочий порядок

1. Снять карту долга и сохранить план.
2. Закрыть frontend production logs.
3. Сгенерировать i18n debt report по файлам.
4. Чистить i18n top files партиями.
5. Чистить backend broad exceptions партиями.
6. Укрепить dynamic SQL helpers.
7. Финальный audit/test/build.

