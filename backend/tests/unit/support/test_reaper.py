"""Unit tests for the stale-container reaper (F10, DEC-108). No Docker needed: the Docker command
runner is injected and records what it is asked to do."""

import subprocess
from datetime import UTC, datetime, timedelta

from tests.support.neo4j import reap_stale_test_containers

NOW = datetime(2026, 10, 27, 21, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=90)

# name, Created as docker prints it (RFC 3339 with nanoseconds), value of the diucs-test label
CONTAINERS = [
    ("diucs-test-neo4j-old", "2026-10-27T19:00:00.123456789Z", "true"),
    ("diucs-test-neo4j-new", "2026-10-27T20:30:00.000000000Z", "true"),
    ("diucs-local-neo4j", "2026-10-27T10:00:00.000000000Z", ""),
]


class FakeDocker:
    """Answers the three docker calls the reaper makes, and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[:2] == ("ps", "-a"):
            # Lists every container, labelled or not: the reaper must check the label itself.
            out = "\n".join(name for name, _, _ in CONTAINERS)
        elif args[0] == "inspect":
            # args are ("inspect", "--format", FORMAT, *names); docker prints the name with a slash.
            asked = set(args[3:])
            out = "\n".join(
                f"/{name}|{created}|{label}" for name, created, label in CONTAINERS if name in asked
            )
        else:
            out = ""
        return subprocess.CompletedProcess(
            args=["docker", *args], returncode=0, stdout=out, stderr=""
        )

    def removed(self) -> list[str]:
        return [call[2] for call in self.calls if call[:2] == ("rm", "-f")]


def test_reaper_removes_only_old_labelled_containers() -> None:
    docker = FakeDocker()

    removed = reap_stale_test_containers(MAX_AGE, run=docker, now=lambda: NOW)

    assert removed == ["diucs-test-neo4j-old"]
    assert docker.removed() == ["diucs-test-neo4j-old"]


def test_reaper_returns_nothing_and_does_not_raise_when_docker_is_missing() -> None:
    def no_docker(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("docker")

    assert reap_stale_test_containers(MAX_AGE, run=no_docker, now=lambda: NOW) == []


def test_reaper_returns_nothing_when_docker_refuses_to_list() -> None:
    def refused(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=list(args), returncode=1, stdout="", stderr="down")

    assert reap_stale_test_containers(MAX_AGE, run=refused, now=lambda: NOW) == []
