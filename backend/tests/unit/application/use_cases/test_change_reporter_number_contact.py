"""A change of reporter number keeps the new number where the pages and the sender can read it
(W7B C): the successor post of an until-changed change holds it, and a cover holds it under the
covered post's cover key, so the lead's lists can show the end of it. The number is in the
protected contact store only: never in the audit entry (which keeps the hash)."""

from collections.abc import Iterator

import pytest

from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.change_reporter_number import (
    ChangeReporterNumber,
    ChangeReporterNumberCommand,
    CoverDuration,
)
from diucs.domain.codes import Role
from tests.support.actors import ACTOR_TENANT
from tests.support.w7b_rig import LEAD, NOW, Rig

pytestmark = pytest.mark.asyncio(loop_scope="session")

LEAD_ACTOR = Actor(Role.LEAD, LEAD, None, "api", frozenset(), tenant_id=ACTOR_TENANT)
NEW_NUMBER = "07700 900888"


@pytest.fixture(autouse=True)
def _bound() -> Iterator[None]:
    with bind_tenant(ACTOR_TENANT):
        yield


def _use_case(rig: Rig) -> ChangeReporterNumber:
    return ChangeReporterNumber(
        rig.units, rig.clock, SequentialIds("new"), rig.units.idempotency, rig.hasher
    )


def _command(duration: CoverDuration) -> ChangeReporterNumberCommand:
    return ChangeReporterNumberCommand(
        idempotency_key="change-key-0001",
        actor=LEAD_ACTOR,
        service_id="svc-b",
        new_mobile=NEW_NUMBER,
        duration=duration,
    )


async def test_an_until_changed_change_gives_the_new_post_the_new_number() -> None:
    rig = Rig()
    rig.lead_world()

    result = await _use_case(rig).execute(_command(CoverDuration.UNTIL_CHANGED))

    assert result.role_id != "role-rep-b"
    assert rig.units.contacts.phones[result.role_id] == "+447700900888"
    assert rig.units.contacts.phones["role-rep-b"] == "+447700900421"


async def test_a_cover_keeps_its_number_under_the_covered_posts_cover_key() -> None:
    rig = Rig()
    rig.lead_world()

    result = await _use_case(rig).execute(_command(CoverDuration.TODAY))

    assert result.role_id == "role-rep-b"
    assert rig.units.contacts.phones["cover-role-rep-b"] == "+447700900888"
    assert rig.units.contacts.phones["role-rep-b"] == "+447700900421"
    assert result.covered_until is not None and result.covered_until > NOW


async def test_the_number_is_not_in_the_audit_entry() -> None:
    rig = Rig()
    rig.lead_world()

    await _use_case(rig).execute(_command(CoverDuration.TODAY))

    audit = repr(rig.units.audit.entries[-1])
    assert "900888" not in audit
