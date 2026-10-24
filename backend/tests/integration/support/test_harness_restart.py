"""Restartable mode of the F11 Neo4j harness (DEC-008, DEC-013).

The harness container must survive `docker stop` and `docker start` so that the recovery tests
(G14) can take Neo4j down and bring it back. It must still be removed when its block exits.
These tests use their own throwaway container, so they never touch the session container that
other tests share.
"""

import subprocess

from tests.support.neo4j import (
    connect_or_fail,
    count_nodes,
    start_container,
    stop_container,
    throwaway_driver,
    wait_until_ready,
    write_tx,
)


def _docker_inspect(name: str, template: str) -> str:
    result = subprocess.run(
        ["docker", "inspect", "-f", template, name],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _container_exists(name: str) -> bool:
    result = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return name in result.stdout.split()


async def _create_probe(tx: object) -> None:
    await tx.run("CREATE (:Probe {id: 'restart'})")  # type: ignore[attr-defined]


async def test_harness_container_survives_stop_and_start_and_is_ready_again() -> None:
    async with throwaway_driver() as (container, driver):
        assert _docker_inspect(container.name, "{{.HostConfig.AutoRemove}}") == "false"
        container_id = _docker_inspect(container.name, "{{.Id}}")
        await write_tx(driver, _create_probe)

        stop_container(container)
        start_container(container)
        wait_until_ready(container)

        assert _docker_inspect(container.name, "{{.Id}}") == container_id
        assert _docker_inspect(container.name, "{{.State.Running}}") == "true"
        fresh = await connect_or_fail(
            container.uri, container.user, container.password, timeout_s=30
        )
        try:
            assert await count_nodes(fresh, "Probe") == 1
        finally:
            await fresh.close()


async def test_restarted_harness_container_is_removed_when_the_block_exits() -> None:
    async with throwaway_driver() as (container, _driver):
        stop_container(container)
        start_container(container)
        wait_until_ready(container)
        assert _container_exists(container.name)

    assert not _container_exists(container.name)
