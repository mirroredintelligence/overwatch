"""SavePushSubscription refuses an endpoint that could reach an inside address before it reads or
writes anything (R11). Recording stand-ins; the stored round trip is in the integration test."""

from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.use_cases.push_subscription import (
    SavePushSubscription,
    SavePushSubscriptionCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubIdempotency, StubUnits, Writes

REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-1",
    device_id="dev-1",
    channel="api",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


@pytest.mark.parametrize(
    "subscription",
    [
        {"endpoint": "http://push.example/x", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://169.254.169.254/x", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://localhost/x", "keys": {"p256dh": "a", "auth": "b"}},
        {"keys": {"p256dh": "a", "auth": "b"}},
        {},
    ],
)
async def test_an_endpoint_that_could_reach_an_inside_address_is_refused_before_any_work(
    subscription: dict[str, Any],
) -> None:
    units = StubUnits()
    use = SavePushSubscription(
        units,
        FixedClock(datetime(2026, 10, 29, 14, 0, tzinfo=UTC)),
        SequentialIds(),
        StubIdempotency(Writes()),
    )
    with pytest.raises(ValidationFailed):
        await use.execute(
            SavePushSubscriptionCommand("k1", REPORTER, "app-dev-1", subscription, "wording-v1")
        )
    assert units.writes.names == []
    assert units.commits == 0
