"""The process entry of the outbox relay (I03, TEN-007): configuration that fails closed, with fixed
messages that never hold a value from the environment, and the tenants it serves, which are the
tenant directory of the container and not a list in the environment (DEC-157 item 13, replaced)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from diucs.bootstrap import outbox_relay_main
from diucs.bootstrap.outbox_relay_main import RelayConfigError, service_bus_connection
from diucs.bootstrap.settings import Settings

CONNECTION = "Endpoint=sb://example;SharedAccessKeyName=k;SharedAccessKey=SECRET-KEY-TEXT"


def test_the_service_bus_connection_is_the_setting() -> None:
    settings = Settings(servicebus_connection=SecretStr(CONNECTION))

    assert service_bus_connection(settings) == CONNECTION


def test_no_service_bus_connection_is_refused() -> None:
    with pytest.raises(RelayConfigError, match="DIUCS_SERVICEBUS_CONNECTION"):
        service_bus_connection(Settings(servicebus_connection=None))


def test_the_list_of_tenants_in_the_environment_is_gone() -> None:
    source = Path(outbox_relay_main.__file__).read_text(encoding="utf-8")

    assert "DIUCS_RELAY_TENANTS" not in source
    assert not hasattr(outbox_relay_main, "configured_tenants")
    assert not hasattr(outbox_relay_main, "TENANTS_VARIABLE")
    assert "StaticTenants" not in source


def test_main_stops_with_the_fixed_message_when_there_is_no_service_bus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_SERVICEBUS_CONNECTION", raising=False)

    with pytest.raises(SystemExit) as raised:
        outbox_relay_main.main()

    assert "DIUCS_SERVICEBUS_CONNECTION" in str(raised.value)


def test_main_does_not_ask_for_a_list_of_tenants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", CONNECTION)
    monkeypatch.delenv("DIUCS_RELAY_TENANTS", raising=False)
    started: list[Settings] = []

    def fake_run(coroutine: Any) -> None:
        coroutine.close()
        started.append(Settings())

    monkeypatch.setattr(asyncio, "run", fake_run)

    outbox_relay_main.main()

    assert len(started) == 1


class _Closer:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    async def close(self) -> None:
        self._events.append(f"{self._name} closed")

    async def aclose(self) -> None:
        self._events.append(f"{self._name} closed")


async def test_the_relay_serves_the_tenants_of_the_containers_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    seen: dict[str, Any] = {}
    directory = object()

    class FakeContainer:
        tenants = directory
        uow_factory = object()
        clock = object()

        async def startup(self) -> None:
            events.append("startup")

        async def shutdown(self) -> None:
            events.append("shutdown")

    class FakeRelay:
        def __init__(self, uow_factory: Any, bus: Any, cache: Any, clock: Any, tenants: Any):
            seen["tenants"] = tenants
            seen["cache"] = cache

        async def run_forever(self, stop: asyncio.Event) -> None:
            events.append("relay ran")

    monkeypatch.setattr(outbox_relay_main, "build", lambda settings: FakeContainer())
    monkeypatch.setattr(outbox_relay_main, "OutboxRelay", FakeRelay)
    monkeypatch.setattr(
        outbox_relay_main.RedisCache, "from_url", lambda url: _Closer("cache", events)
    )
    monkeypatch.setattr(
        outbox_relay_main.ServiceBusClient,
        "from_connection_string",
        lambda text: _Closer("client", events),
    )
    monkeypatch.setattr(
        outbox_relay_main, "ServiceBusEventBus", lambda client: _Closer("bus", events)
    )
    settings = Settings(servicebus_connection=SecretStr(CONNECTION))

    await outbox_relay_main.serve(settings, asyncio.Event())

    assert seen["tenants"] is directory
    assert events == [
        "startup",
        "relay ran",
        "bus closed",
        "client closed",
        "cache closed",
        "shutdown",
    ]


async def test_a_failing_start_up_opens_nothing_else_and_leaves_no_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeContainer:
        tenants = object()

        async def startup(self) -> None:
            raise RuntimeError("migration failed")

        async def shutdown(self) -> None:
            events.append("shutdown")

    monkeypatch.setattr(outbox_relay_main, "build", lambda settings: FakeContainer())
    monkeypatch.setattr(
        outbox_relay_main.RedisCache, "from_url", lambda url: events.append("cache opened")
    )
    settings = Settings(servicebus_connection=SecretStr(CONNECTION))

    with pytest.raises(RuntimeError):
        await outbox_relay_main.serve(settings, asyncio.Event())

    assert events == ["shutdown"]
