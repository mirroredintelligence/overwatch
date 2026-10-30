"""The orphan-tenant sweeper of the Neo4j test harness (TEN-033)."""

from collections.abc import Callable, Iterable

from neo4j import AsyncDriver

from tests.support.neo4j import wipe_tenant
from tests.support.tenancy import RunIdentity

START_SLACK_S = 5.0


def process_start_epoch(pid: int, **_: object) -> float | None:
    raise NotImplementedError


def owner_alive(
    identity: RunIdentity, *, start_epoch: Callable[[int], float | None] = process_start_epoch
) -> bool | None:
    raise NotImplementedError


def orphan_identities(
    scopes: Iterable[str],
    own: Iterable[RunIdentity],
    owner_state: Callable[[RunIdentity], bool | None] = owner_alive,
) -> list[RunIdentity]:
    raise NotImplementedError


async def run_scopes_present(driver: AsyncDriver) -> list[str]:
    raise NotImplementedError


async def sweep_orphan_tenants(
    driver: AsyncDriver,
    own: Iterable[RunIdentity] = (),
    *,
    owner_state: Callable[[RunIdentity], bool | None] = owner_alive,
) -> list[RunIdentity]:
    _ = wipe_tenant
    raise NotImplementedError
