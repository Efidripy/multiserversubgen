from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_main_is_the_only_declared_production_composition_root():
    main = (REPO / "backend/main.py").read_text(encoding="utf-8")
    adr = (REPO / "docs/ADR-0001-production-composition-root.md").read_text(
        encoding="utf-8"
    )

    assert "from core.lifespan import build_lifespan" in main
    assert "from core.router_registration import register_app_routers" in main
    assert "ModuleRegistry(" not in main
    assert "`backend/main.py` is the sole production composition root." in adr


def test_runtime_state_does_not_proxy_subscription_or_redis_ownership():
    main = (REPO / "backend/main.py").read_text(encoding="utf-8")
    runtime_state = (REPO / "backend/services/runtime_state.py").read_text(
        encoding="utf-8"
    )
    subscription_links = (REPO / "backend/services/subscription_links.py").read_text(
        encoding="utf-8"
    )
    runtime_support = (REPO / "backend/services/runtime_support.py").read_text(
        encoding="utf-8"
    )

    assert "from services.runtime_state import RuntimeState" in main
    assert "runtime_state = RuntimeState()" in main
    assert "build_runtime_state" not in main
    assert "runtime_state.emails_cache" not in main
    assert "runtime_state.links_cache" not in main
    assert "runtime_state.redis_client" not in main
    assert "emails_cache: Dict" not in runtime_state
    assert "links_cache: Dict" not in runtime_state
    assert "redis_client = None" not in runtime_state
    assert "def build_runtime_state" not in runtime_state

    assert "emails_cache =" in subscription_links
    assert "links_cache =" in subscription_links
    assert "class RedisJsonCache" in runtime_support
