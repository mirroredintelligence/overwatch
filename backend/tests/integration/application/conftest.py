"""Shared seeding for the application (use case) integration tests.

Seeding runs inside the test body, after clean_graph has wiped the graph, so the seeded data is
never removed by the wipe (lesson L84).
"""

from collections.abc import Awaitable, Callable

import pytest
from neo4j import AsyncDriver

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.model.flags import ServiceFlag
from diucs.domain.model.service import ServiceProfile
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

Seed = Callable[..., Awaitable[None]]


@pytest.fixture
def seed_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, uow_clock: Clock
) -> Seed:
    """Commit a service profile and optional service flags in one committed unit of work, in the
    tenant bound now, or in `tenant` when one is given (the second tenant of a cross-tenant test).

    The run tenant's audit chain head is made by clean_graph (TEN-033); another tenant's is made
    here, because the wipe never makes more than the run's own two (ensure_audit_heads is
    idempotent).
    """

    async def seed(
        *profiles: ServiceProfile, flags: tuple[ServiceFlag, ...] = (), tenant: str | None = None
    ) -> None:
        factory = uow_factory
        if tenant is not None:
            await ensure_audit_heads(neo4j_driver, tenant)
            factory = tenant_uow_factory(neo4j_driver, tenant, uow_clock)
        async with factory() as uow:
            for profile in profiles:
                await uow.services.save(profile)
            for flag in flags:
                await uow.flags.set_service_flag(flag)
            await uow.commit()

    return seed
