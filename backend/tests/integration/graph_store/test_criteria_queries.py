"""Integration tests for the criteria candidate and history statements (G11).

They run against the Neo4j that the F10 harness starts for the pytest session, with data written
through the real repositories. The parity test is the proof that the database pre-filter agrees
with the domain filter (check_hard_criteria) on real stored data. The two-tenant test runs on a
contracted container (DEC-159), so two tenants can hold the same service and criteria ids.

Build-wave note: written in the build wave, not run there (build-wave-rules.md). Verification runs
them. All values are synthetic.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from itertools import product
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.criteria_repository import Neo4jCriteriaRepository
from diucs.adapters.outbound.graph_store.flag_repository import Neo4jFlagRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import Neo4jServiceRepository
from diucs.domain.codes import AgeBand, CriteriaStatus, NeedCategory
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import ServiceFlag
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.criteria_filter import check_hard_criteria
from tests.support.neo4j import read_tx, wipe_all, write_tx
from tests.support.tenancy import as_tenant
from tests.support.tenant_seed import contracted_container
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
REVIEW_BY = date(2026, 12, 12)
OWNER = "role-criteria-owner-sample"
DISTRICTS = ("DT1", "DT4")
NEED_SETS: tuple[tuple[NeedCategory, ...], ...] = (
    (NeedCategory.FRAILTY,),
    (NeedCategory.SUSPECTED_FRACTURE,),
    (NeedCategory.FRAILTY, NeedCategory.WOUND_CARE),
)

Work = Callable[[Neo4jCriteriaRepository], Awaitable[Any]]


def _service(service_id: str, *, active: bool = True) -> ServiceProfile:
    return replace(UCR_WEST, id=service_id, name=f"Service {service_id}", active=active)


def _criteria(
    service_id: str,
    *,
    age_min: int,
    age_max: int | None,
    districts: frozenset[str],
    accepts: frozenset[NeedCategory] = frozenset(),
    excludes: frozenset[NeedCategory] = frozenset(),
    version: int = 1,
    status: CriteriaStatus = CriteriaStatus.CURRENT,
    criteria_id: str | None = None,
    supersedes_id: str | None = None,
) -> ServiceCriteria:
    return ServiceCriteria(
        id=criteria_id or f"crit-{service_id}-v{version}",
        service_id=service_id,
        version=version,
        status=status,
        age_min=age_min,
        age_max=age_max,
        districts=districts,
        accepts=accepts,
        excludes=excludes,
        review_by=REVIEW_BY,
        owner_role_id=OWNER,
        change_reason="Sample set-up",
        supersedes_id=supersedes_id,
    )


# Six active services with varied ages, districts, accepted and excluded needs.
_ALL_DISTRICTS = frozenset({"DT1", "DT2", "DT3", "DT4"})
ACTIVE_CRITERIA: dict[str, ServiceCriteria] = {
    "svc-a": _criteria(
        "svc-a",
        age_min=18,
        age_max=None,
        districts=_ALL_DISTRICTS,
        accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
        excludes=frozenset({NeedCategory.SUSPECTED_FRACTURE, NeedCategory.IV_THERAPY}),
    ),
    "svc-b": _criteria(
        "svc-b",
        age_min=16,
        age_max=64,
        districts=frozenset({"DT1", "DT2"}),
        accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.WOUND_CARE}),
    ),
    "svc-c": _criteria(
        "svc-c",
        age_min=65,
        age_max=79,
        districts=frozenset({"DT3", "DT4"}),
        accepts=frozenset({NeedCategory.SUSPECTED_FRACTURE}),
        excludes=frozenset({NeedCategory.FRAILTY}),
    ),
    "svc-d": _criteria(
        "svc-d",
        age_min=80,
        age_max=None,
        districts=frozenset({"DT2", "DT4"}),
        accepts=frozenset({NeedCategory.PALLIATIVE, NeedCategory.DEMENTIA}),
    ),
    "svc-e": _criteria(
        "svc-e",
        age_min=0,
        age_max=15,
        districts=frozenset({"DT4"}),
    ),
    "svc-f": _criteria(
        "svc-f",
        age_min=16,
        age_max=64,
        districts=_ALL_DISTRICTS,
        accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY}),
        excludes=frozenset({NeedCategory.INFECTION_ISOLATION}),
    ),
}


async def _seed(driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        services = Neo4jServiceRepository(tx, ResourceStore(tx))
        criteria = Neo4jCriteriaRepository(tx, ResourceStore(tx))
        for service_id, version_one in ACTIVE_CRITERIA.items():
            await services.save(_service(service_id))
            await criteria.add(version_one)
        await services.save(_service("svc-x", active=False))
        await criteria.add(
            _criteria(
                "svc-x",
                age_min=0,
                age_max=None,
                districts=_ALL_DISTRICTS,
                accepts=frozenset({NeedCategory.FRAILTY}),
            )
        )

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, step: Work) -> Any:
    return await read_tx(driver, lambda tx: step(Neo4jCriteriaRepository(tx, ResourceStore(tx))))


async def _run(driver: AsyncDriver, step: Work) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await step(Neo4jCriteriaRepository(tx, ResourceStore(tx)))

    await write_tx(driver, work)


async def _candidates(
    driver: AsyncDriver,
    band: AgeBand,
    district: str,
    needs: tuple[NeedCategory, ...],
) -> list[ServiceCriteria]:
    return await _read(driver, lambda repo: repo.candidates(band, district, needs))


async def test_the_database_candidates_agree_with_the_domain_filter(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    active = list(ACTIVE_CRITERIA)
    loaded = await _read(neo4j_driver, lambda repo: repo.current_for_services(active))
    assert set(loaded) == set(active)
    for band, district, needs in product(AgeBand, DISTRICTS, NEED_SETS):
        found = await _candidates(neo4j_driver, band, district, needs)
        got = {criteria.service_id for criteria in found}
        expected = {
            service_id
            for service_id, criteria in loaded.items()
            if check_hard_criteria(criteria, band, district, needs).passes
        }
        assert got == expected, (band.value, district, [need.value for need in needs])


async def test_a_suspended_service_leaves_the_candidates_and_returns_when_lifted(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    band, district, needs = AgeBand.A16_64, "DT1", (NeedCategory.FRAILTY,)

    async def ids() -> set[str]:
        found = await _read(neo4j_driver, lambda repo: repo.candidates(band, district, needs))
        return {criteria.service_id for criteria in found}

    before = await ids()
    assert "svc-b" in before

    async def flag(active: bool) -> None:
        async def work(tx: AsyncManagedTransaction) -> None:
            flags = Neo4jFlagRepository(tx, ResourceStore(tx))
            await flags.set_service_flag(
                ServiceFlag(
                    service_id="svc-b",
                    code="suspended",
                    active=active,
                    reason="Sample suspension",
                    actor_id="actor-sample",
                    at=AT,
                )
            )

        await write_tx(neo4j_driver, work)

    await flag(True)
    assert "svc-b" not in await ids()
    await flag(False)
    assert await ids() == before


async def test_a_need_the_service_excludes_removes_it_from_the_candidates(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    # svc-c excludes frailty, svc-a excludes suspected-fracture; both are in DT4 for 65 to 79.
    frailty = await _read(
        neo4j_driver,
        lambda repo: repo.candidates(AgeBand.A65_79, "DT4", (NeedCategory.FRAILTY,)),
    )
    assert "svc-c" not in {c.service_id for c in frailty}
    fracture = await _read(
        neo4j_driver,
        lambda repo: repo.candidates(AgeBand.A65_79, "DT4", (NeedCategory.SUSPECTED_FRACTURE,)),
    )
    assert {c.service_id for c in fracture} == {"svc-c"}


async def test_history_after_approving_v2_and_superseding_v1_reads_v2_then_v1(
    neo4j_driver: AsyncDriver,
) -> None:
    await _seed(neo4j_driver)
    v1 = ACTIVE_CRITERIA["svc-b"]
    v2 = _criteria(
        "svc-b",
        age_min=16,
        age_max=64,
        districts=frozenset({"DT1", "DT2"}),
        accepts=frozenset({NeedCategory.FRAILTY}),
        version=2,
        status=CriteriaStatus.PENDING_APPROVAL,
        supersedes_id=v1.id,
    )
    v1_superseded = replace(v1, status=CriteriaStatus.SUPERSEDED)
    v2_current = replace(v2, status=CriteriaStatus.CURRENT)

    await _run(neo4j_driver, lambda repo: repo.add(v2))
    await _run(neo4j_driver, lambda repo: repo.save(v1_superseded))
    await _run(neo4j_driver, lambda repo: repo.save(v2_current))
    history = await _read(neo4j_driver, lambda repo: repo.history("svc-b"))
    assert [criteria.id for criteria in history] == [v2.id, v1.id]


async def test_an_inactive_service_is_never_a_candidate(neo4j_driver: AsyncDriver) -> None:
    await _seed(neo4j_driver)
    found = await _read(
        neo4j_driver,
        lambda repo: repo.candidates(AgeBand.A0_15, "DT1", (NeedCategory.FRAILTY,)),
    )
    assert "svc-x" not in {criteria.service_id for criteria in found}
    assert found == []


# Two tenants on a private contracted container: the same service and criteria ids in both.
@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


async def _write_as(driver: AsyncDriver, tenant: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        services = Neo4jServiceRepository(tx, ResourceStore(tx))
        await services.save(_service("svc-a"))
        await Neo4jCriteriaRepository(tx, ResourceStore(tx)).add(ACTIVE_CRITERIA["svc-a"])

    with as_tenant(tenant):
        await write_tx(driver, work)


async def _read_as(driver: AsyncDriver, tenant: str, step: Work) -> Any:
    with as_tenant(tenant):
        return await read_tx(
            driver, lambda tx: step(Neo4jCriteriaRepository(tx, ResourceStore(tx)))
        )


async def test_another_tenants_criteria_are_not_candidates_or_history(
    two_tenant_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await wipe_all(two_tenant_driver)
    await _write_as(two_tenant_driver, tenant_id)
    await _write_as(two_tenant_driver, other_tenant_id)

    async def candidates(repo: Neo4jCriteriaRepository) -> list[str]:
        found = await repo.candidates(AgeBand.A16_64, "DT1", (NeedCategory.FRAILTY,))
        return [criteria.id for criteria in found]

    async def history(repo: Neo4jCriteriaRepository) -> list[str]:
        return [criteria.id for criteria in await repo.history("svc-a")]

    # Both tenants hold the same criteria id, so a leak shows as a second entry in the list.
    own = ACTIVE_CRITERIA["svc-a"].id
    assert await _read_as(two_tenant_driver, tenant_id, candidates) == [own]
    assert await _read_as(two_tenant_driver, other_tenant_id, candidates) == [own]
    assert await _read_as(two_tenant_driver, tenant_id, history) == [own]
