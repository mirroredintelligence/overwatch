"""ReadServiceDetail against real Neo4j (DEC-1367, DEC-130 to DEC-132).

The services, criteria and reports are those of test_filter_options.py. The Analytics User, Advisor
v2 and the advisor read a service of their own tenant; another tenant's service is NotFound, the
same as one that is nowhere; the shift lead and a reporter are not readers. The service's own
number is read from its profile and nothing of a person is. Synthetic values.
"""

import dataclasses

import pytest
from neo4j import AsyncDriver

from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.service_detail import ReadServiceDetail
from overwatch.domain.codes import Role
from overwatch.domain.errors import NotAllowed, NotFound
from tests.integration.application.test_filter_options import (
    ACTOR,
    NOW,
    UCR_EAST,
    UCR_WEST,
    _profile,
    _seed,
)
from tests.integration.application.test_filter_options_b6 import _give_phone
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _read(factory: UnitOfWorkFactory) -> ReadServiceDetail:
    return ReadServiceDetail(factory, FixedClock(NOW))


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.ADVISOR_V2, Role.ANALYTICS_USER])
async def test_a_reader_gets_the_service_its_number_criteria_and_districts(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, role: Role
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await _give_phone(uow_factory, UCR_WEST, "01305 900100")

    detail = await _read(uow_factory).execute(dataclasses.replace(ACTOR, role=role), UCR_WEST)

    assert detail.entry.service_id == UCR_WEST
    assert detail.entry.name == "UCR West"
    assert detail.phone == "01305 900100"
    assert detail.districts == ("DT1", "DT2", "DT3", "DT4")
    assert detail.accepts == ("fall-no-injury", "frailty")
    assert detail.excludes == ()
    assert detail.age_min == 18
    assert detail.opening_hours


async def test_a_service_with_no_number_has_none(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    detail = await _read(uow_factory).execute(ACTOR, UCR_EAST)

    assert detail.phone is None


async def test_another_tenants_service_is_not_found_as_one_that_is_nowhere(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    async with uow_factory_b() as uow:
        await uow.services.save(_profile("svc-b-only", "Org B Service"))
        await uow.commit()
    await _give_phone(uow_factory_b, "svc-b-only", "01305 900999")

    with pytest.raises(NotFound):
        await _read(uow_factory).execute(ACTOR, "svc-b-only")
    with pytest.raises(NotFound):
        await _read(uow_factory).execute(ACTOR, "svc-nowhere")


@pytest.mark.parametrize("role", [Role.LEAD, Role.CLINICAL, Role.REPORTER, Role.EXEC])
async def test_a_role_that_is_not_a_reader_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, role: Role
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(NotAllowed):
        await _read(uow_factory).execute(dataclasses.replace(ACTOR, role=role), UCR_WEST)
