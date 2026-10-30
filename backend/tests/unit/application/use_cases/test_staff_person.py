"""The person record of a signed-in executive (W9H, DEC-1042).

An executive signs in through the organisation's directory, so no Practitioner exists for them until
something makes one: the push subscription is stored against a Practitioner. `EnsureStaffPerson`
makes the minimal record (no phone, no name of a person) the first time an executive saves a push
subscription, and only for the executive role. Recording stand-ins; the stored result is proved in
tests/integration/adapters/inbound/fhir_rest/test_routes_exec_push.py. Sample values only.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from diucs.application.actor import Actor
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.staff_person import (
    STAFF_DISPLAY_NAME,
    STAFF_PERSON_ROLES,
    EnsureStaffPerson,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.people import Practitioner
from tests.support.actors import ACTOR_TENANT
from tests.support.registration_rig import StubUnits

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
SUBJECT = "stf-0123456789abcdef0123456789abcdef"


def _actor(role: Role = Role.EXEC, person: str | None = SUBJECT) -> Actor:
    return Actor(
        role=role,
        practitioner_id=person,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


def _use(units: StubUnits) -> EnsureStaffPerson:
    return EnsureStaffPerson(units, _Clock())


class _Clock:
    def now(self) -> datetime:
        return NOW


async def test_an_executive_with_no_record_gets_a_minimal_active_person() -> None:
    units = StubUnits(ScopeId.tenant(ACTOR_TENANT))

    await _use(units).execute(_actor())

    person = units.people.practitioners[SUBJECT]
    assert person == Practitioner(
        id=SUBJECT, active=True, display_name=STAFF_DISPLAY_NAME, phone_hash=None
    )
    assert units.commits == 1
    assert [(e.use_case, e.entity_ids) for e in units.audit.entries] == [
        ("EnsureStaffPerson", (SUBJECT,))
    ]


async def test_an_executive_who_has_a_record_is_left_exactly_as_it_is() -> None:
    units = StubUnits(ScopeId.tenant(ACTOR_TENANT))
    units.people.practitioners[SUBJECT] = Practitioner(
        id=SUBJECT, active=True, display_name="Sample Executive", phone_hash=None
    )
    before = dict(units.people.practitioners)

    await _use(units).execute(_actor())

    assert units.people.practitioners == before
    assert units.commits == 0
    assert units.audit.entries == []


async def test_a_removed_executive_is_not_brought_back() -> None:
    units = StubUnits(ScopeId.tenant(ACTOR_TENANT))
    removed = Practitioner(id=SUBJECT, active=False, display_name="Sample", phone_hash=None)
    units.people.practitioners[SUBJECT] = removed

    await _use(units).execute(_actor())

    assert units.people.practitioners[SUBJECT] == replace(removed, active=False)


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.EXEC])
async def test_no_other_role_gets_a_person_made(role: Role) -> None:
    units = StubUnits(ScopeId.tenant(ACTOR_TENANT))

    with pytest.raises(NotAllowed):
        await _use(units).execute(_actor(role))

    assert units.people.practitioners == {}
    assert units.commits == 0


async def test_an_actor_with_no_person_gets_nothing_made() -> None:
    units = StubUnits(ScopeId.tenant(ACTOR_TENANT))

    with pytest.raises(NotAllowed):
        await _use(units).execute(_actor(person=None))

    assert units.people.practitioners == {}


def test_only_the_executive_role_is_a_staff_person() -> None:
    assert frozenset({Role.EXEC}) == STAFF_PERSON_ROLES
