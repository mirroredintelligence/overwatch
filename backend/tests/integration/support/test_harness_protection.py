"""Real-Docker checks of the F10b load protection (DEC-135). Run under the manual lock:
`flock /tmp/diucs-neo4j-tests.lock <command>`.

Two things only a real container can prove: the memory limit and the Neo4j settings were accepted
(a misspelt NEO4J_ variable would be ignored or would stop the container), and a run that dies
without cleaning up has its container removed by the next session's sweep.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.neo4j import (
    DEFAULT_CONTAINER_MEMORY,
    read_tx,
    reap_stale_test_containers,
    throwaway_driver,
)
from tests.support.proc import process_start_marker

BACKEND = Path(__file__).resolve().parents[3]

LEAK = """
from tests.support.neo4j import start_throwaway_neo4j
container = start_throwaway_neo4j()
print(container.name, flush=True)
"""


def _inspect(name: str) -> dict[str, object]:
    result = subprocess.run(
        ["docker", "inspect", name], capture_output=True, text=True, check=True, timeout=60
    )
    inspected: dict[str, object] = json.loads(result.stdout)[0]
    return inspected


def _container_names(prefix: str) -> set[str]:
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return {name for name in result.stdout.split() if name.startswith(prefix)}


async def test_a_real_container_has_its_memory_limit_neo4j_settings_and_owner_labels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DIUCS_NEO4J_LOCK", str(tmp_path / "harness.lock"))

    async with throwaway_driver() as (container, driver):
        inspected = _inspect(container.name)
        host_config = inspected["HostConfig"]
        config = inspected["Config"]
        assert isinstance(host_config, dict)
        assert isinstance(config, dict)
        assert DEFAULT_CONTAINER_MEMORY == "768m"
        assert host_config["Memory"] == 768 * 1024 * 1024
        assert config["Labels"]["diucs-test-owner-pid"] == str(os.getpid())
        assert config["Labels"]["diucs-test-owner-start"] == process_start_marker(os.getpid())

        async def settings(tx: object) -> dict[str, str]:
            result = await tx.run(  # type: ignore[attr-defined]
                "CALL dbms.listConfig('server.memory') YIELD name, value RETURN name, value"
            )
            return {row["name"]: row["value"] async for row in result}

        configured = await read_tx(driver, settings)  # type: ignore[arg-type]
        assert configured["server.memory.heap.max_size"] == "256.00MiB"
        assert configured["server.memory.heap.initial_size"] == "256.00MiB"
        assert configured["server.memory.pagecache.size"] == "128.00MiB"


def test_a_container_leaked_by_a_run_that_died_is_removed_by_the_next_sweep(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shared_stack_before = _container_names("diucs-local-")
    leaked = subprocess.run(
        [sys.executable, "-c", LEAK],
        cwd=BACKEND,
        env={
            **os.environ,
            "PYTHONPATH": str(BACKEND),
            "DIUCS_NEO4J_LOCK": str(tmp_path / "child.lock"),
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    name = leaked.stdout.strip().splitlines()[-1]
    try:
        assert name in _container_names(
            "diucs-test-neo4j-"
        )  # the owner is gone, the container is not

        removed = reap_stale_test_containers()

        assert name in removed
        assert name not in _container_names("diucs-test-neo4j-")
        assert _container_names("diucs-local-") == shared_stack_before
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, timeout=60)
