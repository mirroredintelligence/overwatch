"""Worker tenants for parallel runs (TEN-035, DEC-130 item 9, audit E 3.2).

Under pytest-xdist the controller makes one run identity and sends it to each worker in
`workerinput`; a worker derives its own identity from it and the worker's number. So every worker
has a tenant, a second tenant and a network scope of its own; all of them carry the controller's
pid and start, so the orphan sweeper (TEN-033) finds them when the controller dies; and no tenant is
ever derived from the worker number alone, which would collide across runs.
"""

import pytest

from diucs.application.tenancy import is_valid_tenant_id
from tests.support.sweeper import orphan_identities
from tests.support.tenancy import (
    RunIdentity,
    identity_from_workerinput,
    parse_run_id,
    workerinput_for,
)

CONTROLLER = RunIdentity(pid=4242, started=1_800_000_000, nonce="ab12")


def test_each_worker_has_ids_of_its_own() -> None:
    workers = [CONTROLLER.for_worker(index) for index in range(8)]

    scopes = [scope for worker in workers for scope in worker.scope_ids]
    assert len(scopes) == len(set(scopes)) == 24


def test_a_worker_is_never_the_controller() -> None:
    controller = set(CONTROLLER.scope_ids)

    assert all(not controller & set(CONTROLLER.for_worker(i).scope_ids) for i in range(8))


def test_a_workers_ids_are_valid_scope_ids_within_the_length_limit() -> None:
    for index in (0, 1, 7, 63, 255):
        for scope in CONTROLLER.for_worker(index).scope_ids:
            assert len(scope) <= 31
        assert is_valid_tenant_id(CONTROLLER.for_worker(index).tenant_id)
        assert is_valid_tenant_id(CONTROLLER.for_worker(index).other_tenant_id)


def test_a_workers_ids_parse_back_to_an_identity_with_the_controllers_owner() -> None:
    for index in range(4):
        worker = CONTROLLER.for_worker(index)
        for scope in worker.scope_ids:
            parsed = parse_run_id(scope)
            assert parsed == worker
            assert (parsed.pid, parsed.started) == (CONTROLLER.pid, CONTROLLER.started)


def test_the_same_worker_of_the_same_run_always_gets_the_same_identity() -> None:
    assert CONTROLLER.for_worker(3) == CONTROLLER.for_worker(3)


def test_the_same_worker_number_in_two_runs_gives_different_ids() -> None:
    other_run = RunIdentity(pid=4243, started=1_800_000_000, nonce="ab12")
    same_pid_later = RunIdentity(pid=4242, started=1_800_000_500, nonce="ab12")

    for other in (other_run, same_pid_later, RunIdentity(4242, 1_800_000_000, "ab13")):
        assert not set(CONTROLLER.for_worker(2).scope_ids) & set(other.for_worker(2).scope_ids)


def test_workers_of_a_dead_controller_are_all_orphans_and_a_live_ones_are_not() -> None:
    scopes = [scope for i in range(4) for scope in CONTROLLER.for_worker(i).scope_ids]

    dead = orphan_identities(scopes, owner_state=lambda identity: False)
    alive = orphan_identities(scopes, owner_state=lambda identity: True)

    assert dead == sorted(
        (CONTROLLER.for_worker(i) for i in range(4)), key=lambda identity: identity.token
    )
    assert alive == []


@pytest.mark.parametrize("index", [-1, 4096, 2**20])
def test_a_worker_number_out_of_range_is_refused(index: int) -> None:
    with pytest.raises(ValueError, match="worker"):
        CONTROLLER.for_worker(index)


def test_a_worker_number_that_is_not_a_whole_number_is_refused() -> None:
    with pytest.raises(ValueError, match="worker"):
        CONTROLLER.for_worker(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="worker"):
        CONTROLLER.for_worker(1.5)  # type: ignore[arg-type]


# workerinput


def test_the_controllers_identity_travels_to_a_worker_in_plain_values() -> None:
    sent = workerinput_for(CONTROLLER)

    assert sent == {"diucs_run": [4242, 1_800_000_000, "ab12"]}


def test_a_worker_derives_its_identity_from_the_input_and_its_id() -> None:
    received = {**workerinput_for(CONTROLLER), "workerid": "gw3"}

    assert identity_from_workerinput(received) == CONTROLLER.for_worker(3)


def test_each_worker_id_gives_its_own_identity() -> None:
    identities = {
        identity_from_workerinput({**workerinput_for(CONTROLLER), "workerid": f"gw{i}"})
        for i in range(5)
    }

    assert len(identities) == 5


@pytest.mark.parametrize(
    "received",
    [
        {},
        {"workerid": "gw0"},
        {"diucs_run": [1, 2, "0000"]},
        {"diucs_run": "4242", "workerid": "gw0"},
        {"diucs_run": [4242, 1_800_000_000], "workerid": "gw0"},
        {"diucs_run": [4242, 1_800_000_000, "zzzz"], "workerid": "gw0"},
        {"diucs_run": [4242, 1_800_000_000, "ab12"], "workerid": "master"},
        {"diucs_run": [4242, 1_800_000_000, "ab12"], "workerid": "gw-1"},
        {"diucs_run": [True, 1_800_000_000, "ab12"], "workerid": "gw0"},
    ],
)
def test_a_workerinput_that_does_not_name_a_run_and_a_worker_is_refused(
    received: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="workerinput"):
        identity_from_workerinput(received)
