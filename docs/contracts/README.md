# Контракты 3X-UI

`backend/integrations/xui/openapi/3x-ui-3.x.openapi.json` — закреплённый
OpenAPI-источник для панели 3X-UI `3.x`. Он скопирован из предоставленного
оператором документа без изменения содержимого; его SHA-256 зафиксирован в
`backend/integrations/xui/contract_catalog.py`.

Политика простая:

- v3 — default для каждой новой операции;
- все 170 операций upstream имеют явный статус в генерируемой matrix;
- `implemented` означает, что путь входит в зарегистрированный control-plane
  surface и проверяется против pinned спецификации;
- `out_of_scope` не является неявной поддержкой: он требует отдельного
  продуктового решения и теста перед добавлением;
- v2 не выводится из версии панели или одиночного `404/405`; его маршруты и
  причины перечислены в `3x-ui-v2-legacy-manifest.json`;
- опасная v3 write-операция после отправки не может быть повторена через v2.

Проверить источник и registries:

```powershell
python -m integrations.xui.contract_catalog
```

Вывести машиночитаемую matrix всех 170 операций:

```powershell
python -m integrations.xui.contract_catalog --matrix
```

Для import из repo-root задайте `PYTHONPATH=backend`, либо запускайте команды
из `backend/`. Автотест `backend/tests/test_xui_openapi_contract.py` выполняет
эти проверки в CI.
