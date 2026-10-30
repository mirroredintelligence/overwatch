"""The conftest hooks that give each xdist worker its own tenants (TEN-035). The hooks are called
directly with stand-ins for pytest's config and for xdist's node, so no worker is started."""

import os
from types import SimpleNamespace
from typing import Any

import pytest

from tests import conftest as root_conftest
from tests.support.tenancy import RunIdentity, workerinput_for

CONTROLLER = RunIdentity(pid=4242, started=1_800_000_000, nonce="ab12")
ENV = ("DIUCS_TEST_TENANT", "DIUCS_TEST_OTHER_TENANT", "DIUCS_TEST_NETWORK")


@pytest.fixture(autouse=True)
def _restore_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV:
        monkeypatch.setenv(name, os.environ.get(name, ""))


def _config(**attributes: Any) -> Any:
    return SimpleNamespace(stash=pytest.Stash(), **attributes)


def _identity(config: Any) -> RunIdentity:
    return config.stash[root_conftest._RUN_IDENTITY]


def test_a_session_with_no_workers_makes_one_identity_of_its_own() -> None:
    config = _config()

    root_conftest.pytest_configure(config)

    identity = _identity(config)
    assert identity.worker is None
    assert (identity.pid, identity.started) == (os.getpid(), identity.started)
    assert os.environ["DIUCS_TEST_TENANT"] == identity.tenant_id


def test_a_worker_takes_the_identity_its_controller_sent_for_its_own_number() -> None:
    config = _config(workerinput={**workerinput_for(CONTROLLER), "workerid": "gw3"})

    root_conftest.pytest_configure(config)

    assert _identity(config) == CONTROLLER.for_worker(3)
    assert os.environ["DIUCS_TEST_TENANT"] == CONTROLLER.for_worker(3).tenant_id
    assert os.environ["DIUCS_TEST_OTHER_TENANT"] == CONTROLLER.for_worker(3).other_tenant_id
    assert os.environ["DIUCS_TEST_NETWORK"] == CONTROLLER.for_worker(3).network_id


def test_two_workers_of_one_run_have_different_tenants() -> None:
    tenants = set()
    for worker in ("gw0", "gw1", "gw2"):
        config = _config(workerinput={**workerinput_for(CONTROLLER), "workerid": worker})
        root_conftest.pytest_configure(config)
        tenants.add(_identity(config).tenant_id)

    assert len(tenants) == 3


def test_the_controller_sends_its_identity_to_every_worker_it_starts() -> None:
    config = _config()
    root_conftest.pytest_configure(config)
    node = SimpleNamespace(workerinput={}, config=config)

    root_conftest.pytest_configure_node(node)

    controller = _identity(config)
    assert node.workerinput == workerinput_for(controller)


def test_a_worker_with_a_broken_workerinput_stops_with_a_clear_message() -> None:
    config = _config(workerinput={"workerid": "gw0"})

    with pytest.raises(pytest.UsageError, match="workerinput"):
        root_conftest.pytest_configure(config)


def _item(workers: int | None, *, exclusive: bool) -> Any:
    received = None if workers is None else {"workercount": workers}
    marker = object() if exclusive else None
    return SimpleNamespace(
        config=SimpleNamespace(workerinput=received) if received else SimpleNamespace(),
        get_closest_marker=lambda name: marker if name == "exclusive" else None,
    )


def test_an_exclusive_test_fails_on_a_worker_with_the_commands_to_use_instead() -> None:
    with pytest.raises(pytest.fail.Exception, match="make test-parallel"):
        root_conftest._refuse_exclusive_on_a_worker(_item(4, exclusive=True))


def test_an_ordinary_test_on_a_worker_and_an_exclusive_one_in_a_serial_run_are_left_alone() -> None:
    root_conftest._refuse_exclusive_on_a_worker(_item(4, exclusive=False))
    root_conftest._refuse_exclusive_on_a_worker(_item(None, exclusive=True))
    root_conftest._refuse_exclusive_on_a_worker(_item(1, exclusive=True))
