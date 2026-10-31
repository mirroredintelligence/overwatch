"""Every subscription of the Service Bus topology has a reader, and every reader has a
subscription (B1 task 5, N2). A subscription nothing reads fills up and its messages expire, so a
declared subscription with no consumer is a fault; a consumer of an entity the topology does not
declare is a fault too. The worker's runners are built with every optional part, and their
(entity, subscription) pairs are compared with `infra/servicebus-config.json`.

The topology file is the one the emulator and the deployment read."""

import json
from pathlib import Path
from typing import Any

from diucs.adapters.inbound.workers.network_projector import NetworkApplyConsumer
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.testing.recording_senders import FixedSenderResolver
from diucs.application.work import WorkKind
from diucs.bootstrap import workers_main
from diucs.bootstrap.workers_main import AlertWiring, NetworkProjectorWiring, build_runners

TOPOLOGY = Path(__file__).resolve().parents[4] / "infra" / "servicebus-config.json"

# Subscriptions that the pilot does not read, with the reason each was deleted instead of built
# (decision DEC-1111). A subscription added to the topology must be read or be listed here.
DELETED: dict[str, str] = {}


def _declared() -> set[tuple[str, str | None]]:
    config = json.loads(TOPOLOGY.read_text(encoding="utf-8"))
    namespace = config["UserConfig"]["Namespaces"][0]
    pairs: set[tuple[str, str | None]] = {(q["Name"], None) for q in namespace["Queues"]}
    for topic in namespace["Topics"]:
        pairs |= {(topic["Name"], s["Name"]) for s in topic["Subscriptions"]}
    return pairs


async def _no_work(work: Any) -> None:
    return None


def _read() -> set[tuple[str, str | None]]:
    from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer  # noqa: F401
    from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
    from diucs.adapters.testing.fixed_secrets import FixedSecretStore
    from diucs.application.ports.outbound.messaging import PushSender  # noqa: F401

    class _Anything:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError("not used")

    anything: Any = _Anything()
    tenants: Any = StaticTenants(["tenant-a"])
    runners = build_runners(
        client=None,  # type: ignore[arg-type]
        handle_inbound_text=anything,
        uow_factory=anything,
        tenants=tenants,
        work_handlers={WorkKind.REMINDER: _no_work},
        senders=FixedSenderResolver(),
        sealer=AesGcmContentSealer(FixedSecretStore({"link-token": b"x" * 32})),
        push=anything,
        clock=anything,
        board_projector=anything,
        network_projector=NetworkProjectorWiring(
            producer=anything, apply=NetworkApplyConsumer(anything, anything, tenants)
        ),
        network_board_projector=anything,
        network_governance=anything,
        alerts=AlertWiring(evaluator=anything, notifier=anything),
    )
    return {(r._entity, r._subscription) for r in runners}


def test_every_declared_subscription_and_queue_has_a_reader() -> None:
    unread = _declared() - _read()

    assert unread == set(), f"declared and read by nothing: {sorted(map(str, unread))}"


def test_every_reader_has_a_declared_subscription_or_queue() -> None:
    undeclared = _read() - _declared()

    assert undeclared == set(), f"read but not declared: {sorted(map(str, undeclared))}"


def test_the_pilot_reads_the_alert_evaluator_and_the_notifier() -> None:
    pairs = _read()

    assert ("capacity.events", "alert-evaluator") in pairs
    assert ("alerts.events", "notifier") in pairs


def test_the_subscriptions_that_were_deleted_are_gone_from_the_topology() -> None:
    declared = {name for _, name in _declared() if name is not None}

    assert not set(DELETED) & declared


def test_the_worker_module_wires_the_alerts() -> None:
    assert hasattr(workers_main, "AlertWiring")
