"""The orphan-tenant sweeper (TEN-033, DEC-130 item 9, audit E 3.2 and TEN-E11).

A run that dies leaves its tenants behind on a shared Neo4j. A run tenant id carries the pid and the
start of its owner and a nonce (`RunIdentity`), so a later session can tell whose a leftover is. The
rules proved here, with no Docker and no process of its own:

* an owner is alive when its pid exists and that process started no later than the identity says it
  did (a pid reused later started after the identity was made);
* an owner that cannot be seen (an unreadable process table) is unknown, and unknown is never swept;
* the sweeper finds run ids only: `default`, a real tenant id and anything else is never touched;
* the three ids of one run (tenant, second tenant, network) go together, and the caller's own run
  and every run whose owner is alive stay.
"""

from collections.abc import Iterable

import pytest

from tests.support import sweeper
from tests.support.proc import ProcessUnreadable
from tests.support.sweeper import (
    START_SLACK_S,
    orphan_identities,
    owner_alive,
    process_start_epoch,
    sweep_orphan_tenants,
)
from tests.support.tenancy import RunIdentity, new_run_identity

STARTED = 1_800_000_000
DEAD = RunIdentity(pid=4_000_001, started=STARTED, nonce="d0d0")
LIVE = RunIdentity(pid=4242, started=STARTED, nonce="a11e")
OWN = RunIdentity(pid=7, started=STARTED, nonce="0abc")
UNSEEN = RunIdentity(pid=99, started=STARTED, nonce="beef")


def _table(entries: dict[int, float | None | type[Exception]]):
    """A process table: pid -> start epoch, None (gone) or an exception class (cannot be read)."""

    def start_epoch(pid: int) -> float | None:
        entry = entries[pid]
        if isinstance(entry, type):
            raise entry("cannot read")
        return entry

    return start_epoch


# owner_alive


def test_an_owner_whose_process_started_before_the_identity_was_made_is_alive() -> None:
    table = _table({4242: STARTED - 3.0})

    assert owner_alive(LIVE, start_epoch=table) is True


def test_an_owner_whose_process_started_a_moment_after_is_still_alive_within_the_slack() -> None:
    table = _table({4242: STARTED + START_SLACK_S - 1})

    assert owner_alive(LIVE, start_epoch=table) is True


def test_a_pid_reused_by_a_process_that_started_later_is_a_dead_owner() -> None:
    table = _table({4242: STARTED + START_SLACK_S + 60})

    assert owner_alive(LIVE, start_epoch=table) is False


def test_a_pid_that_does_not_exist_is_a_dead_owner() -> None:
    assert owner_alive(DEAD, start_epoch=_table({4_000_001: None})) is False


def test_a_process_table_that_will_not_say_is_unknown_not_dead() -> None:
    assert owner_alive(UNSEEN, start_epoch=_table({99: ProcessUnreadable})) is None


def test_an_owner_is_judged_from_its_pid_and_start_only() -> None:
    same_owner = RunIdentity(pid=4242, started=STARTED, nonce="ffff")

    table = _table({4242: STARTED - 1.0})
    assert owner_alive(same_owner, start_epoch=table) is owner_alive(LIVE, start_epoch=table)


# process_start_epoch


def test_the_start_epoch_is_the_boot_time_plus_the_start_ticks_over_the_clock_rate() -> None:
    epoch = process_start_epoch(
        4242,
        start_marker=lambda pid: "12345",
        boot_time=lambda: 1_700_000_000,
        ticks_per_second=100,
    )

    assert epoch == pytest.approx(1_700_000_000 + 123.45)


def test_the_start_epoch_of_a_gone_process_is_none() -> None:
    assert (
        process_start_epoch(
            4242, start_marker=lambda pid: None, boot_time=lambda: 1, ticks_per_second=100
        )
        is None
    )


def test_a_boot_time_that_cannot_be_read_is_unreadable() -> None:
    def no_boot() -> int:
        raise OSError("no /proc/stat")

    with pytest.raises(ProcessUnreadable):
        process_start_epoch(
            4242, start_marker=lambda pid: "1", boot_time=no_boot, ticks_per_second=100
        )


def test_this_process_started_before_now_and_is_seen_as_alive_by_its_own_identity() -> None:
    mine = new_run_identity()

    assert owner_alive(mine) is True


def test_a_pid_beyond_the_kernel_limit_is_a_dead_owner() -> None:
    far = RunIdentity(pid=4_194_303, started=STARTED, nonce="0000")

    assert owner_alive(far) is False


# orphan_identities


def _scopes(*identities: RunIdentity) -> list[str]:
    out: list[str] = []
    for identity in identities:
        out += [identity.tenant_id, identity.other_tenant_id, identity.network_id]
    return out


def _state(alive: set[RunIdentity], unknown: Iterable[RunIdentity] = ()):
    unseen = set(unknown)

    def state(identity: RunIdentity) -> bool | None:
        if identity in unseen:
            return None
        return identity in alive

    return state


def test_a_run_with_a_dead_owner_is_an_orphan_once_however_many_of_its_ids_are_present() -> None:
    found = orphan_identities(_scopes(DEAD), own=(OWN,), owner_state=_state(set()))

    assert found == [DEAD]


def test_a_run_whose_owner_is_alive_is_kept() -> None:
    found = orphan_identities(_scopes(LIVE, DEAD), own=(OWN,), owner_state=_state({LIVE}))

    assert found == [DEAD]


def test_the_callers_own_run_is_never_an_orphan_even_when_it_looks_dead() -> None:
    found = orphan_identities(_scopes(OWN), own=(OWN,), owner_state=_state(set()))

    assert found == []


def test_a_run_whose_owner_cannot_be_seen_is_kept() -> None:
    found = orphan_identities(
        _scopes(UNSEEN), own=(OWN,), owner_state=_state(set(), unknown=[UNSEEN])
    )

    assert found == []


@pytest.mark.parametrize(
    "value",
    [
        "default",
        "example-icb",
        "tenant-a",
        "sb12345678-integ-a",
        "tt-zz",
        "net-zz",
        "",
        "tt-1-2-xyz",
    ],
)
def test_ids_that_are_not_run_ids_are_never_orphans(value: str) -> None:
    assert orphan_identities([value], own=(), owner_state=_state(set())) == []


def test_the_result_is_in_a_stable_order_and_has_no_duplicates() -> None:
    other_dead = RunIdentity(pid=4_000_002, started=STARTED, nonce="0001")

    found = orphan_identities(_scopes(other_dead, DEAD, DEAD), own=(), owner_state=_state(set()))

    assert found == sorted({DEAD, other_dead}, key=lambda i: i.token)


def test_a_second_tenant_id_alone_still_names_its_run() -> None:
    found = orphan_identities([DEAD.other_tenant_id], own=(), owner_state=_state(set()))

    assert found == [DEAD]


# sweep_orphan_tenants


async def test_the_sweep_wipes_the_three_ids_of_each_orphan_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wiped: list[tuple[str, ...]] = []

    async def present(driver: object) -> list[str]:
        return [*_scopes(DEAD, LIVE, OWN), "default", "example-icb"]

    async def wipe(driver: object, *scopes: str) -> None:
        wiped.append(scopes)

    monkeypatch.setattr(sweeper, "run_scopes_present", present)
    monkeypatch.setattr(sweeper, "wipe_tenant", wipe)

    swept = await sweep_orphan_tenants(object(), own=(OWN,), owner_state=_state({LIVE}))  # type: ignore[arg-type]

    assert swept == [DEAD]
    assert wiped == [(DEAD.tenant_id, DEAD.other_tenant_id, DEAD.network_id)]


async def test_the_sweep_sends_nothing_to_wipe_when_there_is_no_orphan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def present(driver: object) -> list[str]:
        return _scopes(LIVE, OWN)

    async def wipe(driver: object, *scopes: str) -> None:
        raise AssertionError("nothing should be wiped")

    monkeypatch.setattr(sweeper, "run_scopes_present", present)
    monkeypatch.setattr(sweeper, "wipe_tenant", wipe)

    assert await sweep_orphan_tenants(object(), own=(OWN,), owner_state=_state({LIVE})) == []  # type: ignore[arg-type]
