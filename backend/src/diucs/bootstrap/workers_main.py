"""Process entry for the inbound queue workers (I08): `python -m diucs.bootstrap.workers_main`.

It is in bootstrap, the one layer that may name both an inbound worker and the outbound adapters.
It builds the Neo4j connection and the units of work from the container, the cache from Redis and
the bus client from Service Bus, wires `HandleInboundText` with the use cases it calls, and runs one
`ServiceBusRunner` for each inbound queue until it is told to stop: `inbound.replies` (the reply
processor), `inbound.receipts` (the delivery tracker) and `scheduled.work` (the missed-report
ladder, I05), and the two sender runners of `messages.outbound` (I10). Nothing here holds a rule.

The tenants it serves are the active tenants of the container's tenant directory (TEN-007, TEN-025):
the platform's own record, read for each message by the consumer that binds the tenant, so a tenant
that is suspended or not yet active has its messages dead-lettered as `tenant-unknown`, never
processed. The list of tenant ids in the environment that stood in for the directory is gone. No
Service Bus connection stops the process before it opens a connection (fail closed). Messages say
which setting is wrong and never repeat a value.
"""

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

import httpx
from azure.servicebus.aio import ServiceBusClient
from opentelemetry import trace as otel_trace

from diucs.adapters.inbound.scheduler.scheduled_work_consumer import (
    WorkHandler,
    build_scheduled_work_consumer,
)
from diucs.adapters.inbound.workers.board_consumer import BoardRebuilder, board_runners
from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.message_senders import push_runner, sender_runners
from diucs.adapters.inbound.workers.network_board_consumer import (
    NetworkBoardRebuilder,
    network_board_runners,
)
from diucs.adapters.inbound.workers.network_governance_consumer import (
    GovernanceHandler,
    network_governance_runners,
)
from diucs.adapters.inbound.workers.network_projector import (
    NetworkApplyConsumer,
    network_runners,
)
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.reply_processor import HandlesInboundText, reply_consumer
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.cache_redis.redis_cache import RedisCache
from diucs.adapters.outbound.clock_system.system_clock import SystemClock
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.network_registry import Neo4jNetworkRegistry
from diucs.adapters.outbound.graph_store.unit_of_work import (
    neo4j_network_uow_factory,
    neo4j_uow_factory,
)
from diucs.adapters.outbound.projection_queue import BusProjectionPublisher
from diucs.adapters.outbound.push_webpush.web_push import configured_push_sender
from diucs.adapters.outbound.telemetry.attributes import INSTRUMENTATION_NAME
from diucs.adapters.outbound.telemetry.consumer import consumer_observer
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.messaging import PushSender
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.sender_resolver import SenderResolver
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import current_tenant
from diucs.application.use_cases.apply_projection import ApplyProjection
from diucs.application.use_cases.board_projector import BoardProjector
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.grants import SupersedeDueGrants
from diucs.application.use_cases.handle_inbound_text import HandleInboundText
from diucs.application.use_cases.network_admin import GovernanceRecorder
from diucs.application.use_cases.network_board_projector import NetworkBoardProjector
from diucs.application.use_cases.network_governance import NetworkGovernance
from diucs.application.use_cases.network_leave import EndProjections
from diucs.application.use_cases.project_network import ProjectNetwork
from diucs.application.use_cases.projection_boundaries import (
    RunProjectionHeartbeat,
    RunProjectionHeartbeatCommand,
)
from diucs.application.use_cases.projection_reconcile import ReconcileProjection
from diucs.application.use_cases.query_board import QueryBoard
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.application.use_cases.respond_to_booking import RespondToBooking, SetDeclineReason
from diucs.application.work import ScheduledWork, WorkKind
from diucs.bootstrap.container import build
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.telemetry import start_telemetry
from diucs.bootstrap.tenant_senders import TenantSenderResolver, status_callback_url

SERVICE_BUS_MISSING = "DIUCS_SERVICEBUS_CONNECTION must be set for the queue workers"
REPLIES_QUEUE = "inbound.replies"
SENDER_HTTP_TIMEOUT_SECONDS = 10.0
RECEIPTS_QUEUE = "inbound.receipts"
SCHEDULED_WORK_QUEUE = "scheduled.work"


class WorkersConfigError(Exception):
    """The workers cannot start with this configuration. The text is fixed and holds no value."""


@dataclass(frozen=True, slots=True)
class NetworkProjectorWiring:
    """What the network projector's runners need (TEN-055): the producer, which reads in a tenant's
    read-only unit and publishes to the projection queue, and the apply consumer, which binds a
    network scope for each message."""

    producer: ProjectNetwork
    apply: NetworkApplyConsumer


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
    work_handlers: Mapping[WorkKind, WorkHandler],
    *,
    senders: SenderResolver | None = None,
    sealer: ContentSealer | None = None,
    push: PushSender | None = None,
    clock: Clock | None = None,
    app_url: str = "",
    board_projector: BoardRebuilder | None = None,
    network_projector: NetworkProjectorWiring | None = None,
    network_board_projector: NetworkBoardRebuilder | None = None,
    network_governance: GovernanceHandler | None = None,
) -> list[ServiceBusRunner]:
    """One runner for each inbound queue, each over a consumer that binds the message's tenant and
    handles the message under its trace span (O01): the replies, the receipts and, with the
    handlers of the dispatch table, `scheduled.work` (I05). With a sender resolver and a sealer,
    the two runners of `messages.outbound` (the text and email senders, I10) are added; each binds
    the message's tenant in the same way."""
    observe = consumer_observer(otel_trace.get_tracer(INSTRUMENTATION_NAME))
    runners = [
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
        ServiceBusRunner(
            client,
            SCHEDULED_WORK_QUEUE,
            None,
            build_scheduled_work_consumer(work_handlers, uow_factory, tenants, observe),
        ),
    ]
    if senders is not None and sealer is not None:
        runners += sender_runners(
            client, uow_factory, tenants, senders, sealer, clock or SystemClock(), observe
        )
    if push is not None and clock is not None and sealer is not None:
        runners.append(
            push_runner(client, uow_factory, tenants, push, sealer, clock, app_url, observe)
        )
    if board_projector is not None:
        runners += board_runners(client, board_projector, tenants, observe)
    if network_projector is not None:
        runners += network_runners(
            client, network_projector.producer, network_projector.apply, tenants, observe
        )
    if network_board_projector is not None:
        runners += network_board_runners(client, network_board_projector, tenants, observe)
    if network_governance is not None:
        runners += network_governance_runners(client, network_governance, tenants, observe)
    return runners


def projection_heartbeat_handler(job: RunProjectionHeartbeat) -> WorkHandler:
    """The projection heartbeat of one tenant (TEN-056), run once for each scheduled work of its
    kind. The scheduled-work consumer has bound the work's tenant."""

    async def step(work: ScheduledWork) -> None:
        await job.execute(RunProjectionHeartbeatCommand(work_id=work.id))

    return step


async def run_workers(
    loops: Sequence[Callable[[asyncio.Event], Awaitable[None]]], stop: asyncio.Event
) -> None:
    """Run every loop (a runner's `serve`) until `stop` is set."""
    await asyncio.gather(*(loop(stop) for loop in loops))


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    """Open every connection, run the workers until `stop` is set, and close them again."""
    connection = service_bus_connection(settings)
    container = build(settings)
    await container.startup()  # refuses to start when Neo4j cannot be reached
    tenants = container.tenants
    # The daily criteria review run (U31) is seeded once per tenant; a restart changes nothing.
    await container.seed_daily_schedules(await tenants.active_tenant_ids())
    cache = RedisCache.from_url(settings.redis_url)
    client = ServiceBusClient.from_connection_string(connection)
    bus = ServiceBusEventBus(client)
    http = httpx.AsyncClient(timeout=SENDER_HTTP_TIMEOUT_SECONDS)
    try:
        store = DriverIdempotencyStore(container.neo4j.driver)
        booking_sealer = AesGcmContentSealer(container.secrets)
        use_case = HandleInboundText(
            container.uow_factory,
            container.clock,
            container.ids,
            store,
            cache,
            ReportCapacity(container.uow_factory, container.clock, container.ids, store),
            ConfirmCapacity(container.uow_factory, container.clock, container.ids, store),
            respond_to_booking=RespondToBooking(
                container.uow_factory,
                store,
                container.clock,
                container.ids,
                booking_sealer,
            ),
            set_decline_reason=SetDeclineReason(container.uow_factory, store, container.clock),
        )
        senders = TenantSenderResolver(
            container.tenants, container.secrets, http, status_callback_url(settings)
        )
        sealer = AesGcmContentSealer(container.secrets)
        registry = Neo4jNetworkRegistry(container.neo4j)
        network_access = NetworkAccess(registry, container.tenants)
        network_board_projector = NetworkBoardProjector(
            QueryNetworkBoard(
                neo4j_network_uow_factory(container.neo4j, clock=container.clock, read_only=True),
                network_access,
                container.clock,
            ),
            network_access,
            cache,
            container.clock,
        )
        projection_producer = ProjectNetwork(
            neo4j_uow_factory(container.neo4j, clock=container.clock, read_only=True),
            registry,
            BusProjectionPublisher(bus),
            container.clock,
        )
        network_projector = NetworkProjectorWiring(
            producer=projection_producer,
            apply=NetworkApplyConsumer(
                ApplyProjection(
                    neo4j_network_uow_factory(container.neo4j, clock=container.clock),
                    registry,
                    container.clock,
                    notifier=network_board_projector,
                ),
                registry,
                tenants,
            ),
        )
        end_projections = EndProjections(
            neo4j_network_uow_factory(container.neo4j, clock=container.clock),
            registry,
            container.clock,
        )
        reconcile = ReconcileProjection(
            neo4j_network_uow_factory(container.neo4j, clock=container.clock, read_only=True),
            end_projections,
            registry,
            container.clock,
        )
        governance = NetworkGovernance(
            registry,
            end_projections,
            projection_producer,
            container.uow_factory,
            container.ids,
            container.clock,
            tenants,
        )
        supersede = SupersedeDueGrants(
            registry,
            GovernanceRecorder(
                container.uow_factory,
                neo4j_network_uow_factory(container.neo4j, clock=container.clock),
                container.ids,
                container.clock,
            ),
            container.clock,
        )

        async def supersede_due() -> int:
            return await supersede.execute(current_tenant())

        work_handlers = dict(container.scheduled_work.handlers)
        work_handlers[WorkKind.PROJECTION_HEARTBEAT] = projection_heartbeat_handler(
            RunProjectionHeartbeat(
                container.uow_factory,
                container.ids,
                container.clock,
                registry,
                projection_producer,
                reconcile,
                supersede_due,
            )
        )
        push = configured_push_sender(container.secrets, settings.webpush_subject)
        runners = build_runners(
            client,
            use_case,
            container.uow_factory,
            tenants,
            work_handlers,
            senders=senders,
            sealer=sealer,
            push=push,
            clock=container.clock,
            app_url=settings.base_url,
            board_projector=BoardProjector(
                QueryBoard(container.uow_factory, container.clock), cache, container.clock
            ),
            network_projector=network_projector,
            network_board_projector=network_board_projector,
            network_governance=governance,
        )
        await run_workers([runner.serve for runner in runners], stop)
    finally:
        await http.aclose()
        await bus.close()
        await client.close()
        await cache.aclose()
        await container.shutdown()


async def _run(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on every platform
            loop.add_signal_handler(name, stop.set)
    provider = start_telemetry(settings)  # O01: nothing is exported without an OTLP endpoint
    try:
        await serve(settings, stop)
    finally:
        if provider is not None:
            provider.shutdown()  # flushes the last batch of spans


def main() -> None:
    try:
        settings = Settings()
        service_bus_connection(settings)
    except WorkersConfigError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
