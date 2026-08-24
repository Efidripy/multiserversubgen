from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_api_reference_lists_live_read_projections() -> None:
    docs = (REPO / "docs" / "API_DOCUMENTATION.md").read_text(encoding="utf-8")

    for route in (
        "GET /api/v1/clients/paged",
        "GET /api/v1/inbounds/slim",
        "GET /api/v1/inbounds/options",
        "GET /api/v1/traffic/stats-by-period",
    ):
        assert route in docs

    assert "production control-plane contract" in docs
    assert "переключение периода в UI не запускает fleet fan-out" in docs


def test_subscription_guide_matches_stable_token_contract() -> None:
    guide = (REPO / "docs" / "SUBSCRIPTION_GUIDE.md").read_text(encoding="utf-8")

    assert "302" in guide
    assert "30 запросов за 60 секунд" in guide
    assert "grouped subscription response cache: 300 секунд" in guide
    assert "Старые ссылки с raw email/identifier и ранее выданные HMAC-ссылки поддерживаются" in guide
    assert "Authorization: Bearer $ADMIN_API_TOKEN" not in guide
    assert "Старые ссылки с raw email/identifier больше не совместимы" not in guide
    assert "100% обратная совместимость с v3.0" not in guide
    assert "Старые ссылки работают без изменений" not in guide
    assert "Новым клиентам выдаются только новые token URL" in guide
