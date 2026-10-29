"""The process entry of the outbox relay (I03): configuration that fails closed, with fixed messages
that never hold a value from the environment."""

import pytest
from pydantic import SecretStr

from diucs.bootstrap import outbox_relay_main
from diucs.bootstrap.outbox_relay_main import (
    RelayConfigError,
    configured_tenants,
    service_bus_connection,
)
from diucs.bootstrap.settings import Settings

CONNECTION = "Endpoint=sb://example;SharedAccessKeyName=k;SharedAccessKey=SECRET-KEY-TEXT"


async def test_the_configured_tenants_are_the_comma_separated_ids_in_order() -> None:
    tenants = configured_tenants({"DIUCS_RELAY_TENANTS": "tenant-a, tenant-b ,tenant-c"})

    assert list(await tenants.active_tenant_ids()) == ["tenant-a", "tenant-b", "tenant-c"]


@pytest.mark.parametrize("value", [None, "", " , ", "   "])
def test_no_configured_tenant_is_refused(value: str | None) -> None:
    environ = {} if value is None else {"DIUCS_RELAY_TENANTS": value}

    with pytest.raises(RelayConfigError, match="DIUCS_RELAY_TENANTS"):
        configured_tenants(environ)


@pytest.mark.parametrize("bad", ["Not A Tenant", "net-abcd1234", "q", "has:colon", "x" * 40])
def test_an_entry_that_is_not_a_tenant_id_is_refused_without_repeating_it(bad: str) -> None:
    with pytest.raises(RelayConfigError) as raised:
        configured_tenants({"DIUCS_RELAY_TENANTS": f"tenant-a,{bad}"})

    assert bad not in str(raised.value)


def test_the_service_bus_connection_is_the_setting() -> None:
    settings = Settings(servicebus_connection=SecretStr(CONNECTION))

    assert service_bus_connection(settings) == CONNECTION


def test_no_service_bus_connection_is_refused() -> None:
    with pytest.raises(RelayConfigError, match="DIUCS_SERVICEBUS_CONNECTION"):
        service_bus_connection(Settings(servicebus_connection=None))


def test_main_stops_with_the_fixed_message_when_the_tenants_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_RELAY_TENANTS", raising=False)

    with pytest.raises(SystemExit) as raised:
        outbox_relay_main.main()

    assert "DIUCS_RELAY_TENANTS" in str(raised.value)
