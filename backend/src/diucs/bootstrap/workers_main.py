"""Process entry for the inbound queue workers (I08): `python -m diucs.bootstrap.workers_main`.

It is in bootstrap, the one layer that may name both an inbound worker and the outbound adapters.
It builds the Neo4j connection and the units of work from the container, the cache from Redis and
the bus client from Service Bus, wires `HandleInboundText` with the use cases it calls, and runs one
`ServiceBusRunner` for each inbound queue until it is told to stop: `inbound.replies` (the reply
processor) and `inbound.receipts` (the delivery tracker). Nothing here holds a rule.

The tenants it serves come from `DIUCS_WORKER_TENANTS`, a comma-separated list of tenant ids. That
is a stand-in for the tenant directory (TEN-007): the consumers take any `ActiveTenants`, so
`container.tenants` replaces `configured_tenants` in `main` and nothing else changes. A message for
a tenant that is not in the list is dead-lettered, never processed. A missing or malformed list, or
no Service Bus connection, stops the process before it opens a connection (fail closed). Messages
say which setting is wrong and never repeat a value.
"""

import asyncio
import contextlib
import os
import signal
from collections.abc import Awaitable, Callable, Mapping, Sequence

from azure.servicebus.aio import ServiceBusClient
from opentelemetry import trace as otel_trace

from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants, StaticTenants
from diucs.adapters.inbound.workers.reply_processor import HandlesInboundText, reply_consumer
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.telemetry.attributes import INSTRUMENTATION_NAME
from diucs.adapters.outbound.telemetry.consumer import consumer_observer
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import is_valid_tenant_id
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.handle_inbound_text import HandleInboundText
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.telemetry import start_telemetry

TENANTS_VARIABLE = "DIUCS_WORKER_TENANTS"
TENANTS_MISSING = (
    f"{TENANTS_VARIABLE} must list the tenants to serve, as comma-separated tenant ids"
)
TENANT_NOT_VALID = f"{TENANTS_VARIABLE} holds an entry that is not a valid tenant id"
SERVICE_BUS_MISSING = "DIUCS_SERVICEBUS_CONNECTION must be set for the queue workers"
REPLIES_QUEUE = "inbound.replies"
RECEIPTS_QUEUE = "inbound.receipts"


class WorkersConfigError(Exception):
    """The workers cannot start with this configuration. The text is fixed and holds no value."""


def configured_tenants(environ: Mapping[str, str]) -> StaticTenants:
    ids = [part.strip() for part in environ.get(TENANTS_VARIABLE, "").split(",")]
    ids = [tenant_id for tenant_id in ids if tenant_id]
    if not ids:
        raise WorkersConfigError(TENANTS_MISSING)
    if not all(is_valid_tenant_id(tenant_id) for tenant_id in ids):
        raise WorkersConfigError(TENANT_NOT_VALID)
    return StaticTenants(ids)


def service_bus_connection(settings: Settings) -> str:
    secret = settings.servicebus_connection
    if secret is None:
        raise WorkersConfigError(SERVICE_BUS_MISSING)
    return secret.get_secret_value()


def build_runners(
    client: ServiceBusClient,
    handle_inbound_text: HandlesInboundText,
    uow_factory: UnitOfWorkFactory,
    tenants: ActiveTenants,
) -> list[ServiceBusRunner]:
    """One runner for each inbound queue, each over a consumer that binds the message's tenant and
    handles the message under its trace span (O01)."""
    observe = consumer_observer(otel_trace.get_tracer(INSTRUMENTATION_NAME))
    return [
        ServiceBusRunner(
            client,
            REPLIES_QUEUE,
            None,
            reply_consumer(handle_inbound_text, uow_factory, tenants, observe),
        ),
        ServiceBusRunner(
            client,
            RECEIPTS_QUEUE,
            None,
            receipt_consumer(uow_factory, tenants, observe),
        ),
    ]


async def run_workers(
    loops: Sequence[Callable[[asyncio.Event], Awaitable[None]]], stop: asyncio.Event
) -> None:
    """Run every loop (a runner's `serve`) until `stop` is set."""
    await asyncio.gather(*(loop(stop) for loop in loops))


async def serve(settings: Settings, tenants: ActiveTenants, stop: asyncio.Event) -> None:
    """Open every connection, run the workers until `stop` is set, and close them again."""
    connection = service_bus_connection(settings)
    container = build(settings)
    await container.startup()  # refuses to start when Neo4j cannot be reached
    cache = RedisCache.from_url(settings.redis_url)
    client = ServiceBusClient.from_connection_string(connection)
    try:
        store = DriverIdempotencyStore(container.neo4j.driver)
        use_case = HandleInboundText(
            container.uow_factory,
            container.clock,
            container.ids,
            store,
            cache,
            ReportCapacity(container.uow_factory, container.clock, container.ids, store),
            ConfirmCapacity(container.uow_factory, container.clock, container.ids, store),
        )
        runners = build_runners(client, use_case, container.uow_factory, tenants)
        await run_workers([runner.serve for runner in runners], stop)
    finally:
        await client.close()
        await cache.aclose()
        await container.shutdown()


async def _run(settings: Settings, tenants: ActiveTenants) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on every platform
            loop.add_signal_handler(name, stop.set)
    provider = start_telemetry(settings)  # O01: nothing is exported without an OTLP endpoint
    try:
        await serve(settings, tenants, stop)
    finally:
        if provider is not None:
            provider.shutdown()  # flushes the last batch of spans


def main() -> None:
    try:
        settings = Settings()
        tenants = configured_tenants(os.environ)
        service_bus_connection(settings)
    except WorkersConfigError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run(settings, tenants))


if __name__ == "__main__":
    main()
