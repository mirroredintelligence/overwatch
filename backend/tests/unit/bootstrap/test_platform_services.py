"""The services of `/platform` and `/tenant`, wired (TEN-075, TEN-084): the container carries the
platform chain, the ticket store and the cross-tenant guard, the guard is callable, and the process
that serves the app gets both sets of services with the edge told of a status change at once.

No Neo4j is opened: the connection is built and never started.
"""

from typing import Any

import pytest

from diucs.adapters.inbound.fhir_rest.app import create_app
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.platform_audit import Neo4jPlatformAudit
from diucs.adapters.outbound.graph_store.support_ticket_store import Neo4jSupportTickets
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.cross_tenant_guard import CrossTenantGuard
from diucs.application.platform_services import PlatformServices, TenantAdminServices
from diucs.application.use_cases.tenant_offboard import OffboardTenant
from diucs.bootstrap.container import Container, build, build_for_tests
from diucs.bootstrap.platform_services import (
    CONFIGURATION_ROLES,
    build_platform_services,
    build_ticket_services,
    install_platform_routes,
)
from diucs.bootstrap.settings import Settings
from diucs.domain.codes import Role
from diucs.domain.rules.support import SUPPORT_CODE_SECRET

pytestmark = pytest.mark.asyncio(loop_scope="session")

KEY = b"synthetic-platform-key-for-the-wiring-unit-tests-001"


@pytest.fixture
def container() -> Container:
    connection = Neo4jConnection("bolt://localhost:1", "neo4j", "unused-without-a-session")
    return build_for_tests(neo4j=connection, secrets=FixedSecretStore({SUPPORT_CODE_SECRET: KEY}))


async def test_the_container_holds_the_platform_chain_the_ticket_store_and_the_guard(
    container: Container,
) -> None:
    assert isinstance(container.platform_audit, Neo4jPlatformAudit)
    assert isinstance(container.support_tickets, Neo4jSupportTickets)
    assert isinstance(container.cross_tenant_guard, CrossTenantGuard)


async def test_the_guard_is_built_on_the_containers_own_parts(container: Container) -> None:
    guard: Any = container.cross_tenant_guard

    assert guard._platform is container.platform_audit
    assert guard._clock is container.clock
    assert guard._ids is container.ids
    assert guard._cache is container.cache
    assert guard._tenants is container.tenants
    # The support-code key is derived for each tenant, so the guard holds the tenant-keyed store.
    assert guard._secrets is not container.secrets


async def test_the_production_container_wires_them_too() -> None:
    container = build(Settings())
    try:
        assert isinstance(container.platform_audit, Neo4jPlatformAudit)
        assert isinstance(container.cross_tenant_guard, CrossTenantGuard)
        guard: Any = container.cross_tenant_guard
        assert guard._cache is container.cache and guard._platform is container.platform_audit
    finally:
        await container.shutdown()


async def test_the_ticket_services_share_the_containers_guard_and_store(
    container: Container,
) -> None:
    services = build_ticket_services(container)

    for use_case in (
        services.request,
        services.listing,
        services.reading,
        services.cancelling,
        services.opening,
        services.using,
        services.ending,
        services.approving,
        services.refusing,
        services.revoking,
    ):
        assert use_case._guard is container.cross_tenant_guard  # type: ignore[attr-defined]
        assert use_case._tickets is container.support_tickets  # type: ignore[attr-defined]


async def test_the_two_sets_of_services_are_built_on_one_ticket_flow(container: Container) -> None:
    platform, tenant_admin = build_platform_services(container)

    assert isinstance(platform, PlatformServices) and isinstance(tenant_admin, TenantAdminServices)
    assert platform.tickets is not None and tenant_admin.tickets.approving is not None
    assert platform.audit_reader is container.platform_audit
    assert platform.offboard is not None and platform.suspend is not None


async def test_the_administrator_is_the_one_role_that_may_change_the_configuration(
    container: Container,
) -> None:
    _, tenant_admin = build_platform_services(container)

    assert {Role.TENANT_ADMIN} == CONFIGURATION_ROLES
    for use_case in (
        tenant_admin.draft,
        tenant_admin.approve,
        tenant_admin.contact,
        tenant_admin.channel,
        tenant_admin.retention,
        tenant_admin.bind,
        tenant_admin.map_group,
    ):
        assert use_case._roles == CONFIGURATION_ROLES  # type: ignore[attr-defined]


async def test_a_serving_process_installs_both_sets_of_services_on_the_app(
    container: Container,
) -> None:
    app = create_app(container)  # type: ignore[arg-type]

    install_platform_routes(app, container)

    assert isinstance(app.state.platform_services, PlatformServices)
    assert isinstance(app.state.tenant_admin_services, TenantAdminServices)


async def test_a_status_change_tells_the_edge_of_this_process_at_once(
    container: Container,
) -> None:
    app = create_app(container)  # type: ignore[arg-type]
    forgotten: list[str] = []

    class _Gate:
        def forget(self, tenant_id: str) -> None:
            forgotten.append(tenant_id)

    app.state.tenant_gate = _Gate()
    install_platform_routes(app, container)
    platform: PlatformServices = app.state.platform_services

    # the route's offboarding is the one that ends the memberships first (TEN-074), and it moves
    # the record through TEN-075's step, which is the one that tells the edge
    assert isinstance(platform.offboard, OffboardTenant)
    for use_case in (platform.suspend, platform.resume, platform.offboard._start):
        (changed,) = use_case._on_changed  # type: ignore[attr-defined]
        changed("tenant-a")

    assert forgotten == ["tenant-a"] * 3
