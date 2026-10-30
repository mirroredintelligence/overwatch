"""Which Neo4j the integration harness uses, and how the shared one is looked after (TEN-034,
DEC-130 item 9, amends DEC-008 and DEC-013 item 3).

Three modes. `owned`: a container this session starts and removes, as before (the lifecycle and
schema tests always use one). `shared`: one long-lived container for the machine that every run
uses, each in its own tenants. `attached`: an instance named by the environment
(`DIUCS_TEST_NEO4J_URI`, `_USER`, `_PASSWORD`), for example a CI service. No Docker here: the
runner, the probe, the clock and the lock path are injected.
"""

import os
import subprocess
import threading
from pathlib import Path

import pytest

from tests.support import neo4j as harness
from tests.support.harness_mode import (
    ALLOW_LOCAL_ENV,
    MODE_ENV,
    SHARED_LABEL,
    SHARED_NAME,
    Mode,
    ensure_shared_neo4j,
    remove_shared_neo4j,
    select_mode,
    shared_run_arguments,
)
from tests.support.neo4j import HarnessStartError, ThrowawayNeo4j

CLEAN: dict[str, str] = {}


# select_mode


def test_with_nothing_set_the_harness_uses_the_shared_container() -> None:
    selection = select_mode(CLEAN)

    assert selection.mode is Mode.SHARED
    assert selection.uri is None


@pytest.mark.parametrize("value", ["owned", "OWNED", " owned "])
def test_owned_mode_is_chosen_by_name(value: str) -> None:
    assert select_mode({MODE_ENV: value}).mode is Mode.OWNED


def test_shared_mode_can_be_named() -> None:
    assert select_mode({MODE_ENV: "shared"}).mode is Mode.SHARED


@pytest.mark.parametrize("value", ["attached", "", "own", "docker", "1"])
def test_a_mode_that_is_not_owned_or_shared_is_refused_in_the_config_phase(value: str) -> None:
    with pytest.raises(HarnessStartError) as failure:
        select_mode({MODE_ENV: value})

    assert failure.value.phase == "config"
    assert MODE_ENV in str(failure.value)


def test_a_uri_attaches_the_harness_to_that_instance() -> None:
    selection = select_mode(
        {
            "DIUCS_TEST_NEO4J_URI": "bolt://ci-neo4j:7690",
            "DIUCS_TEST_NEO4J_USER": "tester",
            "DIUCS_TEST_NEO4J_PASSWORD": "s3cret-for-the-test",
        }
    )

    assert selection.mode is Mode.ATTACHED
    assert (selection.uri, selection.user, selection.password) == (
        "bolt://ci-neo4j:7690",
        "tester",
        "s3cret-for-the-test",
    )


def test_the_attached_user_defaults_to_neo4j() -> None:
    selection = select_mode(
        {"DIUCS_TEST_NEO4J_URI": "bolt://localhost:7690", "DIUCS_TEST_NEO4J_PASSWORD": "pw"}
    )

    assert selection.user == "neo4j"


def test_an_attached_uri_with_no_password_is_refused() -> None:
    with pytest.raises(HarnessStartError) as failure:
        select_mode({"DIUCS_TEST_NEO4J_URI": "bolt://localhost:7690"})

    assert failure.value.phase == "config"
    assert "DIUCS_TEST_NEO4J_PASSWORD" in str(failure.value)


@pytest.mark.parametrize("uri", ["http://localhost:7474", "localhost:7690", "ftp://x", "bolt://"])
def test_an_attached_uri_that_is_not_a_bolt_uri_is_refused(uri: str) -> None:
    with pytest.raises(HarnessStartError):
        select_mode({"DIUCS_TEST_NEO4J_URI": uri, "DIUCS_TEST_NEO4J_PASSWORD": "pw"})


@pytest.mark.parametrize("scheme", ["bolt", "neo4j", "bolt+s", "neo4j+s", "bolt+ssc"])
def test_every_bolt_scheme_is_accepted(scheme: str) -> None:
    selection = select_mode(
        {"DIUCS_TEST_NEO4J_URI": f"{scheme}://db.example:7690", "DIUCS_TEST_NEO4J_PASSWORD": "pw"}
    )

    assert selection.mode is Mode.ATTACHED


def test_a_uri_and_an_owned_mode_together_are_refused() -> None:
    with pytest.raises(HarnessStartError, match="both"):
        select_mode(
            {
                MODE_ENV: "owned",
                "DIUCS_TEST_NEO4J_URI": "bolt://localhost:7690",
                "DIUCS_TEST_NEO4J_PASSWORD": "pw",
            }
        )


def test_the_shell_neo4j_uri_is_never_read() -> None:
    """DEC-013 item 3 stands: the old variables name a stack the harness must not touch."""
    selection = select_mode(
        {"NEO4J_URI": "bolt://localhost:7687", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "x"}
    )

    assert selection.mode is Mode.SHARED
    assert selection.uri is None


@pytest.mark.parametrize(
    "uri", ["bolt://localhost:7687", "bolt://127.0.0.1:7687", "neo4j://[::1]:7687"]
)
def test_the_compose_stack_of_the_owner_cannot_be_attached_by_accident(uri: str) -> None:
    with pytest.raises(HarnessStartError, match="compose"):
        select_mode({"DIUCS_TEST_NEO4J_URI": uri, "DIUCS_TEST_NEO4J_PASSWORD": "pw"})


def test_the_compose_port_is_allowed_when_the_caller_says_so() -> None:
    selection = select_mode(
        {
            "DIUCS_TEST_NEO4J_URI": "bolt://localhost:7687",
            "DIUCS_TEST_NEO4J_PASSWORD": "pw",
            ALLOW_LOCAL_ENV: "1",
        }
    )

    assert selection.mode is Mode.ATTACHED


def test_port_7687_on_another_host_is_an_ordinary_instance() -> None:
    selection = select_mode(
        {"DIUCS_TEST_NEO4J_URI": "bolt://neo4j.internal:7687", "DIUCS_TEST_NEO4J_PASSWORD": "pw"}
    )

    assert selection.mode is Mode.ATTACHED


def test_a_selection_never_shows_its_password_in_its_text() -> None:
    selection = select_mode(
        {"DIUCS_TEST_NEO4J_URI": "bolt://db.example:7690", "DIUCS_TEST_NEO4J_PASSWORD": "pw-42-x"}
    )

    assert "pw-42-x" not in repr(selection)
    assert "pw-42-x" not in str(selection)


# the shared container


def test_the_shared_container_is_not_one_the_reaper_can_reach() -> None:
    """The reaper removes `diucs-test=true` containers named `diucs-test-neo4j-*` (DEC-108)."""
    assert not SHARED_NAME.startswith(harness.NAME_PREFIX)
    assert SHARED_LABEL != harness.TEST_LABEL


def test_the_shared_container_is_started_detached_limited_labelled_and_never_auto_removed() -> None:
    arguments = shared_run_arguments("pw-1")

    assert arguments[:2] == ["run", "-d"]
    assert arguments[arguments.index("--name") + 1] == SHARED_NAME
    assert f"{SHARED_LABEL}=true" in arguments
    assert f"{harness.TEST_LABEL}=true" not in arguments
    assert "--rm" not in arguments
    assert "--memory" in arguments
    assert "NEO4J_AUTH=neo4j/pw-1" in arguments
    assert arguments[-1] == harness.NEO4J_IMAGE
    published = arguments[arguments.index("-p") + 1]
    assert published.startswith("127.0.0.1::"), "a random loopback port, read back with inspect"


def test_the_shared_container_has_more_memory_than_a_private_one() -> None:
    arguments = shared_run_arguments("pw-1")
    memory = arguments[arguments.index("--memory") + 1]

    assert int(memory.rstrip("gG")) >= 2
    assert memory != harness.DEFAULT_CONTAINER_MEMORY


def test_the_shared_container_takes_its_limits_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_MEMORY", "3g")
    monkeypatch.setenv("DIUCS_NEO4J_HEAP", "1g")

    arguments = shared_run_arguments("pw-1")

    assert arguments[arguments.index("--memory") + 1] == "3g"
    assert "NEO4J_server_memory_heap_max__size=1g" in arguments


class FakeDocker:
    """The docker calls that look the shared container up, start it and read it back."""

    def __init__(
        self, *, state: str | None, port: str = "49321", password: str = "pw-found", image_ok=True
    ) -> None:
        self.state = state  # None: no container, else running or exited
        self.port = port
        self.password = password
        self.image_ok = image_ok
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        ok, out = True, ""
        if args[:2] == ("image", "inspect"):
            ok = self.image_ok
        elif args[0] == "inspect":
            ok = self.state is not None
            template = args[args.index("-f") + 1] if "-f" in args else ""
            if "State.Status" in template:
                out = self.state or ""
            elif "HostPort" in template:
                out = self.port
            elif "Config.Env" in template:
                out = f"NEO4J_AUTH=neo4j/{self.password}\nPATH=/usr/bin\n"
            else:
                out = ""
        elif args[0] == "run" or args[0] == "start":
            self.state = "running"
        return subprocess.CompletedProcess(
            args=["docker", *args], returncode=0 if ok else 1, stdout=out, stderr=""
        )

    def named(self, command: str) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == command]


@pytest.fixture
def lock_path(tmp_path: Path) -> str:
    return str(tmp_path / "shared-create.lock")


def _ensure(docker: FakeDocker, lock_path: str) -> ThrowawayNeo4j:
    return ensure_shared_neo4j(
        run=docker, probe=lambda container: True, lock_path=lock_path, sleep=lambda s: None
    )


def test_a_running_shared_container_is_used_as_it_is(lock_path: str) -> None:
    docker = FakeDocker(state="running")

    container = _ensure(docker, lock_path)

    assert docker.named("run") == []
    assert docker.named("start") == []
    assert container.name == SHARED_NAME
    assert container.uri == "bolt://127.0.0.1:49321"
    assert (container.user, container.password) == ("neo4j", "pw-found")


def test_a_stopped_shared_container_is_started_and_awaited(lock_path: str) -> None:
    docker = FakeDocker(state="exited")
    probed: list[str] = []

    container = ensure_shared_neo4j(
        run=docker,
        probe=lambda c: probed.append(c.uri) or True,
        lock_path=lock_path,
        sleep=lambda s: None,
    )

    assert docker.named("start") == [("start", SHARED_NAME)]
    assert docker.named("run") == []
    assert probed, "readiness was not awaited after the start"
    assert container.password == "pw-found"


def test_a_missing_shared_container_is_created_once_with_a_fresh_password(lock_path: str) -> None:
    docker = FakeDocker(state=None, password="ignored")

    def created(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        result = docker(*args, timeout=timeout)
        if args[0] == "run":
            docker.password = next(
                a.split("/", 1)[1] for a in args if a.startswith("NEO4J_AUTH=neo4j/")
            )
        return result

    container = ensure_shared_neo4j(
        run=created, probe=lambda c: True, lock_path=lock_path, sleep=lambda s: None
    )

    assert len(docker.named("run")) == 1
    assert container.password == docker.password
    assert len(container.password) >= 16


def test_the_shared_container_is_never_removed_by_looking_after_it(lock_path: str) -> None:
    for state in (None, "running", "exited"):
        docker = FakeDocker(state=state)
        _ensure(docker, lock_path)
        assert docker.named("rm") == []
        assert docker.named("stop") == []


def test_the_image_is_checked_before_a_missing_container_is_created(lock_path: str) -> None:
    docker = FakeDocker(state=None, image_ok=False)

    with pytest.raises(HarnessStartError) as failure:
        _ensure(docker, lock_path)

    assert failure.value.phase in {"image", "docker"}
    assert docker.named("run") == []


def test_two_sessions_looking_for_the_shared_container_create_one_container(
    lock_path: str,
) -> None:
    docker = FakeDocker(state=None)
    seen: list[ThrowawayNeo4j] = []
    gate = threading.Barrier(2)

    def session() -> None:
        gate.wait()
        seen.append(_ensure(docker, lock_path))

    threads = [threading.Thread(target=session) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(docker.named("run")) == 1
    assert {c.uri for c in seen} == {"bolt://127.0.0.1:49321"}


def test_the_creation_lock_is_free_again_afterwards(lock_path: str) -> None:
    import fcntl

    _ensure(FakeDocker(state="running"), lock_path)

    fd = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)


def test_removing_the_shared_container_removes_that_name_and_its_volumes_only() -> None:
    docker = FakeDocker(state="running")

    assert remove_shared_neo4j(run=docker) is True

    assert docker.named("rm") == [("rm", "-f", "-v", SHARED_NAME)]


def test_removing_a_shared_container_that_does_not_exist_is_not_an_error() -> None:
    docker = FakeDocker(state=None)

    assert remove_shared_neo4j(run=docker) is False
    assert docker.named("rm") == []
