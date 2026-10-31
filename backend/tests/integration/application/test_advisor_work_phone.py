"""The advisor's work phone (W44, DEC-1034, DEC-1178), against the real Neo4j.

The tenant administrator records the number a clinician phones an advisor on. It is held under
`work-<practitioner id>` in the protected contact store, never in the audit entry; the clinician who
holds a request is then shown it (ReadAdvisorContact). Another tenant's person, an unknown one and
one who has left are the same not found; another tenant's number is never read. Sample numbers.
"""

import dataclasses
from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.advisor_work_phone import (
    RecordAdvisorWorkPhone,
    RecordAdvisorWorkPhoneCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.people import Practitioner, work_contact_key
from tests.support.actors import ACTOR_TENANT
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
ADMIN = Actor(
    role=Role.TENANT_ADMIN,
    practitioner_id="admin-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ADVISOR_ID = "prac-advisor-1"
NUMBER = "07700 900123"


async def _seed(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    await ensure_audit_heads(driver, tenant)
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id=ADVISOR_ID, active=True, display_name="Sample Advisor", phone_hash=None)
        )
        await uow.people.save_practitioner(
            Practitioner(
                id="prac-left", active=False, display_name="Sample Leaver", phone_hash=None
            )
        )
        await uow.commit()


def _record(factory: UnitOfWorkFactory) -> RecordAdvisorWorkPhone:
    return RecordAdvisorWorkPhone(factory, FixedClock(NOW))


async def _stored(factory: UnitOfWorkFactory, person: str = ADVISOR_ID) -> str | None:
    async with factory() as uow:
        return await uow.contacts.get_phone(work_contact_key(person))


async def test_the_number_is_stored_under_the_work_key_and_read_back(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    await _record(uow_factory).execute(RecordAdvisorWorkPhoneCommand(ADMIN, ADVISOR_ID, NUMBER))

    assert await _stored(uow_factory) == NUMBER


async def test_a_second_number_replaces_the_first(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    record = _record(uow_factory)
    await record.execute(RecordAdvisorWorkPhoneCommand(ADMIN, ADVISOR_ID, NUMBER))

    await record.execute(RecordAdvisorWorkPhoneCommand(ADMIN, ADVISOR_ID, "07700 900456"))

    assert await _stored(uow_factory) == "07700 900456"


async def test_the_audit_entry_names_the_person_and_the_kind_and_never_the_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    await _record(uow_factory).execute(RecordAdvisorWorkPhoneCommand(ADMIN, ADVISOR_ID, NUMBER))

    async with uow_factory() as uow:
        entries = [
            r.entry
            for r in await uow.audit.records()
            if r.entry.use_case == "RecordAdvisorWorkPhone"
        ]
    assert len(entries) == 1
    assert entries[0].entity_ids == (ADVISOR_ID,)
    assert entries[0].snapshot == {"kind": "work-phone"}
    assert "900123" not in repr(entries[0])


@pytest.mark.parametrize("phone", ["", "0770090012", "+1 202 555 0100", "notanumber"])
async def test_a_number_that_is_not_a_full_uk_number_is_refused_and_nothing_is_stored(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, phone: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(ValidationFailed):
        await _record(uow_factory).execute(RecordAdvisorWorkPhoneCommand(ADMIN, ADVISOR_ID, phone))

    assert await _stored(uow_factory) is None


@pytest.mark.parametrize("person", ["prac-nobody", "prac-left"])
async def test_an_unknown_person_and_one_who_has_left_are_the_same_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, person: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(NotFound):
        await _record(uow_factory).execute(RecordAdvisorWorkPhoneCommand(ADMIN, person, NUMBER))

    assert await _stored(uow_factory, person) is None


@pytest.mark.parametrize("role", [Role.LEAD, Role.ADVISOR, Role.CLINICAL, Role.OWNER, Role.EXEC])
async def test_no_role_but_the_tenant_administrator_may_record_it(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, role: Role
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(NotAllowed):
        await _record(uow_factory).execute(
            RecordAdvisorWorkPhoneCommand(dataclasses.replace(ADMIN, role=role), ADVISOR_ID, NUMBER)
        )

    assert await _stored(uow_factory) is None


async def test_another_tenants_person_is_not_found_and_its_number_is_never_read(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    async with uow_factory_b() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-of-b", active=True, display_name="Sample B", phone_hash=None)
        )
        await uow.contacts.put_phone(work_contact_key("prac-of-b"), "07700 900999")
        await uow.commit()

    with pytest.raises(NotFound):
        await _record(uow_factory).execute(
            RecordAdvisorWorkPhoneCommand(ADMIN, "prac-of-b", NUMBER)
        )

    assert await _stored(uow_factory, "prac-of-b") is None
    assert await _stored(uow_factory_b, "prac-of-b") == "07700 900999"
