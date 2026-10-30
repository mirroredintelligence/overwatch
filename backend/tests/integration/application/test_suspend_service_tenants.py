"""Two-tenant tests for SuspendService and ResumeService (U36, DEC-130 to DEC-132).

Tenant A holds UCR East, with a report and an open request. Tenant B holds its own tenant record
and nothing else. B cannot suspend or resume A's service, and A's flag and requests are unchanged:
a B id given as input answers as not found. Runs on the run's two tenants (the uow_factory_a and
uow_factory_b fixtures of tests/conftest.py).
"""

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.suspend_service import (
    ResumeService,
    ResumeServiceCommand,
    SuspendService,
    SuspendServiceCommand,
)
from diucs.domain.errors import NotFound
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from tests.integration.application.test_suspend_service import sample_wording, seed_east
from tests.support.booking_rig import LEAD, SECRETS, at
from tests.support.neo4j import count_nodes, wipe
from tests.support.tenant_seed import contracted_container

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """The contracted schema (superseded global keys dropped, DEC-159): the two-tenant tests run on
    it, not on the root driver, which still holds the global Concept and Communication keys."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    await wipe(two_tenant_driver)
    return two_tenant_driver


EAST = "ucr-east"


async def test_tenant_b_cannot_suspend_a_service_of_tenant_a(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory_a, neo4j_driver, tenant_id)
    suspend = SuspendService(
        uow_factory_b,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 20)),
        SequentialIds("tb"),
        AesGcmContentSealer(SECRETS),
        sample_wording,
        DEFAULT_POLICY,
    )
    with pytest.raises(NotFound):
        await suspend.execute(
            SuspendServiceCommand(
                idempotency_key="tb-1", actor=LEAD, service_id=EAST, reason="other"
            )
        )
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 0


async def test_tenant_b_cannot_resume_a_suspended_service_of_tenant_a(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory_a, neo4j_driver, tenant_id)
    suspend_a = SuspendService(
        uow_factory_a,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 20)),
        SequentialIds("ta"),
        AesGcmContentSealer(SECRETS),
        sample_wording,
        DEFAULT_POLICY,
    )
    await suspend_a.execute(
        SuspendServiceCommand(idempotency_key="ta-1", actor=LEAD, service_id=EAST, reason="other")
    )
    resume_b = ResumeService(
        uow_factory_b,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(15, 0)),
        SequentialIds("tr"),
        DEFAULT_POLICY,
    )
    with pytest.raises(NotFound):
        await resume_b.execute(
            ResumeServiceCommand(
                idempotency_key="tb-2",
                actor=LEAD,
                service_id=EAST,
                phoned_register_number=True,
                reason_resolved=True,
            )
        )
    assert await count_nodes(neo4j_driver, "ServiceFlag") == 1
