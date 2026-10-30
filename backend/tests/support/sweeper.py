"""The orphan-tenant sweeper of the Neo4j test harness (TEN-033, DEC-130 item 9, audit E 3.2).

On a Neo4j that runs share, a run that is killed leaves its tenants behind. A run tenant id carries
the pid and the start of its owner (`RunIdentity`), so a later session can tell whose a leftover is
and remove it. The decision is made from the process table of this machine, so the sweeper is for a
Neo4j that is used from this machine only (the shared container of this harness, a service
container of one CI job); the harness does not sweep an instance on another host (TEN-034).

An owner is alive when its pid exists and that process started no later than the identity says it
did (the identity is made when the run starts, so a process that started after it is a later one
that was handed the same pid). A process table that cannot be read says nothing: that owner is
unknown, and an unknown owner is never swept. Only ids that parse as run ids are ever touched:
`default`, a real tenant's id and every other value stay.
"""

import os
from collections.abc import Callable, Iterable

from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import TransientError

from tests.support.neo4j import read_tx, wipe_tenant
from tests.support.proc import ProcessUnreadable, process_start_marker
from tests.support.tenancy import RunIdentity, parse_run_id

# The identity records `time.time()` when the run began and the kernel records the start of the
# process in whole clock ticks, rounded down from the boot time of a whole second: a few seconds of
# difference either way is not a different process.
START_SLACK_S = 5.0
SWEEP_ATTEMPTS = 5

StartEpoch = Callable[[int], float | None]
OwnerState = Callable[[RunIdentity], bool | None]


def _boot_time() -> int:
    with open("/proc/stat", encoding="ascii") as handle:
        for line in handle:
            if line.startswith("btime "):
                return int(line.split()[1])
    raise OSError("no btime in /proc/stat")


def process_start_epoch(
    pid: int,
    *,
    start_marker: Callable[[int], str | None] = process_start_marker,
    boot_time: Callable[[], int] = _boot_time,
    ticks_per_second: int | None = None,
) -> float | None:
    """When the process started, as seconds since the epoch, or None when it does not exist (or is
    a zombie). Raises ProcessUnreadable when this process cannot say (see `proc`)."""
    marker = start_marker(pid)
    if marker is None:
        return None
    try:
        boot = boot_time()
        ticks = ticks_per_second if ticks_per_second is not None else os.sysconf("SC_CLK_TCK")
        return boot + int(marker) / ticks
    except (OSError, ValueError) as error:
        raise ProcessUnreadable("the boot time of this machine could not be read") from error


def owner_alive(
    identity: RunIdentity, *, start_epoch: StartEpoch = process_start_epoch
) -> bool | None:
    """True when the run's owner is alive, False when it is gone, None when this process cannot
    tell (an unreadable process table): the caller keeps what it cannot judge."""
    try:
        started = start_epoch(identity.pid)
    except ProcessUnreadable:
        return None
    if started is None:
        return False
    return started <= identity.started + START_SLACK_S


def orphan_identities(
    scopes: Iterable[str],
    own: Iterable[RunIdentity] = (),
    owner_state: OwnerState = owner_alive,
) -> list[RunIdentity]:
    """The runs, among the scope ids given, whose owner is gone. A value that is not a run id, the
    caller's own runs (`own`) and a run whose owner is alive or unknown are left out. One entry per
    run, in the order of the run token."""
    mine = {identity.token for identity in own}
    runs: dict[str, RunIdentity] = {}
    for value in scopes:
        identity = parse_run_id(value)
        if identity is not None and identity.token not in mine:
            runs.setdefault(identity.token, identity)
    return [identity for _, identity in sorted(runs.items()) if owner_state(identity) is False]


# One pass over the nodes: only run-shaped ids are asked for, and the registry's directory record
# (which has `id` and no `tenantId`) is read with them.
_SCOPES = (
    "MATCH (n) WHERE n.tenantId STARTS WITH 'tt-' OR n.tenantId STARTS WITH 'net-' "
    "RETURN DISTINCT n.tenantId AS scope "
    "UNION MATCH (t:Tenant) WHERE t.id STARTS WITH 'tt-' RETURN DISTINCT t.id AS scope"
)


async def run_scopes_present(driver: AsyncDriver) -> list[str]:
    """Every run-shaped scope id that has a node, or a directory record, on this database."""

    async def work(tx: AsyncManagedTransaction) -> list[str]:
        rows = await (await tx.run(_SCOPES)).data()
        return [str(row["scope"]) for row in rows]

    return await read_tx(driver, work)


async def sweep_orphan_tenants(
    driver: AsyncDriver,
    own: Iterable[RunIdentity] = (),
    *,
    owner_state: OwnerState = owner_alive,
) -> list[RunIdentity]:
    """Remove the tenants, second tenants and network scopes of every run whose owner is gone, and
    return those runs. Two sessions may sweep at once; a delete that meets the other's (a
    transient error) is tried again."""
    present = await run_scopes_present(driver)
    orphans = orphan_identities(present, own, owner_state)
    for identity in orphans:
        scopes = (identity.tenant_id, identity.other_tenant_id, identity.network_id)
        for attempt in range(SWEEP_ATTEMPTS):
            try:
                await wipe_tenant(driver, *scopes)
                break
            except TransientError:
                if attempt == SWEEP_ATTEMPTS - 1:
                    raise
    return orphans
