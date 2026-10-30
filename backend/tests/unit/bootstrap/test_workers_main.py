"""The process entry of the inbound queue workers (I08): configuration that fails closed with fixed
messages that never hold a value from the environment, and the two runners it composes. No
Docker and no Service Bus: the runners are built with no client and never started."""

import asyncio
from pathlib import Path

import pytest
from pydantic import SecretStr

from diucs.adapters.inbound.workers.delivery_tracker import receipt_consumer
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.use_cases.handle_inbound_text import (
    HandleInboundTextCommand,
    HandleInboundTextResult,
)
from diucs.application.work import WorkKind
from diucs.bootstrap import workers_main
from diucs.bootstrap.settings import Settings
from diucs.bootstrap.workers_main import (
    NetworkProjectorWiring,
    WorkersConfigError,
    build_runners,
    run_workers,
    service_bus_connection,
)

CONNECTION = "Endpoint=sb://example;SharedAccessKeyName=k;SharedAccessKey=SECRET-KEY-TEXT"


async def _no_work(work: object) -> None:
    raise AssertionError("no work runs when the runners are only built")


class _UseCase:
    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult:
        raise AssertionError("not used")


def _no_unit() -> object:
    raise AssertionError("not used")


def test_the_environment_no_longer_lists_the_tenants_the_workers_serve() -> None:
    # TEN-025: the tenants are the active tenants of the directory (TEN-007), read for each message.
    # The list in the environment that stood in for it is gone, and so is its loader.
    assert not hasattr(workers_main, "configured_tenants")
    assert not hasattr(workers_main, "TENANTS_VARIABLE")
    assert "DIUCS_WORKER_TENANTS" not in Path(workers_main.__file__).read_text(encoding="utf-8")


def test_the_service_bus_connection_is_the_setting() -> None:
    assert service_bus_connection(Settings(servicebus_connection=SecretStr(CONNECTION))) == (
        CONNECTION
    )


def test_no_service_bus_connection_is_refused_without_a_value() -> None:
    with pytest.raises(WorkersConfigError, match="DIUCS_SERVICEBUS_CONNECTION"):
        service_bus_connection(Settings(servicebus_connection=None))


def test_main_stops_with_the_fixed_message_when_there_is_no_service_bus_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DIUCS_SERVICEBUS_CONNECTION", raising=False)

    with pytest.raises(SystemExit) as raised:
        workers_main.main()

    assert "DIUCS_SERVICEBUS_CONNECTION" in str(raised.value)


def test_main_runs_the_workers_on_the_settings_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_SERVICEBUS_CONNECTION", CONNECTION)
    seen: list[object] = []

    async def fake_run(settings: Settings) -> None:
        seen.append(type(settings))

    monkeypatch.setattr(workers_main, "_run", fake_run)

    workers_main.main()

    assert seen == [Settings]


def test_there_is_one_runner_for_each_queue_and_each_binds_the_tenant() -> None:
    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
    )

    assert [(r._entity, r._subscription, r._sessions) for r in runners] == [
        ("inbound.replies", None, False),
        ("inbound.receipts", None, False),
        ("scheduled.work", None, False),
    ]
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)


def test_the_receipt_consumer_is_built_from_the_same_parts() -> None:
    consumer = receipt_consumer(_no_unit, StaticTenants(["tenant-a"]))  # type: ignore[arg-type]

    assert isinstance(consumer, TenantBoundConsumer)


async def test_run_workers_runs_every_runner_until_stop_is_set() -> None:
    stop = asyncio.Event()
    started: list[str] = []

    class _Runner:
        def __init__(self, name: str) -> None:
            self.name = name

        async def serve(self, event: asyncio.Event) -> None:
            started.append(self.name)
            await event.wait()

    task = asyncio.create_task(run_workers([_Runner("a").serve, _Runner("b").serve], stop))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert sorted(started) == ["a", "b"]
    assert not task.done()

    stop.set()
    await task


def test_the_queues_are_the_ones_the_webhook_fills() -> None:
    from diucs.adapters.inbound.sms_webhook import routes
    from diucs.application.ports.outbound.event_bus import QUEUES

    assert workers_main.REPLIES_QUEUE == routes.REPLIES_QUEUE
    assert workers_main.RECEIPTS_QUEUE == routes.RECEIPTS_QUEUE
    assert {workers_main.REPLIES_QUEUE, workers_main.RECEIPTS_QUEUE} <= QUEUES


def test_with_a_sender_resolver_the_two_sender_runners_are_added_and_each_binds_the_tenant() -> (
    None
):
    from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
    from diucs.adapters.testing.fixed_secrets import FixedSecretStore
    from diucs.adapters.testing.recording_senders import FixedSenderResolver

    sealer = AesGcmContentSealer(FixedSecretStore({"link-token": b"x" * 32}))
    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
        senders=FixedSenderResolver(),
        sealer=sealer,
    )

    assert [(r._entity, r._subscription) for r in runners] == [
        ("inbound.replies", None),
        ("inbound.receipts", None),
        ("scheduled.work", None),
        ("messages.outbound", "text-sender"),
        ("messages.outbound", "email-sender"),
    ]
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)
    assert [r._consumer._inner.name for r in runners[3:]] == ["sender-sms", "sender-email"]


def test_without_a_sender_resolver_only_the_three_inbound_runners_are_built() -> None:
    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
    )

    assert len(runners) == 3


def test_with_a_board_projector_the_two_board_runners_are_added_and_each_binds_the_tenant() -> None:
    class _Projector:
        async def handle(self, event_type: str, payload: object) -> bool:
            raise AssertionError("not used")

    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
        board_projector=_Projector(),  # type: ignore[arg-type]
    )

    assert [(r._entity, r._subscription) for r in runners] == [
        ("inbound.replies", None),
        ("inbound.receipts", None),
        ("scheduled.work", None),
        ("capacity.events", "board-projector"),
        ("booking.events", "board-projector"),
    ]
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)


def test_with_the_network_projector_its_five_runners_are_added() -> None:
    from diucs.adapters.inbound.workers.network_projector import NetworkApplyConsumer
    from tests.unit.adapters.inbound.workers.test_network_projector import (
        _Apply,
        _Producer,
        _Registry,
    )

    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
        network_projector=NetworkProjectorWiring(
            producer=_Producer(),  # type: ignore[arg-type]
            apply=NetworkApplyConsumer(_Apply(), _Registry(), StaticTenants(["tenant-a"])),  # type: ignore[arg-type]
        ),
    )

    assert [(r._entity, r._subscription) for r in runners[3:]] == [
        ("capacity.events", "network-projector"),
        ("booking.events", "network-projector"),
        ("criteria.events", "network-projector"),
        ("registration.events", "network-projector"),
        ("projection.work", None),
    ]


def test_without_the_network_projector_no_projection_runner_is_built() -> None:
    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
    )
    assert all(r._entity != "projection.work" for r in runners)


def test_with_the_network_board_projector_its_runner_is_added() -> None:
    from tests.unit.adapters.inbound.workers.test_network_board_consumer import _Projector

    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
        network_board_projector=_Projector(),  # type: ignore[arg-type]
    )
    assert [(r._entity, r._subscription) for r in runners[3:]] == [
        ("network.events", "network-board-projector")
    ]
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)


def test_with_the_network_governance_handler_its_runner_is_added() -> None:
    from tests.unit.adapters.inbound.workers.test_network_governance_consumer import _Governance

    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=_UseCase(),
        uow_factory=_no_unit,  # type: ignore[arg-type]
        tenants=StaticTenants(["tenant-a"]),
        work_handlers={WorkKind.REMINDER: _no_work},
        network_governance=_Governance(),
    )
    assert [(r._entity, r._subscription) for r in runners[3:]] == [
        ("network.events", "network-projector")
    ]
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)


async def test_the_heartbeat_handler_runs_the_job_for_the_work_it_is_given() -> None:
    from datetime import UTC, datetime

    from diucs.application.work import ScheduledWork
    from diucs.bootstrap.workers_main import projection_heartbeat_handler

    seen: list[str] = []

    class _Job:
        async def execute(self, command: Any) -> None:
            seen.append(command.work_id)

    work = ScheduledWork(
        id="work-9",
        kind=WorkKind.PROJECTION_HEARTBEAT,
        due_at=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
        about_id="tenant-a",
        sequence_number=None,
        status="scheduled",
    )
    await projection_heartbeat_handler(_Job())(work)  # type: ignore[arg-type]
    assert seen == ["work-9"]
