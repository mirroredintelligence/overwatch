"""Unit tests for how the harness removes throwaway Neo4j containers (F10-fix). The neo4j image
declares anonymous volumes, so removal must pass -v or every run leaks two volumes. No Docker
needed: the Docker command runner is replaced and records what it is asked to do."""

import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from tests.support import neo4j as harness
from tests.support.neo4j import ThrowawayNeo4j, reap_stale_test_containers, stop_throwaway_neo4j

NOW = datetime(2026, 10, 27, 21, 0, 0, tzinfo=UTC)
OLD = "2026-10-27T19:00:00.000000000Z"


def _done(args: tuple[str, ...], out: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["docker", *args], returncode=0, stdout=out, stderr="")


def _assert_removes_with_volumes(calls: list[tuple[str, ...]], name: str) -> None:
    removals = [c for c in calls if c and c[0] == "rm"]
    assert len(removals) == 1
    assert "-f" in removals[0]
    assert "-v" in removals[0]
    assert removals[0][-1] == name


def test_stop_throwaway_neo4j_removes_the_container_and_its_anonymous_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return _done(args)

    monkeypatch.setattr(harness, "_docker", fake)

    stop_throwaway_neo4j(ThrowawayNeo4j("diucs-test-neo4j-abc", "bolt://x", "u", "p"))

    _assert_removes_with_volumes(calls, "diucs-test-neo4j-abc")


def _reaper_docker(
    containers: list[tuple[str, str]], calls: list[tuple[str, ...]]
) -> harness.DockerRunner:
    def fake(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ("ps", "-a"):
            return _done(args, "\n".join(n for n, _ in containers))
        if args[0] == "inspect":
            asked = set(args[3:])
            return _done(args, "\n".join(f"/{n}|{c}|true" for n, c in containers if n in asked))
        return _done(args)

    return fake


def test_reaper_removes_a_stale_container_and_its_anonymous_volumes() -> None:
    calls: list[tuple[str, ...]] = []
    docker = _reaper_docker([("diucs-test-neo4j-old", OLD)], calls)

    removed = reap_stale_test_containers(timedelta(minutes=90), run=docker, now=lambda: NOW)

    assert removed == ["diucs-test-neo4j-old"]
    _assert_removes_with_volumes(calls, "diucs-test-neo4j-old")


def test_reaper_sweep_never_removes_a_container_outside_the_throwaway_prefix() -> None:
    calls: list[tuple[str, ...]] = []
    docker = _reaper_docker([("diucs-local-neo4j", OLD), ("other-app", OLD)], calls)

    removed = reap_stale_test_containers(timedelta(minutes=90), run=docker, now=lambda: NOW)

    assert removed == []
    assert [c for c in calls if c and c[0] == "rm"] == []
