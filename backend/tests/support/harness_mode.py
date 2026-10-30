"""Which Neo4j the integration harness uses (TEN-034)."""

import enum
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from neo4j import AsyncDriver

from tests.support.neo4j import DockerRunner, Probe, ThrowawayNeo4j
from tests.support.tenancy import RunIdentity

MODE_ENV = "DIUCS_TEST_NEO4J"
ALLOW_LOCAL_ENV = "DIUCS_TEST_NEO4J_ALLOW_LOCAL"
SHARED_NAME = "diucs-test-shared-neo4j"
SHARED_LABEL = "diucs-test-shared"


class Mode(enum.StrEnum):
    OWNED = "owned"
    SHARED = "shared"
    ATTACHED = "attached"


@dataclass(frozen=True, slots=True)
class Selection:
    mode: Mode
    uri: str | None = None
    user: str | None = None
    password: str | None = field(default=None, repr=False)


@dataclass(slots=True)
class HarnessDatabase:
    target: ThrowawayNeo4j
    driver: AsyncDriver
    mode: Mode
    swept: list[RunIdentity]


class ExclusiveUnderParallel(Exception):
    """An exclusive test was selected for a session that runs with parallel workers."""


def select_mode(environ: Mapping[str, str] | None = None) -> Selection:
    raise NotImplementedError


def shared_run_arguments(password: str) -> list[str]:
    raise NotImplementedError


def ensure_shared_neo4j(
    *,
    run: DockerRunner | None = None,
    probe: Probe | None = None,
    lock_path: str | None = None,
    sleep: Callable[[float], None] | None = None,
) -> ThrowawayNeo4j:
    raise NotImplementedError


def remove_shared_neo4j(*, run: DockerRunner | None = None) -> bool:
    raise NotImplementedError


def exclusive_selected(items: Iterable[Any]) -> bool:
    raise NotImplementedError


def refuse_exclusive_under_parallel(items: Iterable[Any], workers: int | None) -> None:
    raise NotImplementedError


@asynccontextmanager
async def open_harness_database(
    selection: Selection, *, exclusive: bool = False, own: RunIdentity | None = None
) -> AsyncIterator[HarnessDatabase]:
    raise NotImplementedError
    yield  # pragma: no cover
