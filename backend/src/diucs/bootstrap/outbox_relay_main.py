"""Process entry for the outbox relay (I03): `python -m diucs.bootstrap.outbox_relay_main`.

It is in bootstrap, the one layer that may name both an inbound worker and the outbound adapters
(the layers contract forbids the worker importing them). It builds the Neo4j connection and the
units of work from the container, the cache from Redis and the bus from Service Bus, and hands them
to `OutboxRelay`. Nothing here holds a rule.

The tenants it serves are the active tenants of the container's tenant directory (TEN-007): the
platform's own record, read on the global path, so a tenant that is suspended or not yet active is
not relayed. The list of tenant ids in the environment that stood in for it is gone. Start-up
applies the migrations and makes sure the audit head exists, and stops the process if either
fails (DEC-012). A missing Service Bus connection stops it before anything opens (fail closed);
messages say which setting is wrong and never repeat a value.
"""

import asyncio
import contextlib
import signal

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.outbox_relay import OutboxRelay
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings

SERVICE_BUS_MISSING = "DIUCS_SERVICEBUS_CONNECTION must be set for the outbox relay"


class RelayConfigError(Exception):
    """The relay cannot start with this configuration. The text is fixed and holds no value."""


def service_bus_connection(settings: Settings) -> str:
    secret = settings.servicebus_connection
    if secret is None:
        raise RelayConfigError(SERVICE_BUS_MISSING)
    return secret.get_secret_value()


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    """Open every connection, relay until `stop` is set, and close them in the other order."""
    connection = service_bus_connection(settings)
    container = build(settings)
    try:
        await container.startup()  # refuses to start when Neo4j cannot be reached or migrated
        cache = RedisCache.from_url(settings.redis_url)
        client = ServiceBusClient.from_connection_string(connection)
        bus = ServiceBusEventBus(client)
        try:
            relay = OutboxRelay(
                container.uow_factory, bus, cache, container.clock, container.tenants
            )
            await relay.run_forever(stop)
        finally:
            await bus.close()
            await client.close()
            await cache.aclose()
    finally:
        await container.shutdown()


async def _run(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on every platform
            loop.add_signal_handler(name, stop.set)
    await serve(settings, stop)


def main() -> None:
    try:
        settings = Settings()
        service_bus_connection(settings)
    except RelayConfigError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
