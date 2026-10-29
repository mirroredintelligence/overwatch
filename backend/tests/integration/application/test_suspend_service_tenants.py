"""Two-tenant tests for SuspendService and ResumeService (U36, DEC-130 to DEC-132).

Tenant A holds UCR East, with a report and an open request. Tenant B holds its own tenant record
and nothing else. B cannot suspend or resume A's service, and A's flag and requests are unchanged:
a B id given as input answers as not found. Runs on the run's two tenants (the uow_factory_a and
uow_factory_b fixtures of tests/conftest.py).
"""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.outbound.graph_store.driver import Neo4jConnection
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.outbound.graph_store.tenant_directory import Neo4jTenantDirectory
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
from tests.integration.application.test_suspend_service import seed_east
from tests.integration.graph_store.test_tenant_directory import seed_tenant
from tests.support.booking_rig import LEAD, SECRETS, at
from tests.support.neo4j import count_nodes
from tests.support.tenant_samples import SAMPLE_WORDING, make_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

EAST = "ucr-east"


@pytest_asyncio.fixture(loop_scope="session")
async def connection() -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


async def test_tenant_b_cannot_suspend_a_service_of_tenant_a(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    connection: Neo4jConnection,
    tenant_id: str,
    other_tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory_a, neo4j_driver, tenant_id)
    await seed_tenant(neo4j_driver, make_tenant(id=other_tenant_id, values=SAMPLE_WORDING))
    suspend = SuspendService(
        uow_factory_b,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 20)),
        SequentialIds("tb"),
        AesGcmContentSealer(SECRETS),
        Neo4jTenantDirectory(connection),
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
    connection: Neo4jConnection,
    tenant_id: str,
    other_tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_east(uow_factory_a, neo4j_driver, tenant_id)
    await seed_tenant(neo4j_driver, make_tenant(id=other_tenant_id, values=SAMPLE_WORDING))
    suspend_a = SuspendService(
        uow_factory_a,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(14, 20)),
        SequentialIds("ta"),
        AesGcmContentSealer(SECRETS),
        Neo4jTenantDirectory(connection),
    )
    await suspend_a.execute(
        SuspendServiceCommand(
            idempotency_key="ta-1", actor=LEAD, service_id=EAST, reason="other"
        )
    )
    resume_b = ResumeService(
        uow_factory_b,
        DriverIdempotencyStore(neo4j_driver),
        FixedClock(at(15, 0)),
        SequentialIds("tr"),
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
