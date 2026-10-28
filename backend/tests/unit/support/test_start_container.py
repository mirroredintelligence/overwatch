"""How the harness starts its Neo4j container (F10b, DEC-135): the lock, the memory limits, the
owner labels, the image check, and the Bolt readiness probe with its failure paths. No Docker and no
real waiting: the Docker runner, the probe, the clock and the sleep are all injected."""

import fcntl
import os
import re
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support import harness_lock
from tests.support import neo4j as harness
from tests.support.neo4j import (
    NEO4J_IMAGE,
    HarnessStartError,
    Neo4jNotRunning,
    ThrowawayNeo4j,
    bolt_ready,
    owner_labels,
    start_throwaway_neo4j,
    stop_throwaway_neo4j,
    wait_until_ready,
)
from tests.support.proc import process_start_marker

ENV_NAMES = (
    "DIUCS_NEO4J_MEMORY",
    "DIUCS_NEO4J_HEAP",
    "DIUCS_NEO4J_PAGECACHE",
    "DIUCS_NEO4J_READY_TIMEOUT",
    "DIUCS_NEO4J_LOCK_TIMEOUT",
)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("DIUCS_NEO4J_LOCK", str(tmp_path / "harness.lock"))
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield
    harness_lock.release_all()


class FakeClock:
    def __init__(self) -> None:
        self.now = 5000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeDocker:
    """Answers the docker calls the harness makes and records each call with its timeout."""

    def __init__(
        self,
        clock: FakeClock,
        *,
        image_present: bool = True,
        pull_ok: bool = True,
        run_ok: bool = True,
        pull_seconds: float = 0.0,
    ) -> None:
        self.clock = clock
        self.image_present = image_present
        self.pull_ok = pull_ok
        self.run_ok = run_ok
        self.pull_seconds = pull_seconds
        self.calls: list[tuple[str, ...]] = []
        self.timeouts: dict[str, float] = {}

    def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        self.timeouts[args[0]] = timeout
        ok = True
        stderr = ""
        if args[:2] == ("image", "inspect"):
            ok = self.image_present
        elif args[0] == "pull":
            self.clock.now += self.pull_seconds
            ok = self.pull_ok
            stderr = "pull access denied"
        elif args[0] == "run":
            ok = self.run_ok
            stderr = "port is already allocated\nsecond line"
        return subprocess.CompletedProcess(
            args=["docker", *args], returncode=0 if ok else 1, stdout="", stderr=stderr
        )

    def named(self, command: str) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] == command]

    def run_args(self) -> tuple[str, ...]:
        (call,) = self.named("run")
        return call

    def container_name(self) -> str:
        args = self.run_args()
        return args[args.index("--name") + 1]

    def removals(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[:3] == ("rm", "-f", "-v")]


class ScriptedProbe:
    """A readiness probe that answers from a list, then keeps giving the same answer."""

    def __init__(self, clock: FakeClock, answers: list[bool], then: bool = False) -> None:
        self.clock = clock
        self.answers = list(answers)
        self.then = then
        self.at: list[float] = []

    def __call__(self, container: ThrowawayNeo4j) -> bool:
        self.at.append(self.clock.now)
        return self.answers.pop(0) if self.answers else self.then


def _start(docker: FakeDocker, probe: ScriptedProbe, clock: FakeClock) -> harness.ThrowawayNeo4j:
    return start_throwaway_neo4j(run=docker, probe=probe, clock=clock, sleep=clock.sleep)


def _lock_is_free(tmp_path: Path) -> bool:
    fd = os.open(tmp_path / "harness.lock", os.O_RDWR | os.O_CREAT, 0o666)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(fd)


def _values(args: tuple[str, ...], flag: str) -> list[str]:
    return [args[i + 1] for i, arg in enumerate(args) if arg == flag]


def _megabytes(size: str) -> int:
    match = re.fullmatch(r"(\d+)([mg])", size.lower())
    assert match, size
    return int(match.group(1)) * (1024 if match.group(2) == "g" else 1)


# ---- the image is checked before the readiness clock starts ---------------------------------


@pytest.mark.parametrize("present", [True, False])
def test_the_image_is_inspected_first_and_pulled_only_when_it_is_missing(present: bool) -> None:
    clock = FakeClock()
    docker = FakeDocker(clock, image_present=present)

    _start(docker, ScriptedProbe(clock, [True]), clock)

    assert docker.calls[0] == ("image", "inspect", NEO4J_IMAGE)
    pulls = docker.named("pull")
    assert pulls == ([] if present else [("pull", NEO4J_IMAGE)])
    order = [call[0] for call in docker.calls]
    assert order.index("run") > order.index("image")
    if not present:
        assert order.index("pull") < order.index("run")


def test_the_pull_has_a_long_timeout_and_the_run_does_not_wait_for_a_pull() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock, image_present=False)

    _start(docker, ScriptedProbe(clock, [True]), clock)

    assert docker.timeouts["pull"] >= 600
    assert docker.timeouts["run"] <= 180  # a run that starts a present image is quick


def test_a_slow_image_pull_does_not_use_up_the_readiness_time() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock, image_present=False, pull_seconds=500.0)
    probe = ScriptedProbe(clock, [False] * 5, then=True)

    container = _start(docker, probe, clock)  # the pull alone took four times the 120 s limit

    assert container.name == docker.container_name()
    assert len(probe.at) == 6
    assert probe.at[-1] - probe.at[0] < 60


def test_a_missing_image_that_cannot_be_pulled_fails_in_the_image_phase(tmp_path: Path) -> None:
    clock = FakeClock()
    docker = FakeDocker(clock, image_present=False, pull_ok=False)

    with pytest.raises(HarnessStartError) as excinfo:
        _start(docker, ScriptedProbe(clock, [True]), clock)

    assert excinfo.value.phase == "image"
    assert "image" in str(excinfo.value)
    assert "pull access denied" in str(excinfo.value)
    assert docker.named("run") == []
    assert _lock_is_free(tmp_path)


# ---- Bolt readiness ---------------------------------------------------------------------------


def test_readiness_is_a_bolt_probe_and_never_a_docker_exec_of_cypher_shell() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)
    probe = ScriptedProbe(clock, [False, False, True])

    container = _start(docker, probe, clock)

    assert len(probe.at) == 3
    assert [call for call in docker.calls if call[0] == "exec"] == []
    assert container.uri.startswith("bolt://127.0.0.1:")
    assert docker.run_args().count(f"127.0.0.1:{container.uri.rsplit(':', 1)[1]}:7687") == 1


def test_the_probe_backs_off_and_does_not_hammer_a_starting_server() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)
    probe = ScriptedProbe(clock, [False] * 40, then=True)

    _start(docker, probe, clock)

    assert all(0.1 <= pause <= 5.0 for pause in clock.sleeps)
    assert max(clock.sleeps) > min(clock.sleeps)


def test_a_server_that_never_answers_fails_in_the_ready_phase_and_the_container_is_removed(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)
    probe = ScriptedProbe(clock, [])

    with pytest.raises(HarnessStartError) as excinfo:
        _start(docker, probe, clock)

    name = docker.container_name()
    assert excinfo.value.phase == "ready"
    assert "ready" in str(excinfo.value)
    assert name in str(excinfo.value)
    assert "120" in str(excinfo.value)
    assert isinstance(excinfo.value, Neo4jNotRunning)
    assert docker.removals() == [("rm", "-f", "-v", name)]
    assert 120 <= probe.at[-1] - probe.at[0] <= 125
    assert _lock_is_free(tmp_path)


def test_the_readiness_limit_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_READY_TIMEOUT", "30")
    clock = FakeClock()
    probe = ScriptedProbe(clock, [])

    with pytest.raises(HarnessStartError, match="30"):
        _start(FakeDocker(clock), probe, clock)

    assert 30 <= probe.at[-1] - probe.at[0] <= 35


def test_wait_until_ready_returns_when_the_probe_says_yes_and_removes_nothing() -> None:
    clock = FakeClock()
    probe = ScriptedProbe(clock, [False, True])
    container = ThrowawayNeo4j("diucs-test-neo4j-x", "bolt://127.0.0.1:1", "neo4j", "pw")

    wait_until_ready(container, probe=probe, clock=clock, sleep=clock.sleep, timeout_s=10)

    assert len(probe.at) == 2


def test_wait_until_ready_raises_after_its_limit_and_leaves_the_container_to_the_caller() -> None:
    clock = FakeClock()
    probe = ScriptedProbe(clock, [])
    container = ThrowawayNeo4j("diucs-test-neo4j-x", "bolt://127.0.0.1:1", "neo4j", "pw")

    with pytest.raises(Neo4jNotRunning, match="diucs-test-neo4j-x"):
        wait_until_ready(container, probe=probe, clock=clock, sleep=clock.sleep, timeout_s=10)

    assert 10 <= probe.at[-1] - probe.at[0] <= 12


def test_the_real_probe_says_no_at_once_when_nothing_listens() -> None:
    container = ThrowawayNeo4j("diucs-test-neo4j-x", "bolt://127.0.0.1:1", "neo4j", "pw")
    began = time.monotonic()

    assert bolt_ready(container) is False

    assert time.monotonic() - began < 10


# ---- the docker run itself --------------------------------------------------------------------


def test_the_container_gets_a_memory_limit_and_neo4j_heap_and_page_cache_settings() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)

    _start(docker, ScriptedProbe(clock, [True]), clock)

    args = docker.run_args()
    env = _values(args, "-e")
    assert _values(args, "--memory") == [harness.DEFAULT_CONTAINER_MEMORY]
    assert "NEO4J_server_memory_heap_initial__size=" + harness.DEFAULT_HEAP in env
    assert "NEO4J_server_memory_heap_max__size=" + harness.DEFAULT_HEAP in env
    assert "NEO4J_server_memory_pagecache_size=" + harness.DEFAULT_PAGECACHE in env
    assert any(value.startswith("NEO4J_AUTH=neo4j/") for value in env)
    assert "--rm" not in args  # restartable (F11)


def test_the_default_limits_are_small_and_heap_and_page_cache_fit_inside_the_container() -> None:
    memory = _megabytes(harness.DEFAULT_CONTAINER_MEMORY)
    heap = _megabytes(harness.DEFAULT_HEAP)
    pagecache = _megabytes(harness.DEFAULT_PAGECACHE)

    assert memory <= 1024
    assert heap + pagecache < memory
    assert memory - (heap + pagecache) >= 128  # room for metaspace, direct buffers and the JVM


def test_the_limits_can_be_raised_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_MEMORY", "2g")
    monkeypatch.setenv("DIUCS_NEO4J_HEAP", "512m")
    monkeypatch.setenv("DIUCS_NEO4J_PAGECACHE", "300m")
    clock = FakeClock()
    docker = FakeDocker(clock)

    _start(docker, ScriptedProbe(clock, [True]), clock)

    args = docker.run_args()
    env = _values(args, "-e")
    assert _values(args, "--memory") == ["2g"]
    assert "NEO4J_server_memory_heap_initial__size=512m" in env
    assert "NEO4J_server_memory_heap_max__size=512m" in env
    assert "NEO4J_server_memory_pagecache_size=300m" in env


@pytest.mark.parametrize("variable", ["DIUCS_NEO4J_MEMORY", "DIUCS_NEO4J_HEAP"])
def test_a_limit_that_is_not_a_size_is_refused_before_docker_is_called(
    monkeypatch: pytest.MonkeyPatch, variable: str, tmp_path: Path
) -> None:
    monkeypatch.setenv(variable, "--privileged")
    clock = FakeClock()
    docker = FakeDocker(clock)

    with pytest.raises(HarnessStartError) as excinfo:
        _start(docker, ScriptedProbe(clock, [True]), clock)

    assert excinfo.value.phase == "config"
    assert variable in str(excinfo.value)
    assert docker.calls == []
    assert _lock_is_free(tmp_path)


def test_the_container_is_labelled_with_its_owner_process_and_start_time() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)

    _start(docker, ScriptedProbe(clock, [True]), clock)

    labels = _values(docker.run_args(), "--label")
    assert "diucs-test=true" in labels
    assert f"diucs-test-owner-pid={os.getpid()}" in labels
    marker = process_start_marker(os.getpid())
    assert marker is not None
    assert f"diucs-test-owner-start={marker}" in labels
    assert f"diucs-test-owner-host={socket.gethostname()}" in labels


def test_owner_labels_name_this_process_and_this_host() -> None:
    assert owner_labels() == {
        "diucs-test-owner-pid": str(os.getpid()),
        "diucs-test-owner-start": process_start_marker(os.getpid()),
        "diucs-test-owner-host": socket.gethostname(),
    }


def test_a_container_name_keeps_the_prefix_the_reaper_requires() -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)

    _start(docker, ScriptedProbe(clock, [True]), clock)

    assert docker.container_name().startswith("diucs-test-neo4j-")


# ---- failures of the docker run ---------------------------------------------------------------


def test_a_refused_run_fails_in_the_start_phase_and_removes_what_it_half_created(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    docker = FakeDocker(clock, run_ok=False)

    with pytest.raises(HarnessStartError) as excinfo:
        _start(docker, ScriptedProbe(clock, [True]), clock)

    assert excinfo.value.phase == "start"
    assert "Docker could not start the Neo4j test container" in str(excinfo.value)
    assert "port is already allocated" in str(excinfo.value)
    # docker run leaves a created container behind when the bind fails
    assert docker.removals() == [("rm", "-f", "-v", docker.container_name())]
    assert _lock_is_free(tmp_path)


def test_docker_missing_is_reported_as_not_available_in_the_start_phase(tmp_path: Path) -> None:
    clock = FakeClock()

    def missing(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    with pytest.raises(HarnessStartError) as excinfo:
        start_throwaway_neo4j(
            run=missing, probe=ScriptedProbe(clock, [True]), clock=clock, sleep=clock.sleep
        )

    assert excinfo.value.phase == "docker"
    assert "Docker is not available" in str(excinfo.value)
    assert _lock_is_free(tmp_path)


def test_a_docker_run_that_times_out_says_so_and_does_not_claim_docker_is_missing() -> None:
    clock = FakeClock()
    calls: list[tuple[str, ...]] = []

    def slow_run(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "run":
            raise subprocess.TimeoutExpired(cmd=["docker", *args], timeout=timeout)
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="", stderr="")

    with pytest.raises(HarnessStartError) as excinfo:
        start_throwaway_neo4j(
            run=slow_run, probe=ScriptedProbe(clock, [True]), clock=clock, sleep=clock.sleep
        )

    assert excinfo.value.phase == "start"
    assert "timed out" in str(excinfo.value)
    assert "not available" not in str(excinfo.value)
    assert [call for call in calls if call[:3] == ("rm", "-f", "-v")]


# ---- the lock ---------------------------------------------------------------------------------


def test_the_lock_is_held_while_the_container_lives_and_freed_when_it_is_removed(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    docker = FakeDocker(clock)

    container = _start(docker, ScriptedProbe(clock, [True]), clock)

    assert not _lock_is_free(tmp_path)
    stop_throwaway_neo4j(container, run=docker)
    assert docker.removals() == [("rm", "-f", "-v", container.name)]
    assert _lock_is_free(tmp_path)


def test_the_lock_is_taken_before_docker_is_asked_for_anything(tmp_path: Path) -> None:
    clock = FakeClock()
    seen: list[bool] = []
    docker = FakeDocker(clock)
    real_call = docker.__call__

    def checking(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        seen.append(not _lock_is_free(tmp_path))
        return real_call(*args, timeout=timeout)

    start_throwaway_neo4j(
        run=checking, probe=ScriptedProbe(clock, [True]), clock=clock, sleep=clock.sleep
    )

    assert seen and all(seen)


def test_a_lock_that_stays_taken_fails_in_the_lock_phase_naming_the_holder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "harness.lock"
    path.write_text("31337\n", encoding="utf-8")
    other = os.open(path, os.O_RDWR)
    fcntl.flock(other, fcntl.LOCK_EX)  # another process holds it, as far as this one can tell
    monkeypatch.setenv("DIUCS_NEO4J_LOCK_TIMEOUT", "0.3")
    clock = FakeClock()
    docker = FakeDocker(clock)
    try:
        with pytest.raises(HarnessStartError) as excinfo:
            start_throwaway_neo4j(
                run=docker, probe=ScriptedProbe(clock, [True]), clock=time.monotonic
            )
    finally:
        os.close(other)

    assert excinfo.value.phase == "lock"
    assert "31337" in str(excinfo.value)
    assert docker.calls == []
