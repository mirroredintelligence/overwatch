"""A reference to another tenant's record is refused like a missing one (TEN-029).

It also writes nothing. Tenant B holds a service, a practitioner and a capacity report that
tenant A does not. Tenant A names each of them in every entry point that checks its target
(`CHECKED` in the relationship matrix, `tests/support/relationship_matrix.py`). Each must be
refused with the same message as for an id that exists nowhere, so the refusal does not say that
the id exists elsewhere (audit F 3.4), and neither tenant's graph may change: the attempt is
caught inside its transaction and the transaction commits, so a write made before the refusal
would be kept and show in the digest.
The placeholder entry points are checked for the tenant-local result they have. All values are
synthetic. These tests run on a private container with the superseded keys dropped. NOT RUN in the
W2B build (no Neo4j there).
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.capacity_repository import Neo4jCapacityRepository
from diucs.adapters.outbound.graph_store.flag_repository import Neo4jFlagRepository
from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.push_subscription_repository import (
    Neo4jPushSubscriptionRepository,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scope_list_repository import Neo4jScopeListRepository
from diucs.adapters.outbound.graph_store.service_move_repository import Neo4jServiceMoveRepository
from diucs.adapters.outbound.graph_store.service_repository import codeable_to_fhir
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.application.tenancy import bind_tenant
from diucs.domain.codes import (
    Measure,
    PractitionerRoleCode,
    ReportFlagReason,
    ReportSource,
    ReportType,
    ScopeFlag,
    ServiceCategory,
)
from diucs.domain.errors import DomainError, NotFound
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import (
    REPORT_FLAG_OPEN,
    SERVICE_FLAG_SUSPENDED,
    ReportFlag,
    ServiceFlag,
)
from diucs.domain.model.people import PractitionerRole
from diucs.domain.model.registration import ScopeEntry
from diucs.domain.model.service_move import ServiceMove
from tests.support.neo4j import read_tx, wipe_all, write_tx
from tests.support.relationship_matrix import checked_cases, shape
from tests.support.tenant_seed import (
    Snapshot,
    contracted_container,
    digest,
    invariant_breaks,
    snapshot,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
OWN_SERVICE = "svc-own"
OWN_PRACTITIONER = "p-own"
FOREIGN_SERVICE = "svc-foreign"
FOREIGN_PRACTITIONER = "p-foreign"
FOREIGN_REPORT = "obs-foreign"
MISSING = {"service": "svc-missing", "practitioner": "p-missing", "report": "obs-missing"}
FOREIGN = {
    "service": FOREIGN_SERVICE,
    "practitioner": FOREIGN_PRACTITIONER,
    "report": FOREIGN_REPORT,
}

Attempt = Callable[[AsyncManagedTransaction, str], Awaitable[None]]


def _store(tx: AsyncManagedTransaction) -> ResourceStore:
    return ResourceStore(tx)


async def _capacity(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jCapacityRepository(tx, _store(tx)).add(
        CapacityReport(
            id="obs-new",
            service_id=target,
            value=5,
            measure=Measure.REFERRALS_ACCEPTABLE,
            effective_at=NOW,
            source=ReportSource.LINK,
            report_type=ReportType.NUMBER,
        )
    )


def _role(practitioner: str, service: str, cover: str | None = None) -> PractitionerRole:
    return PractitionerRole(
        id="r-new",
        practitioner_id=practitioner,
        service_id=service,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=None,
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        covered_by_practitioner_id=cover,
        covered_until=None if cover is None else LATER,
    )


async def _role_practitioner(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jPersonRepository(tx, _store(tx)).save_role(_role(target, OWN_SERVICE))


async def _role_service(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jPersonRepository(tx, _store(tx)).save_role(_role(OWN_PRACTITIONER, target))


async def _role_cover(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jPersonRepository(tx, _store(tx)).save_role(
        _role(OWN_PRACTITIONER, OWN_SERVICE, cover=target)
    )


async def _report_flag(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jFlagRepository(tx, _store(tx)).add_report_flag(
        ReportFlag(
            id="rf-new",
            report_id=target,
            service_id=OWN_SERVICE,
            reason=ReportFlagReason.OUT_OF_RANGE_TWICE,
            status=REPORT_FLAG_OPEN,
            created_at=NOW,
        )
    )


async def _service_flag(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jFlagRepository(tx, _store(tx)).set_service_flag(
        ServiceFlag(
            service_id=target,
            code=SERVICE_FLAG_SUSPENDED,
            active=True,
            reason="Staffing shortfall",
            actor_id="role-own",
            at=NOW,
        )
    )


async def _push(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jPushSubscriptionRepository(tx).save(
        PushSubscription(
            device_id="dev-new",
            practitioner_id=target,
            subscription={
                "endpoint": "https://push.example/abc",
                "keys": {"p256dh": "k", "auth": "a"},
            },
            saved_at=NOW,
        )
    )


async def _move_service(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jServiceMoveRepository(tx).add(
        ServiceMove(
            id="move-new",
            service_id=target,
            from_practitioner_id=OWN_PRACTITIONER,
            to_phone_hash="h9",
            until=LATER,
        )
    )


async def _move_practitioner(tx: AsyncManagedTransaction, target: str) -> None:
    await Neo4jServiceMoveRepository(tx).add(
        ServiceMove(
            id="move-new",
            service_id=OWN_SERVICE,
            from_practitioner_id=target,
            to_phone_hash="h9",
            until=LATER,
        )
    )


# Each case of the matrix: the argument kind it names, and the entry point it calls.
CASES: dict[str, tuple[str, Attempt]] = {
    "capacity.add.service": ("service", _capacity),
    "person.save_role.practitioner": ("practitioner", _role_practitioner),
    "person.save_role.service": ("service", _role_service),
    "person.save_role.cover": ("practitioner", _role_cover),
    "flag.add_report_flag.report": ("report", _report_flag),
    "flag.set_service_flag.service": ("service", _service_flag),
    "push.save.practitioner": ("practitioner", _push),
    "move.add.service": ("service", _move_service),
    "move.add.practitioner": ("practitioner", _move_practitioner),
}


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def two(two_tenant_driver: AsyncDriver) -> AsyncIterator[AsyncDriver]:
    await wipe_all(two_tenant_driver)
    yield two_tenant_driver
    await wipe_all(two_tenant_driver)


async def _as(driver: AsyncDriver, tenant: str, step: Callable[..., Awaitable[None]]) -> None:
    with bind_tenant(tenant):
        await write_tx(driver, step)


async def _put_service(tx: AsyncManagedTransaction, service_id: str) -> None:
    await _store(tx).put(
        {
            "resourceType": "HealthcareService",
            "id": service_id,
            "active": True,
            "name": f"Sample service {service_id}",
            "category": codeable_to_fhir(ServiceCategory.URGENT_COMMUNITY_RESPONSE),
        },
        None,
    )


async def _put_practitioner(tx: AsyncManagedTransaction, practitioner_id: str) -> None:
    await _store(tx).put(
        {"resourceType": "Practitioner", "id": practitioner_id, "active": True}, None
    )


async def _seed(driver: AsyncDriver, tenant: str, other: str) -> None:
    """Tenant `tenant` holds its own service and practitioner; `other` holds the foreign ones and a
    capacity report of its service."""

    async def own(tx: AsyncManagedTransaction) -> None:
        await _put_service(tx, OWN_SERVICE)
        await _put_practitioner(tx, OWN_PRACTITIONER)

    async def foreign(tx: AsyncManagedTransaction) -> None:
        await _put_service(tx, FOREIGN_SERVICE)
        await _put_practitioner(tx, FOREIGN_PRACTITIONER)
        await Neo4jCapacityRepository(tx, _store(tx)).add(
            CapacityReport(
                id=FOREIGN_REPORT,
                service_id=FOREIGN_SERVICE,
                value=3,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=NOW,
                source=ReportSource.LINK,
                report_type=ReportType.NUMBER,
            )
        )

    await _as(driver, tenant, own)
    await _as(driver, other, foreign)


async def _snapshots(driver: AsyncDriver, a: str, b: str) -> tuple[str, str]:
    async def work(tx: AsyncManagedTransaction) -> tuple[Snapshot, Snapshot]:
        return await snapshot(tx, a), await snapshot(tx, b)

    snap_a, snap_b = await read_tx(driver, work)
    return digest(snap_a), digest(snap_b)


async def _refusal(
    driver: AsyncDriver, tenant: str, attempt: Attempt, target: str
) -> DomainError | None:
    """Run the attempt as `tenant` and commit, whatever the outcome. The refusal is caught inside
    the transaction, so anything written before it is kept and shows in the digest."""
    caught: list[DomainError] = []

    async def work(tx: AsyncManagedTransaction) -> None:
        try:
            await attempt(tx, target)
        except DomainError as error:
            caught.append(error)

    await _as(driver, tenant, work)
    return caught[0] if caught else None


def test_every_case_of_the_matrix_has_an_entry_point_and_no_other_has() -> None:
    assert set(CASES) == set(checked_cases())


@pytest.mark.parametrize("case", sorted(CASES))
async def test_a_foreign_record_is_refused_like_a_missing_one_and_nothing_is_written(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str, case: str
) -> None:
    kind, attempt = CASES[case]
    await _seed(two, tenant_id, other_tenant_id)
    before = await _snapshots(two, tenant_id, other_tenant_id)

    foreign = await _refusal(two, tenant_id, attempt, FOREIGN[kind])
    missing = await _refusal(two, tenant_id, attempt, MISSING[kind])

    assert isinstance(foreign, NotFound), "a foreign record was not refused as missing"
    assert isinstance(missing, NotFound), "a missing record was not refused as missing"
    assert shape(foreign, *FOREIGN.values()) == shape(missing, *MISSING.values())
    assert await _snapshots(two, tenant_id, other_tenant_id) == before

    assert await read_tx(two, invariant_breaks) == ([], [])


@pytest.mark.parametrize("case", sorted(CASES))
async def test_the_own_record_is_accepted_where_the_foreign_one_is_refused(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str, case: str
) -> None:
    """The refusal is about whose record it is: the same call with the tenant's own record is not
    refused as missing (it may be refused for another reason, never NotFound)."""
    kind, attempt = CASES[case]
    await _seed(two, tenant_id, other_tenant_id)
    own = {"service": OWN_SERVICE, "practitioner": OWN_PRACTITIONER}
    if kind == "report":
        await _as(
            two,
            tenant_id,
            lambda tx: Neo4jCapacityRepository(tx, _store(tx)).add(
                CapacityReport(
                    id="obs-own",
                    service_id=OWN_SERVICE,
                    value=2,
                    measure=Measure.REFERRALS_ACCEPTABLE,
                    effective_at=NOW,
                    source=ReportSource.LINK,
                    report_type=ReportType.NUMBER,
                )
            ),
        )
        own["report"] = "obs-own"

    assert not isinstance(await _refusal(two, tenant_id, attempt, own[kind]), NotFound)


async def test_a_scope_entry_for_a_service_only_the_other_tenant_holds_makes_the_tenants_own(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """`ENTRY` is a placeholder entry point: the entry is not refused, and the service it names is
    the tenant's own new node. Nothing of tenant B changes and nothing joins the two."""
    await _seed(two, tenant_id, other_tenant_id)
    _, before_b = await _snapshots(two, tenant_id, other_tenant_id)

    async def mine(tx: AsyncManagedTransaction) -> None:
        await Neo4jScopeListRepository(tx, _store(tx)).save_entry(
            ScopeEntry(
                service_id=FOREIGN_SERVICE,
                name="Mine",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=date(2026, 10, 25),
            )
        )

    await _as(two, tenant_id, mine)

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, object]]:
        result = await tx.run(
            "MATCH (:List {tenantId: $tenant})-[:ENTRY]->(s:HealthcareService) "
            "RETURN s.id AS id, s.tenantId AS tenant",
            tenant=tenant_id,
        )
        return await result.data()

    assert await read_tx(two, work) == [{"id": FOREIGN_SERVICE, "tenant": tenant_id}]
    assert (await _snapshots(two, tenant_id, other_tenant_id))[1] == before_b

    assert await read_tx(two, invariant_breaks) == ([], [])
