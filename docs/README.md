# Документация проекта

Этот каталог содержит только стабильную документацию, нужную пользователю,
оператору или интегратору после клонирования репозитория. Исключение —
минимальные технические ADR, которые закрепляют проверяемый composition-root
и Telegram provisioning contract.

## Начать работу

- [Установка](INSTALL.md)
- [Обновление](UPDATE.md)
- [Эксплуатация](OPS.md)
- [OBS-001: bounded request attribution](OPS.md#obs-001-bounded-request-attribution)
- [API: короткая точка входа](API.md)
- [API: полный справочник](API_DOCUMENTATION.md)
- [Подписки](SUBSCRIPTION_GUIDE.md)
- [Telegram: identity и provisioning authority](ADR-0002-telegram-identity-and-provisioning-authority.md)
- [Installer/updater: ownership внешних компонентов](ADR-0003-component-ownership.md)
- [Telegram: безопасность и staging rollout](TELEGRAM_BOT_SECURITY.md)
- [Telegram: staging runbook](TELEGRAM_STAGING_RUNBOOK.md)
- [Telegram: опциональный локальный VLESS transport](TELEGRAM_LOCAL_VLESS_TRANSPORT.md)

## Backend CI: pyright baseline

Backend CI checks pyright errors against `backend/.pyright-baseline.json`. After fixing errors, install the backend development requirements in a Python 3.12 environment and run from the repository root:

```sh
python scripts/ci/check-pyright-baseline.py --update-baseline -- npx --yes pyright@1.1.390
```

Review the baseline diff and include it with the fix. Use the same pinned pyright version as CI.
