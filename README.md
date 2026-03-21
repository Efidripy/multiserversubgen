# Multi-Server Subscription Manager

Современная панель управления multi-node инфраструктурой (FastAPI + React/Vite) с поддержкой subpath-деплоя, мониторинга и batch-операций.

## Что это

`multiserversubgen` — это проект для управления несколькими node-panel серверами в едином интерфейсе:

- управление узлами
- inbounds и clients
- статистика трафика
- backup/restore
- observability и monitoring-интеграции

## Быстрый старт: установка

```bash
git clone https://github.com/Efidripy/multiserversubgen
cd multiserversubgen
chmod +x install.sh
sudo ./install.sh
```

После установки проверьте:

```bash
systemctl is-active sub-manager
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:666/health
```

## Быстрый старт: обновление

```bash
cd multiserversubgen
git pull
sudo ./update.sh
```

Перед обновлением рекомендуется сделать backup через API.

## Документация

### Основное

- [Установка (подробно)](./docs/INSTALL.md)
- [Обновление (подробно)](./docs/UPDATE.md)
- [Ops / Эксплуатация](./docs/OPS.md)
- [API (входная точка)](./docs/API.md)

### Дополнительно

- [Полная API-документация](./docs/API_DOCUMENTATION.md)
- [Гайд по компонентам](./docs/COMPONENTS_GUIDE.md)
- [Гайд по подпискам](./docs/SUBSCRIPTION_GUIDE.md)
- [Снимки интерфейса](./screens.md)
- [Текущий статус улучшений](./docs/IMPROVEMENTS.md)
- Индекс знаний проекта: `./KNOWLEDGE_INDEX.md` (локальный файл, не публикуется в Git)

## Лицензия

MIT
