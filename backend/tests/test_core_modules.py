"""Tests for the core modular infrastructure.

Covers: EventBus, Container, ModuleRegistry, JobQueue, FeatureFlags,
BaseModule lifecycle.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.base_module import BaseModule, HealthState, HealthStatus
from core.container import Container, ContainerError
from core.event_bus import EventBus
from core.feature_flags import FeatureFlags
from core.job_queue import JobQueue, _cron_to_interval
from core.module_registry import ModuleRegistry, RegistryError


# ---------------------------------------------------------------------------
# Helpers – minimal concrete module for testing
# ---------------------------------------------------------------------------

class _DummyModule(BaseModule):
    name = "dummy"
    dependencies = []

    def __init__(self, *, fail_start: bool = False) -> None:
        super().__init__()
        self.initialized = False
        self.started = False
        self.stopped = False
        self._fail_start = fail_start

    async def initialize(self, container: Container) -> None:
        self.initialized = True

    async def start(self) -> None:
        if self._fail_start:
            raise RuntimeError("Simulated start failure")
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def health_check(self) -> HealthStatus:
        return HealthStatus(state=HealthState.HEALTHY, message="ok")


class _DependentModule(BaseModule):
    name = "dependent"
    dependencies = ["dummy"]

    async def initialize(self, container: Container) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def health_check(self) -> HealthStatus:
        return HealthStatus(state=HealthState.HEALTHY)


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class TestEventBus:
    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []

        async def handler(data):
            received.append(data)

        bus.subscribe("test.event", handler)
        asyncio.get_event_loop().run_until_complete(
            bus.emit("test.event", {"key": "value"})
        )
        assert received == [{"key": "value"}]

    def test_multiple_handlers(self):
        bus = EventBus()
        log = []

        async def h1(data):
            log.append("h1")

        async def h2(data):
            log.append("h2")

        bus.subscribe("ev", h1)
        bus.subscribe("ev", h2)
        asyncio.get_event_loop().run_until_complete(bus.emit("ev"))
        assert log == ["h1", "h2"]

    def test_wildcard_handler(self):
        bus = EventBus()
        log = []

        async def catch_all(data):
            log.append("all")

        bus.subscribe("*", catch_all)
        asyncio.get_event_loop().run_until_complete(bus.emit("any.event"))
        assert log == ["all"]

    def test_unsubscribe(self):
        bus = EventBus()
        log = []

        async def handler(data):
            log.append("called")

        bus.subscribe("ev", handler)
        bus.unsubscribe("ev", handler)
        asyncio.get_event_loop().run_until_complete(bus.emit("ev"))
        assert log == []

    def test_sync_handler_called(self):
        bus = EventBus()
        log = []

        def sync_handler(data):
            log.append(data)

        bus.subscribe("ev", sync_handler)
        asyncio.get_event_loop().run_until_complete(bus.emit("ev", {"x": 1}))
        assert log == [{"x": 1}]

    def test_handler_exception_does_not_propagate(self):
        bus = EventBus()

        async def bad_handler(data):
            raise ValueError("boom")

        bus.subscribe("ev", bad_handler)
        # Should not raise
        asyncio.get_event_loop().run_until_complete(bus.emit("ev"))

    def test_all_events(self):
        bus = EventBus()
        bus.subscribe("a", lambda d: None)
        bus.subscribe("b", lambda d: None)
        assert set(bus.all_events()) == {"a", "b"}

    def test_no_duplicate_subscription(self):
        bus = EventBus()

        async def h(data):
            pass

        bus.subscribe("ev", h)
        bus.subscribe("ev", h)  # duplicate
        assert len(bus.listeners("ev")) == 1


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------

class TestContainer:
    def test_register_and_resolve_singleton(self):
        c = Container()
        c.register("svc", lambda: object(), singleton=True)
        a = c.resolve("svc")
        b = c.resolve("svc")
        assert a is b

    def test_register_and_resolve_factory(self):
        c = Container()
        c.register("svc", lambda: object(), singleton=False)
        a = c.resolve("svc")
        b = c.resolve("svc")
        assert a is not b

    def test_register_instance(self):
        c = Container()
        obj = object()
        c.register_instance("x", obj)
        assert c.resolve("x") is obj

    def test_resolve_unknown_raises(self):
        c = Container()
        with pytest.raises(ContainerError):
            c.resolve("missing")

    def test_resolve_optional_returns_default(self):
        c = Container()
        assert c.resolve_optional("missing") is None
        assert c.resolve_optional("missing", default=42) == 42

    def test_reset_clears_everything(self):
        c = Container()
        c.register("x", lambda: 1)
        c.reset()
        assert not c.is_registered("x")

    def test_context_manager_resets(self):
        with Container() as c:
            c.register("x", lambda: 1)
            assert c.is_registered("x")
        # After __exit__ the container is reset
        assert not c.is_registered("x")


# ---------------------------------------------------------------------------
# ModuleRegistry
# ---------------------------------------------------------------------------

class TestModuleRegistry:
    def setup_method(self):
        self.container = Container()
        self.registry = ModuleRegistry(self.container)

    def test_register_module(self):
        mod = _DummyModule()
        self.registry.register(mod)
        assert self.registry.get("dummy") is mod

    def test_duplicate_registration_raises(self):
        self.registry.register(_DummyModule())
        with pytest.raises(RegistryError):
            self.registry.register(_DummyModule())

    def test_module_without_name_raises(self):
        class Unnamed(BaseModule):
            name = ""

            async def initialize(self, c): pass
            async def start(self): pass
            async def stop(self): pass
            async def health_check(self): return HealthStatus()

        with pytest.raises(RegistryError):
            self.registry.register(Unnamed())

    def test_start_all_calls_lifecycle(self):
        mod = _DummyModule()
        self.registry.register(mod)
        asyncio.get_event_loop().run_until_complete(self.registry.start_all())
        assert mod.initialized
        assert mod.started

    def test_stop_all_calls_stop(self):
        mod = _DummyModule()
        self.registry.register(mod)
        asyncio.get_event_loop().run_until_complete(self.registry.start_all())
        asyncio.get_event_loop().run_until_complete(self.registry.stop_all())
        assert mod.stopped

    def test_dependency_order(self):
        order = []

        class A(BaseModule):
            name = "a"
            dependencies = []

            async def initialize(self, c):
                order.append("a_init")

            async def start(self):
                order.append("a_start")

            async def stop(self): pass

            async def health_check(self): return HealthStatus()

        class B(BaseModule):
            name = "b"
            dependencies = ["a"]

            async def initialize(self, c):
                order.append("b_init")

            async def start(self):
                order.append("b_start")

            async def stop(self): pass

            async def health_check(self): return HealthStatus()

        self.registry.register(B())
        self.registry.register(A())
        asyncio.get_event_loop().run_until_complete(self.registry.start_all())
        assert order.index("a_init") < order.index("b_init")
        assert order.index("a_start") < order.index("b_start")

    def test_circular_dependency_raises(self):
        class X(BaseModule):
            name = "x"
            dependencies = ["y"]

            async def initialize(self, c): pass
            async def start(self): pass
            async def stop(self): pass
            async def health_check(self): return HealthStatus()

        class Y(BaseModule):
            name = "y"
            dependencies = ["x"]

            async def initialize(self, c): pass
            async def start(self): pass
            async def stop(self): pass
            async def health_check(self): return HealthStatus()

        self.registry.register(X())
        self.registry.register(Y())
        with pytest.raises(RegistryError):
            self.registry.enabled_modules()

    def test_health_check_all(self):
        self.registry.register(_DummyModule())
        asyncio.get_event_loop().run_until_complete(self.registry.start_all())
        results = asyncio.get_event_loop().run_until_complete(
            self.registry.health_check_all()
        )
        assert "dummy" in results
        assert results["dummy"]["state"] == "healthy"

    def test_disabled_module_not_started(self):
        mod = _DummyModule()
        mod.enabled = False
        self.registry.register(mod)
        asyncio.get_event_loop().run_until_complete(self.registry.start_all())
        assert not mod.started


# ---------------------------------------------------------------------------
# JobQueue
# ---------------------------------------------------------------------------

class TestJobQueue:
    def test_cron_to_interval_every_5_minutes(self):
        assert _cron_to_interval("*/5 * * * *") == 300.0

    def test_cron_to_interval_every_hour(self):
        assert _cron_to_interval("0 */1 * * *") == 3600.0

    def test_cron_to_interval_special_forms(self):
        assert _cron_to_interval("@hourly") == 3600.0
        assert _cron_to_interval("@daily") == 86400.0

    def test_schedule_decorator_registers_job(self):
        q = JobQueue()

        @q.schedule(cron="*/1 * * * *", name="my_job")
        async def my_job():
            pass

        names = [j.name for j in q._scheduled]
        assert "my_job" in names

    def test_task_decorator_adds_enqueue(self):
        q = JobQueue()

        @q.task(retry=2, timeout=5)
        async def my_task():
            pass

        assert hasattr(my_task, "enqueue")

    def test_run_with_retry_succeeds(self):
        q = JobQueue()
        calls = []

        async def failing_then_ok():
            calls.append(1)
            if len(calls) < 2:
                raise ValueError("first attempt fails")

        result = asyncio.get_event_loop().run_until_complete(
            q._run_with_retry(failing_then_ok, "test", retry=2, timeout=None)
        )
        assert len(calls) == 2

    def test_status_returns_list(self):
        q = JobQueue()

        @q.schedule(cron="*/1 * * * *", name="j1")
        async def j1(): pass

        statuses = q.status()
        assert any(s["name"] == "j1" for s in statuses)


# ---------------------------------------------------------------------------
# FeatureFlags
# ---------------------------------------------------------------------------

class TestFeatureFlags:
    def test_flag_disabled_by_default(self):
        flags = FeatureFlags()
        assert not flags.is_enabled("nonexistent_flag")

    def test_set_flag(self):
        flags = FeatureFlags()
        flags.set_flag("my_flag", enabled=True)
        assert flags.is_enabled("my_flag")

    def test_register_flag(self):
        flags = FeatureFlags()
        flags.register_flag("my_flag", enabled=True)
        assert flags.is_enabled("my_flag")

    def test_register_flag_does_not_overwrite(self):
        flags = FeatureFlags()
        flags.set_flag("my_flag", enabled=True)
        flags.register_flag("my_flag", enabled=False)  # should not overwrite
        assert flags.is_enabled("my_flag")

    def test_is_enabled_for_user_global_flag(self):
        flags = FeatureFlags()
        flags.set_flag("feat", enabled=True)
        assert flags.is_enabled_for_user("feat", user_id=1)

    def test_is_enabled_for_user_in_list(self):
        flags = FeatureFlags()
        flags.load_from_dict({
            "flags": {
                "beta": {
                    "enabled": True,
                    "rollout_percentage": 0,
                    "enabled_users": [42],
                }
            }
        })
        assert flags.is_enabled_for_user("beta", user_id=42)
        assert not flags.is_enabled_for_user("beta", user_id=99)

    def test_load_from_dict(self):
        flags = FeatureFlags()
        flags.load_from_dict({
            "flags": {
                "feature_a": {"enabled": True},
                "feature_b": {"enabled": False},
            }
        })
        assert flags.is_enabled("feature_a")
        assert not flags.is_enabled("feature_b")

    def test_all_flags(self):
        flags = FeatureFlags()
        flags.set_flag("x", enabled=True)
        flags.set_flag("y", enabled=False)
        names = [f["name"] for f in flags.all_flags()]
        assert "x" in names
        assert "y" in names
