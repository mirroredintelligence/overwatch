"""Process entry for the outbox relay (I03): `python -m diucs.bootstrap.outbox_relay_main`.

It is in bootstrap, the one layer that may name both an inbound worker and the outbound adapters
(the layers contract forbids the worker importing them). It builds the Neo4j connection and the
units of work from the container, the cache from Redis and the bus from Service Bus, and hands them
to `OutboxRelay`. Nothing here holds a rule.

The tenants it serves come from `DIUCS_RELAY_TENANTS`, a comma-separated list of tenant ids. That is
a stand-in for the tenant directory (TEN-007): the relay takes any `ActiveTenants`, so the
directory replaces `configured_tenants` here and nothing else changes. A missing or malformed list
stops the process before it opens a connection (fail closed). Messages say which setting is wrong
and never repeat a value.
"""

import asyncio
import contextlib
import os
import signal
from collections.abc import Mapping

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.outbox_relay import OutboxRelay, StaticTenants
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.application.tenancy import is_valid_tenant_id
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings

TENANTS_VARIABLE = "DIUCS_RELAY_TENANTS"
TENANTS_MISSING = (
    f"{TENANTS_VARIABLE} must list the tenants to relay, as comma-separated tenant ids"
)
TENANT_NOT_VALID = f"{TENANTS_VARIABLE} holds an entry that is not a valid tenant id"
SERVICE_BUS_MISSING = "DIUCS_SERVICEBUS_CONNECTION must be set for the outbox relay"


class RelayConfigError(Exception):
    """The relay cannot start with this configuration. The text is fixed and holds no value."""


def configured_tenants(environ: Mapping[str, str]) -> StaticTenants:
    ids = [part.strip() for part in environ.get(TENANTS_VARIABLE, "").split(",")]
    ids = [tenant_id for tenant_id in ids if tenant_id]
    if not ids:
        raise RelayConfigError(TENANTS_MISSING)
    if not all(is_valid_tenant_id(tenant_id) for tenant_id in ids):
        raise RelayConfigError(TENANT_NOT_VALID)
    return StaticTenants(ids)


def service_bus_connection(settings: Settings) -> str:
    secret = settings.servicebus_connection
    if secret is None:
        raise RelayConfigError(SERVICE_BUS_MISSING)
    return secret.get_secret_value()


async def serve(settings: Settings, tenants: StaticTenants, stop: asyncio.Event) -> None:
    """Open every connection, relay until `stop` is set, and close them in the other order."""
    connection = service_bus_connection(settings)
    container = build(settings)
    await container.startup()  # refuses to start when Neo4j cannot be reached
    cache = RedisCache.from_url(settings.redis_url)
    client = ServiceBusClient.from_connection_string(connection)
    bus = ServiceBusEventBus(client)
    try:
        relay = OutboxRelay(container.uow_factory, bus, cache, container.clock, tenants)
        await relay.run_forever(stop)
    finally:
        await bus.close()
        await client.close()
        await cache.aclose()
        await container.shutdown()


async def _run(settings: Settings, tenants: StaticTenants) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on every platform
            loop.add_signal_handler(name, stop.set)
    await serve(settings, tenants, stop)


def main() -> None:
    try:
        settings = Settings()
        tenants = configured_tenants(os.environ)
        service_bus_connection(settings)
    except RelayConfigError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run(settings, tenants))


if __name__ == "__main__":
    main()
