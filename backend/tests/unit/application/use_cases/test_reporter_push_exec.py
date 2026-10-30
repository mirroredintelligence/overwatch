"""The test notification of an executive (W9H, DEC-1043).

An executive holds no post, so the reporter's test (queued to the person's own post through the
sealed send) cannot be theirs. Theirs is the person push alerts use: a K3 message that names the
person, with the plain title and body of the test, which says nothing about a service, a figure or
a person and carries no link. A reporter's test is unchanged. Recording stand-ins; no real push.
"""

from datetime import UTC, datetime

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.reporter_push import (
    EXEC_TEST_BODY,
    TEST_TITLE,
    NoPushSubscription,
    SendPushTest,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.people import Practitioner
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SUBJECT = "stf-0123456789abcdef0123456789abcdef"
OTHER = "stf-fedcba9876543210fedcba9876543210"


class _Sealer:
    def seal(self, content: str, **_: str) -> str:
        raise AssertionError("an executive's test is not a sealed message")


def _actor(role: Role = Role.EXEC, person: str = SUBJECT) -> Actor:
    return Actor(
        role=role,
        practitioner_id=person,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


def _world(subscribed: tuple[str, ...] = (SUBJECT,)) -> tuple[StubUnits, SendPushTest]:
    units = StubUnits(ScopeId.tenant(ACTOR_TENANT))
    units.people.practitioners[SUBJECT] = Practitioner(
        id=SUBJECT, active=True, display_name="Executive", phone_hash=None
    )
    for person in subscribed:
        units.push_subscriptions.held[f"app-{person}"] = PushSubscription(
            device_id=f"app-{person}",
            practitioner_id=person,
            subscription={"endpoint": "https://push.example/sample-endpoint"},
            saved_at=NOW,
        )
    return units, SendPushTest(units, FixedClock(NOW), SequentialIds(), _Sealer())  # type: ignore[arg-type]


async def test_an_executives_test_is_one_person_push_with_no_post_and_no_link() -> None:
    units, use = _world()

    queued = await use.execute(_actor())

    [message] = units.outbox.messages
    assert queued == message.id
    assert message.event_type == "SendMessage"
    assert message.payload == {
        "message_id": "K3",
        "channel": "push",
        "recipient_practitioner_id": SUBJECT,
        "title": TEST_TITLE,
        "body": EXEC_TEST_BODY,
    }
    assert "http" not in EXEC_TEST_BODY
    assert units.communications.sent == []
    assert units.commits == 1
    assert [(e.use_case, e.entity_ids) for e in units.audit.entries] == [
        ("SendPushTest", (message.id, SUBJECT))
    ]


async def test_an_executive_with_no_saved_subscription_gets_no_test() -> None:
    units, use = _world(subscribed=())

    with pytest.raises(NoPushSubscription):
        await use.execute(_actor())

    assert units.outbox.messages == []
    assert units.commits == 0


async def test_another_persons_subscription_is_not_the_executives() -> None:
    units, use = _world(subscribed=(OTHER,))

    with pytest.raises(NoPushSubscription):
        await use.execute(_actor())

    assert units.outbox.messages == []


@pytest.mark.parametrize("role", [role for role in Role if role not in (Role.EXEC, Role.REPORTER)])
async def test_no_other_role_has_a_test_push_made(role: Role) -> None:
    units, use = _world()

    with pytest.raises(NotAllowed):
        await use.execute(_actor(role))

    assert units.outbox.messages == []
