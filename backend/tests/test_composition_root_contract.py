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
