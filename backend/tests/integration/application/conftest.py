"""Shared seeding for the application (use case) integration tests.

Seeding runs inside the test body, after clean_graph has wiped the graph, so the seeded data is
never removed by the wipe (lesson L84).
"""

from collections.abc import Awaitable, Callable

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.model.flags import ServiceFlag
from diucs.domain.model.service import ServiceProfile

Seed = Callable[..., Awaitable[None]]


@pytest.fixture
def seed_service(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver) -> Seed:
    """Commit a service profile and optional service flags in one committed unit of work.

    The audit chain head is created here too, because clean_graph wipes it with everything else
    (ensure_audit_head is idempotent).
    """

    async def seed(*profiles: ServiceProfile, flags: tuple[ServiceFlag, ...] = ()) -> None:
        await ensure_audit_head(neo4j_driver)
        async with uow_factory() as uow:
            for profile in profiles:
                await uow.services.save(profile)
            for flag in flags:
                await uow.flags.set_service_flag(flag)
            await uow.commit()

    return seed
